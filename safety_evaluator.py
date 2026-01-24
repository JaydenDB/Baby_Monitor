"""
Safety evaluator for Baby Monitor.

This module aggregates multiple weak signals (position classifier output, motion metrics,
and observability/quality) over time to reduce single-frame noise and to avoid silent
failures when the monitor can't reliably see the baby.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Tuple

from config import (
    ALERT_POSITIONS,
    POSITION_UNKNOWN,
    SAFETY_WINDOW_SECONDS,
    UNSAFE_SUSPECT_SECONDS,
    UNSAFE_CONFIRM_SECONDS,
    OBSERVABILITY_DEGRADED_SECONDS,
    UNSAFE_SUSPECT_P_THRESHOLD,
    UNSAFE_CONFIRM_P_THRESHOLD,
    OBSERVABILITY_DEGRADED_THRESHOLD,
    CONSERVATIVE_DEFAULT_ENABLED,
    UNKNOWN_POSITION_ALARM_SECONDS,
)


@dataclass(frozen=True)
class SafetyResult:
    """
    Result of a single evaluation step.
    """

    state: str  # 'safe' | 'unsafe_suspected' | 'unsafe_confirmed' | 'degraded'
    position: str
    confidence: float
    method: str
    observability: float
    p_unsafe: float
    reason: str


class SafetyEvaluator:
    """
    Aggregates signals over time and provides a stable decision.

    Expected detector API:
      - position_detector.detect_position_with_diagnostics(frame) ->
            (position, confidence, method, diagnostics_dict)
    """

    def __init__(self, position_detector):
        self.position_detector = position_detector

        self._history: Deque[Dict] = deque()
        self._state: str = "safe"
        self._state_since: float = time.time()

    def update(self, frame) -> SafetyResult:
        now = time.time()

        position, confidence, method, diag = self.position_detector.detect_position_with_diagnostics(frame)

        observability = float(diag.get("observability", 0.0) or 0.0)
        observability = max(0.0, min(1.0, observability))

        # Evidence terms (0..1). These are *not* calibrated probabilities; they are weights.
        unsafe_evidence = 0.0
        safe_evidence = 0.0

        if position in ALERT_POSITIONS:
            unsafe_evidence = max(0.0, min(1.0, float(confidence)))
        elif position != POSITION_UNKNOWN:
            # "Safe" evidence should not be overconfident; cap it.
            safe_evidence = max(0.0, min(0.8, float(confidence)))

        self._append_history(
            now=now,
            position=position,
            confidence=float(confidence),
            method=method,
            observability=observability,
            unsafe_evidence=unsafe_evidence,
            safe_evidence=safe_evidence,
        )

        avg_obs, degraded_duration = self._observability_stats(now)
        p_unsafe = self._p_unsafe_over_window()
        unknown_duration = self._sustained_unknown_duration(now)

        # Decide state using sustained evidence + observability gating.
        if avg_obs <= OBSERVABILITY_DEGRADED_THRESHOLD and degraded_duration >= OBSERVABILITY_DEGRADED_SECONDS:
            state = "degraded"
            reason = f"low_observability(avg={avg_obs:.2f}, for={degraded_duration:.0f}s)"
        else:
            # If we can see reasonably well, decide based on sustained P(unsafe).
            if p_unsafe >= UNSAFE_CONFIRM_P_THRESHOLD and self._sustained_seconds(now, predicate="unsafe") >= UNSAFE_CONFIRM_SECONDS:
                state = "unsafe_confirmed"
                reason = f"p_unsafe={p_unsafe:.2f} sustained"
            elif p_unsafe >= UNSAFE_SUSPECT_P_THRESHOLD and self._sustained_seconds(now, predicate="unsafe") >= UNSAFE_SUSPECT_SECONDS:
                state = "unsafe_suspected"
                reason = f"p_unsafe={p_unsafe:.2f} rising"
            elif CONSERVATIVE_DEFAULT_ENABLED and unknown_duration >= UNKNOWN_POSITION_ALARM_SECONDS:
                # Conservative default: if we can't determine position for too long, err on side of caution
                state = "unsafe_suspected"
                reason = f"unknown_position_sustained({unknown_duration:.0f}s, conservative_default)"
            else:
                state = "safe"
                reason = f"p_unsafe={p_unsafe:.2f}"

        self._transition_if_needed(state, now)

        return SafetyResult(
            state=self._state,
            position=position,
            confidence=float(confidence),
            method=method,
            observability=observability,
            p_unsafe=p_unsafe,
            reason=reason,
        )

    def _append_history(
        self,
        *,
        now: float,
        position: str,
        confidence: float,
        method: str,
        observability: float,
        unsafe_evidence: float,
        safe_evidence: float,
    ) -> None:
        self._history.append(
            {
                "t": now,
                "position": position,
                "confidence": confidence,
                "method": method,
                "observability": observability,
                "unsafe_evidence": unsafe_evidence,
                "safe_evidence": safe_evidence,
            }
        )

        # Drop history older than our evaluation window.
        cutoff = now - SAFETY_WINDOW_SECONDS
        while self._history and self._history[0]["t"] < cutoff:
            self._history.popleft()

    def _p_unsafe_over_window(self) -> float:
        if not self._history:
            return 0.0

        unsafe = 0.0
        safe = 0.0
        eps = 1e-6

        for h in self._history:
            obs = float(h["observability"])
            unsafe += float(h["unsafe_evidence"]) * obs
            safe += float(h["safe_evidence"]) * obs

        # If we have no useful evidence, treat as low confidence unsafe (not 0.5) to avoid
        # spuriously entering unsafe states on missing data. Degraded state handles blindness.
        denom = unsafe + safe
        if denom < eps:
            return 0.0
        return max(0.0, min(1.0, unsafe / (denom + eps)))

    def _observability_stats(self, now: float) -> Tuple[float, float]:
        """
        Returns:
          - average_observability over recent window
          - how long we've been continuously below OBSERVABILITY_DEGRADED_THRESHOLD
        """
        if not self._history:
            return 0.0, 0.0

        avg_obs = sum(float(h["observability"]) for h in self._history) / len(self._history)

        # Duration below threshold (continuous, from newest backwards)
        duration = 0.0
        earliest_t = now
        for h in reversed(self._history):
            if float(h["observability"]) > OBSERVABILITY_DEGRADED_THRESHOLD:
                break
            earliest_t = float(h["t"])
            duration = now - earliest_t
        return avg_obs, duration

    def _sustained_seconds(self, now: float, *, predicate: str) -> float:
        """
        Compute how long the last samples have continuously met the predicate.
        predicate: 'unsafe' supported.
        """
        if not self._history:
            return 0.0

        if predicate != "unsafe":
            return 0.0

        # Continuous unsafe evidence above suspect threshold.
        earliest_t = now
        any_unsafe = False
        for h in reversed(self._history):
            obs = float(h["observability"])
            eff_unsafe = float(h["unsafe_evidence"]) * obs
            if eff_unsafe <= 0.0:
                break
            any_unsafe = True
            earliest_t = float(h["t"])

        return (now - earliest_t) if any_unsafe else 0.0

    def _sustained_unknown_duration(self, now: float) -> float:
        """
        Compute how long we've had consecutive 'unknown' positions.
        Used for conservative default alarm.
        """
        if not self._history:
            return 0.0

        earliest_t = now
        any_unknown = False
        for h in reversed(self._history):
            pos = str(h.get("position", ""))
            if pos != POSITION_UNKNOWN:
                break
            any_unknown = True
            earliest_t = float(h["t"])

        return (now - earliest_t) if any_unknown else 0.0

    def _transition_if_needed(self, new_state: str, now: float) -> None:
        if new_state != self._state:
            self._state = new_state
            self._state_since = now
