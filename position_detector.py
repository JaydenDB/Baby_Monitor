"""
Hybrid position detection combining MediaPipe Pose and motion detection
Handles errors gracefully and falls back to motion detection when needed
"""
import cv2
import mediapipe as mp
import logging
from config import (
    MEDIAPIPE_CONFIDENCE_THRESHOLD_HIGH,
    MEDIAPIPE_CONFIDENCE_THRESHOLD_MEDIUM,
    POSITION_BACK,
    POSITION_SIDE,
    POSITION_STOMACH,
    POSITION_UNKNOWN
)
from motion_detector import MotionDetector
from face_detector import FaceDetector

logger = logging.getLogger(__name__)


class PositionDetector:
    """Hybrid position detector using MediaPipe and motion detection"""
    
    def __init__(self):
        # Initialize MediaPipe Pose
        try:
            self.mp_pose = mp.solutions.pose
            self.pose = self.mp_pose.Pose(
                static_image_mode=False,
                model_complexity=1,  # 0=fast, 1=balanced, 2=accurate
                enable_segmentation=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.mediapipe_available = True
            logger.info("MediaPipe Pose initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize MediaPipe: {e}")
            self.mediapipe_available = False
            self.pose = None
        
        # Initialize motion detector as fallback
        self.motion_detector = MotionDetector()
        
        # Initialize face detector
        self.face_detector = FaceDetector()
        
        # Track detection method used
        self.last_method = None
        self.last_confidence = 0.0
    
    def detect_position(self, frame):
        """
        Detect baby position using hybrid approach
        Returns: (position, confidence, method_used)
        """
        position, confidence, method, _diag = self.detect_position_with_diagnostics(frame)
        return position, confidence, method

    def detect_position_with_diagnostics(self, frame):
        """
        Detect baby position using hybrid approach, returning diagnostics used for
        observability/quality evaluation.

        Returns: (position, confidence, method_used, diagnostics_dict)
        """
        diagnostics = {
            "mediapipe": None,
            "motion": None,
            "face": None,
            # Observability/quality score (0..1): how well we can see/track the baby.
            "observability": 0.0,
        }

        if frame is None:
            return POSITION_UNKNOWN, 0.0, 'none', diagnostics
        
        # Run face detection on every frame
        face_result = self.face_detector.detect_face(frame)
        diagnostics["face"] = dict(face_result)
        
        # Try MediaPipe first if available
        mediapipe_result = None
        if self.mediapipe_available and self.pose is not None:
            try:
                mediapipe_result = self._detect_with_mediapipe(frame)
            except Exception as e:
                logger.warning(f"MediaPipe detection failed: {e}")
                mediapipe_result = None

        if mediapipe_result is not None:
            diagnostics["mediapipe"] = dict(mediapipe_result)
        
        # Determine which method to use based on MediaPipe confidence
        if mediapipe_result and mediapipe_result['confidence'] >= MEDIAPIPE_CONFIDENCE_THRESHOLD_HIGH:
            # High confidence - use MediaPipe result, but apply face detection logic
            position, confidence = self._apply_face_detection_logic(
                mediapipe_result['position'], mediapipe_result['confidence'],
                None, 0.0, face_result
            )
            self.last_method = 'mediapipe'
            self.last_confidence = confidence
            # Boost observability if face detected
            obs = float(mediapipe_result["confidence"])
            if face_result.get("face_detected"):
                obs = min(1.0, obs + face_result.get("face_confidence", 0.0) * 0.2)
            diagnostics["observability"] = obs
            return position, confidence, 'mediapipe', diagnostics
        
        elif mediapipe_result and mediapipe_result['confidence'] >= MEDIAPIPE_CONFIDENCE_THRESHOLD_MEDIUM:
            # Medium confidence - use both methods and require agreement
            # Pass face detection result to motion detector
            motion_position, motion_confidence, motion_metrics = self.motion_detector.detect_position_with_metrics(
                frame, face_detected=face_result["face_detected"]
            )
            diagnostics["motion"] = {
                "position": motion_position,
                "confidence": motion_confidence,
                "metrics": motion_metrics,
            }
            
            # Apply face detection logic to refine position
            position, confidence = self._apply_face_detection_logic(
                mediapipe_result['position'], mediapipe_result['confidence'],
                motion_position, motion_confidence, face_result
            )
            
            # If both methods agree, use the result with higher confidence
            if position == mediapipe_result['position'] or position == motion_position:
                if position == mediapipe_result['position'] == motion_position:
                    combined_confidence = (mediapipe_result['confidence'] + motion_confidence) / 2
                else:
                    combined_confidence = max(mediapipe_result['confidence'], motion_confidence)
                self.last_method = 'hybrid'
                self.last_confidence = combined_confidence
                diagnostics["observability"] = float(max(mediapipe_result["confidence"], self._observability_from_motion(motion_metrics, face_result)))
                return position, combined_confidence, 'hybrid', diagnostics
            else:
                # Methods disagree - use face-informed result
                logger.info(f"Methods disagree: MediaPipe={mediapipe_result['position']}, "
                          f"Motion={motion_position}, Face={face_result['face_detected']}, using {position}")
                self.last_method = 'motion'
                self.last_confidence = confidence
                diagnostics["observability"] = float(max(mediapipe_result["confidence"], self._observability_from_motion(motion_metrics, face_result)))
                return position, confidence, 'motion', diagnostics
        
        else:
            # Low confidence or MediaPipe unavailable - use motion detection
            # Pass face detection result to motion detector
            motion_position, motion_confidence, motion_metrics = self.motion_detector.detect_position_with_metrics(
                frame, face_detected=face_result["face_detected"]
            )
            self.last_method = 'motion'
            self.last_confidence = motion_confidence
            diagnostics["motion"] = {
                "position": motion_position,
                "confidence": motion_confidence,
                "metrics": motion_metrics,
            }
            
            # Apply face detection logic to refine position
            position, confidence = self._apply_face_detection_logic(
                None, 0.0, motion_position, motion_confidence, face_result
            )
            
            diagnostics["observability"] = float(self._observability_from_motion(motion_metrics, face_result))
            return position, confidence, 'motion', diagnostics

    def _apply_face_detection_logic(self, mediapipe_position, mediapipe_confidence,
                                   motion_position, motion_confidence, face_result):
        """
        Apply face detection results to refine position classification.
        
        Logic:
        - Face visible → likely back or side (face up)
        - Face NOT visible + horizontal body → likely stomach (face down)
        - Face visible + classified as stomach → contradiction, reduce confidence
        - Face visible + side with low confidence → likely back with head tilt, reclassify as back
        - Face visible + side with high confidence → keep as side but reduce confidence slightly
        """
        face_detected = face_result.get("face_detected", False)
        face_confidence = face_result.get("face_confidence", 0.0)
        
        # Use the position from whichever method we're using
        position = motion_position if mediapipe_position is None else mediapipe_position
        confidence = motion_confidence if mediapipe_position is None else mediapipe_confidence
        
        if face_detected:
            # Face visible → likely back or side (face up)
            if position == POSITION_STOMACH:
                # Contradiction: face visible but classified as stomach
                logger.debug("Face detected but position is stomach - reducing confidence")
                confidence = max(0.2, confidence * 0.5)
            elif position == POSITION_SIDE:
                # Face visible + side position: could be back with head tilted
                # If confidence is low, it's more likely to be back with head tilt than true side
                if confidence < 0.6:
                    logger.debug(f"Face detected but position is side with low confidence ({confidence:.2f}) - "
                               f"likely back with head tilt, reclassifying as back")
                    position = POSITION_BACK
                    # Use face confidence as primary signal since face is clearly visible
                    confidence = min(0.7, face_confidence * 0.9)
                else:
                    # High confidence side with face visible - could be true side position
                    # Keep as side but note that face is visible (less concerning than side without face)
                    logger.debug("Face detected with side position and high confidence - keeping as side")
                    # Slightly reduce confidence since face visible suggests it might be back with tilt
                    confidence = max(confidence * 0.85, 0.5)
            elif position == POSITION_UNKNOWN:
                # Face visible but unknown → likely back
                position = POSITION_BACK
                confidence = min(0.6, face_confidence * 0.8)
            elif position == POSITION_BACK:
                # Face visible confirms back position
                confidence = min(1.0, confidence + face_confidence * 0.2)
        else:
            # Face NOT visible
            if position == POSITION_BACK and motion_confidence < 0.5:
                # No face + low confidence back → suspicious, prefer unknown
                logger.debug("No face detected but position is back with low confidence - preferring unknown")
                position = POSITION_UNKNOWN
                confidence = 0.3
            elif position == POSITION_UNKNOWN:
                # No face + unknown + we have body detection → could be stomach
                # But don't assume - keep as unknown with lower confidence
                confidence = max(0.2, confidence * 0.7)
        
        return position, confidence
    
    def _observability_from_motion(self, motion_metrics, face_result=None):
        """
        Convert motion metrics into an observability score (0..1).
        This does NOT assert safe/unsafe; it estimates whether we can see meaningful signal.
        
        Args:
            face_result: Optional face detection result to boost observability
        """
        if not motion_metrics:
            return 0.0
        if motion_metrics.get("lighting_change") or motion_metrics.get("full_frame_motion"):
            return 0.0
        if motion_metrics.get("background_learning"):
            return 0.2

        # Area ratio of the largest contour is a crude proxy for baby presence in frame.
        area_ratio = float(motion_metrics.get("area_ratio") or 0.0)
        # Map ~2% of frame to ~1.0 observability (tunable).
        obs = min(1.0, area_ratio / 0.02) if area_ratio > 0 else 0.0
        
        # Face detection can boost observability (we can see the baby better)
        if face_result and face_result.get("face_detected"):
            face_boost = face_result.get("face_confidence", 0.0) * 0.2
            obs = min(1.0, obs + face_boost)
        
        return max(0.0, min(1.0, obs))
    
    def _detect_with_mediapipe(self, frame):
        """
        Detect position using MediaPipe Pose
        Returns: {'position': str, 'confidence': float} or None
        """
        try:
            # Convert BGR to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Process frame
            results = self.pose.process(rgb_frame)
            
            if not results.pose_landmarks:
                return {'position': POSITION_UNKNOWN, 'confidence': 0.0}
            
            # Extract key landmarks
            landmarks = results.pose_landmarks.landmark
            
            # Get key points (using MediaPipe pose landmark indices)
            # 0: nose, 11: left shoulder, 12: right shoulder
            # 23: left hip, 24: right hip
            nose = landmarks[0]
            left_shoulder = landmarks[11]
            right_shoulder = landmarks[12]
            left_hip = landmarks[23]
            right_hip = landmarks[24]
            
            # Calculate confidence based on visibility of key points
            visible_points = sum([
                nose.visibility > 0.5,
                left_shoulder.visibility > 0.5,
                right_shoulder.visibility > 0.5,
                left_hip.visibility > 0.5,
                right_hip.visibility > 0.5
            ])
            confidence = visible_points / 5.0
            
            if confidence < 0.3:
                return {'position': POSITION_UNKNOWN, 'confidence': confidence}
            
            # Analyze position based on keypoint relationships
            position = self._analyze_mediapipe_position(
                nose, left_shoulder, right_shoulder, left_hip, right_hip
            )
            
            return {'position': position, 'confidence': confidence}
            
        except Exception as e:
            logger.error(f"Error in MediaPipe detection: {e}")
            return None
    
    def _analyze_mediapipe_position(self, nose, left_shoulder, right_shoulder, 
                                    left_hip, right_hip):
        """
        Analyze position from MediaPipe keypoints
        Returns: position string
        """
        # Calculate shoulder and hip positions
        shoulder_center_y = (left_shoulder.y + right_shoulder.y) / 2
        hip_center_y = (left_hip.y + right_hip.y) / 2
        shoulder_width = abs(left_shoulder.x - right_shoulder.x)
        hip_width = abs(left_hip.x - right_hip.x)
        
        # Calculate body orientation
        body_vertical = abs(hip_center_y - shoulder_center_y)
        body_horizontal = (shoulder_width + hip_width) / 2
        
        # Nose position relative to body
        nose_to_shoulder_y = abs(nose.y - shoulder_center_y)
        
        # Back position: body horizontal, nose above shoulders
        if body_horizontal > body_vertical * 1.5:  # Body is horizontal
            if nose_to_shoulder_y < body_vertical * 0.3:  # Nose close to shoulder level
                return POSITION_BACK
        
        # Side position: body rotated, significant lateral offset
        lateral_offset = abs((left_shoulder.x + right_shoulder.x) / 2 - 
                            (left_hip.x + right_hip.x) / 2)
        if lateral_offset > body_horizontal * 0.3:
            return POSITION_SIDE
        
        # Stomach position: body horizontal, nose further from camera than shoulders (face down)
        shoulder_center_z = (left_shoulder.z + right_shoulder.z) / 2
        if nose.z > shoulder_center_z:  # Nose "deeper" than shoulders (face down)
            return POSITION_STOMACH
        
        # Default to back if horizontal
        if body_horizontal > body_vertical:
            return POSITION_BACK
        
        return POSITION_UNKNOWN
