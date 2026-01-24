"""
Face detection module for Baby Monitor
Uses MediaPipe Face Detection to identify face visibility for position classification
"""
import cv2
import mediapipe as mp
import logging
from typing import Dict

from config import ENABLE_FACE_DETECTION, FACE_DETECTION_MIN_CONFIDENCE

logger = logging.getLogger(__name__)


class FaceDetector:
    """Detects faces in frames using MediaPipe Face Detection"""
    
    def __init__(self):
        self.enabled = bool(ENABLE_FACE_DETECTION)
        self.min_confidence = float(FACE_DETECTION_MIN_CONFIDENCE)
        self.face_detection = None
        self.available = False
        
        if self.enabled:
            try:
                self.mp_face_detection = mp.solutions.face_detection
                self.face_detection = self.mp_face_detection.FaceDetection(
                    model_selection=0,  # 0=short-range (2m), 1=full-range (5m)
                    min_detection_confidence=self.min_confidence
                )
                self.available = True
                logger.info("MediaPipe Face Detection initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize MediaPipe Face Detection: {e}")
                self.face_detection = None
                self.available = False
        else:
            logger.info("Face detection disabled in configuration")
    
    def detect_face(self, frame) -> Dict:
        """
        Detect faces in the frame
        
        Returns:
            dict with keys:
                - face_detected: bool
                - face_confidence: float (0-1), highest confidence if multiple faces
                - face_count: int
                - largest_face_bbox: tuple (x, y, w, h) or None
        """
        result = {
            "face_detected": False,
            "face_confidence": 0.0,
            "face_count": 0,
            "largest_face_bbox": None,
        }
        
        if not self.enabled or not self.available or self.face_detection is None:
            return result
        
        if frame is None:
            return result
        
        try:
            # Convert BGR to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Process frame
            results = self.face_detection.process(rgb_frame)
            
            if results.detections:
                result["face_count"] = len(results.detections)
                result["face_detected"] = True
                
                # Find the largest face (by bounding box area)
                largest_area = 0
                largest_bbox = None
                highest_confidence = 0.0
                
                h, w = frame.shape[:2]
                
                for detection in results.detections:
                    confidence = detection.score[0] if hasattr(detection, 'score') else 0.0
                    highest_confidence = max(highest_confidence, confidence)
                    
                    # Get bounding box
                    bbox = detection.location_data.relative_bounding_box
                    x = int(bbox.xmin * w)
                    y = int(bbox.ymin * h)
                    width = int(bbox.width * w)
                    height = int(bbox.height * h)
                    area = width * height
                    
                    if area > largest_area:
                        largest_area = area
                        largest_bbox = (x, y, width, height)
                
                result["face_confidence"] = float(highest_confidence)
                result["largest_face_bbox"] = largest_bbox
                
        except Exception as e:
            logger.error(f"Error in face detection: {e}")
            # Return default result on error
        
        return result
    
    def is_available(self) -> bool:
        """Check if face detection is available and enabled"""
        return self.enabled and self.available
