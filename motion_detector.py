"""
Motion-based position detection fallback
Uses background subtraction and contour analysis when MediaPipe fails
"""
import cv2
import numpy as np
import logging
from config import MOTION_DETECTION_THRESHOLD, CONTOUR_MIN_AREA

logger = logging.getLogger(__name__)


class MotionDetector:
    """Detects baby position using motion and contour analysis"""
    
    def __init__(self):
        # Reduced history from 500 to 100 to save memory on Raspberry Pi
        # 100 frames is sufficient for background learning while using ~80% less memory
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=100, varThreshold=50, detectShadows=True
        )
        self.frame_count = 0
        self.background_learning_frames = 30  # Learn background for first N frames
        self.last_position = None
        self._morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        # Track brightness for lighting change detection
        self.brightness_history = []  # Store last N brightness values
        self.brightness_history_size = 5  # Track last 5 frames
        self.brightness_change_threshold = 30  # Significant brightness change (0-255 scale)
        
    def detect_position(self, frame):
        """
        Detect baby position from frame using motion detection
        Returns: (position, confidence)
        - position: 'back', 'side', 'stomach', or 'unknown'
        - confidence: 0.0 to 1.0
        """
        position, confidence, _metrics = self.detect_position_with_metrics(frame)
        return position, confidence

    def detect_position_with_metrics(self, frame, face_detected=False):
        """
        Detect baby position from frame using motion detection, with diagnostics.

        Args:
            frame: Input frame
            face_detected: Optional face detection result (True if face is visible)

        Returns: (position, confidence, metrics_dict)
        """
        metrics = {
            "frame_count": self.frame_count,
            "background_learning": True,
            "lighting_change": False,
            "full_frame_motion": False,
            "brightness": None,
            "motion_ratio": 0.0,
            "motion_pixels": 0,
            "largest_contour_area": 0.0,
            "area_ratio": 0.0,
        }

        if frame is None:
            return 'unknown', 0.0, metrics

        try:
            self.frame_count += 1
            metrics["frame_count"] = self.frame_count

            # Convert to grayscale for processing
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Calculate current frame brightness
            current_brightness = float(np.mean(gray))
            metrics["brightness"] = current_brightness

            # Check for sudden brightness changes (lighting changes)
            if self._is_lighting_change(current_brightness, gray.shape):
                metrics["lighting_change"] = True
                logger.debug(
                    f"Ignoring detection due to lighting change (brightness: {current_brightness:.1f})"
                )
                self._update_brightness_history(current_brightness)
                return 'unknown', 0.0, metrics

            # Update brightness history
            self._update_brightness_history(current_brightness)

            # Apply background subtraction
            fg_mask = self.background_subtractor.apply(gray)

            # Skip if still learning background
            if self.frame_count < self.background_learning_frames:
                metrics["background_learning"] = True
                return 'unknown', 0.0, metrics

            metrics["background_learning"] = False

            # Apply morphological operations to reduce noise
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, self._morph_kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, self._morph_kernel)

            # Prefer high-confidence foreground pixels (avoid counting MOG2 shadows as motion)
            motion_pixels = int(np.sum(fg_mask > 200))
            frame_area = int(frame.shape[0] * frame.shape[1])
            motion_ratio = (motion_pixels / frame_area) if frame_area > 0 else 0.0
            metrics["motion_pixels"] = motion_pixels
            metrics["motion_ratio"] = float(motion_ratio)

            # Check if motion covers most of frame (often lighting change / camera bump)
            if motion_ratio > 0.7:
                metrics["full_frame_motion"] = True
                logger.debug(
                    f"Ignoring detection: motion covers {motion_ratio:.1%} of frame (likely lighting change)"
                )
                return 'unknown', 0.0, metrics

            # Find contours
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return 'unknown', 0.0, metrics

            # Find largest contour (likely the baby)
            largest_contour = max(contours, key=cv2.contourArea)
            area = float(cv2.contourArea(largest_contour))
            metrics["largest_contour_area"] = area
            metrics["area_ratio"] = float(area / frame_area) if frame_area > 0 else 0.0

            if area < CONTOUR_MIN_AREA:
                return 'unknown', 0.0, metrics

            # Get bounding box and analyze shape
            x, y, w, h = cv2.boundingRect(largest_contour)
            aspect_ratio = w / h if h > 0 else 0
            center_x = x + w / 2
            frame_center_x = frame.shape[1] / 2

            # Store face detection result in metrics for diagnostics
            metrics["face_detected"] = face_detected
            
            # Analyze position based on shape and movement
            position, confidence = self._analyze_position(
                aspect_ratio, motion_ratio, motion_pixels, center_x, frame_center_x, area,
                face_detected=face_detected
            )

            self.last_position = position
            return position, confidence, metrics

        except Exception as e:
            logger.error(f"Error in motion detection: {e}")
            return 'unknown', 0.0, metrics
    
    def _analyze_position(self, aspect_ratio, motion_ratio, motion_pixels, 
                         center_x, frame_center_x, area, face_detected=False):
        """
        Analyze position based on detected features
        Returns: (position, confidence)
        
        Args:
            face_detected: If True, we have strong evidence of face-up position
        """
        # High motion suggests position change (rolling)
        if motion_pixels > MOTION_DETECTION_THRESHOLD:
            # Significant lateral movement suggests side position
            lateral_offset = abs(center_x - frame_center_x)
            if lateral_offset > frame_center_x * 0.3:  # Moved significantly to side
                return 'side', min(0.7, motion_ratio * 10)
            
            # High motion with low aspect ratio might indicate rolling to stomach
            if aspect_ratio < 0.8:
                return 'stomach', min(0.6, motion_ratio * 8)
        
        # Low motion: be conservative - only classify as 'back' with strong evidence
        if motion_pixels < MOTION_DETECTION_THRESHOLD * 0.3:
            # Only return 'back' if we have strong positive evidence (face detected)
            # This prevents false negatives when baby is still on stomach/side
            if face_detected:
                # Face visible is strong evidence of face-up (back or side)
                if 0.8 < aspect_ratio < 1.5:  # Roughly horizontal rectangle
                    if abs(center_x - frame_center_x) < frame_center_x * 0.2:  # Centered
                        return 'back', 0.6
            # Without face evidence, prefer 'unknown' over assuming 'back'
            # This is the key change to reduce Type II errors
        
        # Uncertain - not enough information
        return 'unknown', 0.3
    
    def _update_brightness_history(self, brightness):
        """Update brightness history, keeping only recent values"""
        self.brightness_history.append(brightness)
        if len(self.brightness_history) > self.brightness_history_size:
            self.brightness_history.pop(0)
    
    def _is_lighting_change(self, current_brightness, frame_shape):
        """
        Detect if there's a sudden full-frame brightness change
        Returns True if lighting change detected
        """
        if len(self.brightness_history) < 2:
            # Not enough history yet
            return False
        
        # Calculate average of recent brightness (history does not include current)
        recent_avg = float(np.mean(self.brightness_history)) if self.brightness_history else current_brightness
        
        # Check for sudden brightness change
        brightness_change = abs(current_brightness - recent_avg)
        
        if brightness_change > self.brightness_change_threshold:
            # Significant brightness change detected
            # This likely indicates a light being turned on/off
            return True
        
        return False
    
    def reset_background(self):
        """Reset background model (useful after long periods of inactivity)"""
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=100, varThreshold=50, detectShadows=True
        )
        self.frame_count = 0
        self.brightness_history = []  # Reset brightness tracking
        logger.info("Background model reset")
