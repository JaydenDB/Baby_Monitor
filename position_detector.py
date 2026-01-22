"""
Hybrid position detection combining MediaPipe Pose and motion detection
Handles errors gracefully and falls back to motion detection when needed
"""
import cv2
import mediapipe as mp
import numpy as np
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
        
        # Track detection method used
        self.last_method = None
        self.last_confidence = 0.0
    
    def detect_position(self, frame):
        """
        Detect baby position using hybrid approach
        Returns: (position, confidence, method_used)
        """
        if frame is None:
            return POSITION_UNKNOWN, 0.0, 'none'
        
        # Try MediaPipe first if available
        mediapipe_result = None
        if self.mediapipe_available and self.pose is not None:
            try:
                mediapipe_result = self._detect_with_mediapipe(frame)
            except Exception as e:
                logger.warning(f"MediaPipe detection failed: {e}")
                mediapipe_result = None
        
        # Determine which method to use based on MediaPipe confidence
        if mediapipe_result and mediapipe_result['confidence'] >= MEDIAPIPE_CONFIDENCE_THRESHOLD_HIGH:
            # High confidence - use MediaPipe result
            self.last_method = 'mediapipe'
            self.last_confidence = mediapipe_result['confidence']
            return mediapipe_result['position'], mediapipe_result['confidence'], 'mediapipe'
        
        elif mediapipe_result and mediapipe_result['confidence'] >= MEDIAPIPE_CONFIDENCE_THRESHOLD_MEDIUM:
            # Medium confidence - use both methods and require agreement
            motion_result = self.motion_detector.detect_position(frame)
            motion_position, motion_confidence = motion_result
            
            # If both methods agree, use the result with higher confidence
            if motion_position == mediapipe_result['position']:
                combined_confidence = (mediapipe_result['confidence'] + motion_confidence) / 2
                self.last_method = 'hybrid'
                self.last_confidence = combined_confidence
                return mediapipe_result['position'], combined_confidence, 'hybrid'
            else:
                # Methods disagree - use motion detection (more reliable for babies)
                logger.info(f"Methods disagree: MediaPipe={mediapipe_result['position']}, "
                          f"Motion={motion_position}, using motion detection")
                self.last_method = 'motion'
                self.last_confidence = motion_confidence
                return motion_position, motion_confidence, 'motion'
        
        else:
            # Low confidence or MediaPipe unavailable - use motion detection
            motion_position, motion_confidence = self.motion_detector.detect_position(frame)
            self.last_method = 'motion'
            self.last_confidence = motion_confidence
            return motion_position, motion_confidence, 'motion'
    
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
        
        # Stomach position: body horizontal, nose below shoulders (face down)
        if body_horizontal > body_vertical * 1.5:
            if nose.y > hip_center_y:  # Nose below hips (face down)
                return POSITION_STOMACH
        
        # Default to back if horizontal
        if body_horizontal > body_vertical:
            return POSITION_BACK
        
        return POSITION_UNKNOWN
    
    def get_last_method(self):
        """Get the detection method used in last detection"""
        return self.last_method
    
    def get_last_confidence(self):
        """Get the confidence from last detection"""
        return self.last_confidence
