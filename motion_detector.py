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
        if frame is None:
            return 'unknown', 0.0
        
        try:
            self.frame_count += 1
            
            # Convert to grayscale for processing
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Calculate current frame brightness
            current_brightness = np.mean(gray)
            
            # Check for sudden brightness changes (lighting changes)
            if self._is_lighting_change(current_brightness, gray.shape):
                logger.debug(f"Ignoring detection due to lighting change (brightness: {current_brightness:.1f})")
                # Update brightness history but return unknown
                self._update_brightness_history(current_brightness)
                return 'unknown', 0.0
            
            # Update brightness history
            self._update_brightness_history(current_brightness)
            
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
            
            # Check if motion covers most of frame (indicates lighting change, not baby movement)
            if motion_ratio > 0.7:  # More than 70% of frame has motion
                logger.debug(f"Ignoring detection: motion covers {motion_ratio:.1%} of frame (likely lighting change)")
                return 'unknown', 0.0
            
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
        
        # Calculate average of recent brightness (excluding current)
        recent_avg = np.mean(self.brightness_history[:-1]) if len(self.brightness_history) > 1 else current_brightness
        
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
