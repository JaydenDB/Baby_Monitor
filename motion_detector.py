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
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=50, detectShadows=True
        )
        self.frame_count = 0
        self.background_learning_frames = 30  # Learn background for first N frames
        self.last_position = None
        
    def detect_position(self, frame):
        """
        Detect baby position from frame using motion detection
        Returns: (position, confidence)
        - position: 'back', 'side', 'stomach', or 'unknown'
        - confidence: 0.0 to 1.0
        """
        if frame is None:
            return 'unknown', 0.0
        
        try:
            self.frame_count += 1
            
            # Convert to grayscale for processing
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Apply background subtraction
            fg_mask = self.background_subtractor.apply(gray)
            
            # Skip if still learning background
            if self.frame_count < self.background_learning_frames:
                return 'unknown', 0.0
            
            # Apply morphological operations to reduce noise
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            
            # Find contours
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                return 'unknown', 0.0
            
            # Find largest contour (likely the baby)
            largest_contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest_contour)
            
            if area < CONTOUR_MIN_AREA:
                return 'unknown', 0.0
            
            # Calculate motion amount
            motion_pixels = np.sum(fg_mask > 0)
            motion_ratio = motion_pixels / (frame.shape[0] * frame.shape[1])
            
            # Get bounding box and analyze shape
            x, y, w, h = cv2.boundingRect(largest_contour)
            aspect_ratio = w / h if h > 0 else 0
            center_x = x + w / 2
            frame_center_x = frame.shape[1] / 2
            
            # Analyze position based on shape and movement
            position, confidence = self._analyze_position(
                aspect_ratio, motion_ratio, motion_pixels, center_x, frame_center_x, area
            )
            
            self.last_position = position
            return position, confidence
            
        except Exception as e:
            logger.error(f"Error in motion detection: {e}")
            return 'unknown', 0.0
    
    def _analyze_position(self, aspect_ratio, motion_ratio, motion_pixels, 
                         center_x, frame_center_x, area):
        """
        Analyze position based on detected features
        Returns: (position, confidence)
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
        
        # Low motion with centered, wide shape suggests back position
        if motion_pixels < MOTION_DETECTION_THRESHOLD * 0.3:
            if 0.8 < aspect_ratio < 1.5:  # Roughly horizontal rectangle
                if abs(center_x - frame_center_x) < frame_center_x * 0.2:  # Centered
                    return 'back', 0.5
        
        # Uncertain - not enough information
        return 'unknown', 0.3
    
    def reset_background(self):
        """Reset background model (useful after long periods of inactivity)"""
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=50, detectShadows=True
        )
        self.frame_count = 0
        logger.info("Background model reset")
