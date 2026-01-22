"""
Main program for Baby Monitor
Continuous monitoring loop with error handling
"""
import logging
import time
import sys
from datetime import datetime
from config import (
    CHECK_INTERVAL,
    ALERT_REQUIRE_CONFIDENCE,
    ALERT_POSITIONS,
    POSITION_BACK,
    POSITION_SIDE,
    POSITION_STOMACH,
    POSITION_UNKNOWN,
    LOG_LEVEL,
    LOG_FILE,
    LOG_TO_CONSOLE
)
from camera_capture import CameraCapture
from position_detector import PositionDetector
from alert_system import AlertSystem

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        *([logging.StreamHandler(sys.stdout)] if LOG_TO_CONSOLE else [])
    ]
)

logger = logging.getLogger(__name__)


class BabyMonitor:
    """Main baby monitor application"""
    
    def __init__(self):
        self.camera = CameraCapture()
        self.position_detector = PositionDetector()
        self.alert_system = AlertSystem()
        self.running = False
        self.frame_count = 0
        self.last_position = None
        self.last_alert_position = None
        
    def initialize(self):
        """Initialize all components"""
        logger.info("Initializing Baby Monitor...")
        
        # Initialize camera
        if not self.camera.initialize():
            logger.error("Failed to initialize camera. Please check camera connection.")
            return False
        
        # Test alert system
        if not self.alert_system.test_connection():
            logger.warning("Alert system connection test failed. Alerts may not work.")
        
        logger.info("Baby Monitor initialized successfully")
        return True
    
    def run(self):
        """Main monitoring loop"""
        if not self.initialize():
            logger.error("Initialization failed. Exiting.")
            return
        
        self.running = True
        logger.info("Starting baby monitoring...")
        logger.info(f"Check interval: {CHECK_INTERVAL} seconds")
        logger.info(f"Alert confidence threshold: {ALERT_REQUIRE_CONFIDENCE:.0%}")
        
        try:
            while self.running:
                self._monitor_cycle()
                time.sleep(CHECK_INTERVAL)
                
        except KeyboardInterrupt:
            logger.info("Received interrupt signal. Shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def _monitor_cycle(self):
        """Single monitoring cycle"""
        try:
            # Capture frame
            frame = self.camera.capture_frame()
            
            if frame is None:
                logger.warning("Failed to capture frame. Skipping cycle.")
                return
            
            self.frame_count += 1
            
            # Detect position
            position, confidence, method = self.position_detector.detect_position(frame)
            
            # Log detection result
            if position != self.last_position:
                logger.info(
                    f"Position detected: {position} "
                    f"(confidence: {confidence:.0%}, method: {method})"
                )
                self.last_position = position
            
            # Check if alert is needed
            if position in ALERT_POSITIONS:
                if confidence >= ALERT_REQUIRE_CONFIDENCE:
                    # Only alert if position changed (avoid repeated alerts)
                    if position != self.last_alert_position:
                        logger.warning(
                            f"ALERT: Baby on {position} (confidence: {confidence:.0%})"
                        )
                        self.alert_system.send_alert(position, confidence, method)
                        self.last_alert_position = position
                    else:
                        logger.debug(f"Position {position} still detected, but already alerted")
                else:
                    logger.info(
                        f"Unsafe position detected ({position}) but confidence too low "
                        f"({confidence:.0%} < {ALERT_REQUIRE_CONFIDENCE:.0%}). Not alerting."
                    )
            else:
                # Safe position - reset alert tracking
                if self.last_alert_position is not None:
                    logger.info(f"Baby returned to safe position: {position}")
                    self.last_alert_position = None
            
            # Retry any queued alerts
            self.alert_system.retry_queued_alerts()
            
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}", exc_info=True)
            # Continue running despite errors
    
    def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down Baby Monitor...")
        self.running = False
        self.camera.release()
        logger.info("Baby Monitor stopped")


def main():
    """Entry point"""
    monitor = BabyMonitor()
    monitor.run()


if __name__ == '__main__':
    main()
