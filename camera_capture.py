"""
Camera capture module for Baby Monitor
Handles webcam access with error handling and retry logic
"""
import cv2
import logging
import time
from config import CAMERA_INDEX, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS

logger = logging.getLogger(__name__)


class CameraCapture:
    """Handles camera initialization and frame capture with error recovery"""
    
    def __init__(self):
        self.camera = None
        self.camera_index = CAMERA_INDEX
        self.width = CAMERA_WIDTH
        self.height = CAMERA_HEIGHT
        self.fps = CAMERA_FPS
        self.last_error_time = 0
        self.error_retry_interval = 5  # Retry every 5 seconds
        
    def initialize(self):
        """Initialize camera connection"""
        try:
            self.camera = cv2.VideoCapture(self.camera_index)
            
            if not self.camera.isOpened():
                raise Exception(f"Camera {self.camera_index} failed to open")
            
            # Set camera properties
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.camera.set(cv2.CAP_PROP_FPS, self.fps)
            
            logger.info(f"Camera {self.camera_index} initialized successfully")
            logger.info(f"Resolution: {self.width}x{self.height}, FPS: {self.fps}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            self.camera = None
            return False
    
    def capture_frame(self):
        """
        Capture a single frame from the camera
        Returns frame (numpy array) or None if capture fails
        """
        # Try to reconnect if camera is not available
        if self.camera is None or not self.camera.isOpened():
            current_time = time.time()
            # Only retry if enough time has passed
            if current_time - self.last_error_time > self.error_retry_interval:
                logger.info("Attempting to reconnect to camera...")
                if self.initialize():
                    self.last_error_time = 0
                else:
                    self.last_error_time = current_time
                    return None
            else:
                return None
        
        try:
            ret, frame = self.camera.read()
            
            if not ret or frame is None:
                logger.warning("Failed to capture frame from camera")
                self.camera.release()
                self.camera = None
                return None
            
            return frame
            
        except Exception as e:
            logger.error(f"Error capturing frame: {e}")
            try:
                if self.camera is not None:
                    self.camera.release()
            except:
                pass
            self.camera = None
            return None
    
    def release(self):
        """Release camera resources"""
        try:
            if self.camera is not None:
                self.camera.release()
                logger.info("Camera released")
        except Exception as e:
            logger.error(f"Error releasing camera: {e}")
        finally:
            self.camera = None
    
    def is_available(self):
        """Check if camera is available and working"""
        return self.camera is not None and self.camera.isOpened()
