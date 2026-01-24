"""
Main program for Baby Monitor
Continuous monitoring loop with error handling
"""
import logging
import time
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
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
from safety_evaluator import SafetyEvaluator

# Configure logging with rotation to prevent unbounded log file growth
# 10MB max file size, keep 5 backup files (total ~50MB max)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5),
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
        self.safety_evaluator = SafetyEvaluator(self.position_detector)
        self.running = False
        self.frame_count = 0
        self.last_position = None
        self.last_alert_position = None
        self.last_state = None
        
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
            
            # Evaluate safety state (fused over time)
            result = self.safety_evaluator.update(frame)

            # Log state transitions and key signal changes
            if result.state != self.last_state:
                logger.info(
                    f"Safety state: {result.state} (p_unsafe={result.p_unsafe:.2f}, "
                    f"obs={result.observability:.2f}, reason={result.reason})"
                )
                self.last_state = result.state

            if result.position != self.last_position:
                logger.info(
                    f"Position detected: {result.position} "
                    f"(confidence: {result.confidence:.0%}, method: {result.method}, "
                    f"obs={result.observability:.2f}, p_unsafe={result.p_unsafe:.2f})"
                )
                self.last_position = result.position

            status_text = (
                f"State: {result.state}\n"
                f"Position: {result.position}\n"
                f"Confidence: {result.confidence:.0%}\n"
                f"Method: {result.method}\n"
                f"Observability: {result.observability:.0%}\n"
                f"P(unsafe): {result.p_unsafe:.0%}\n"
                f"Reason: {result.reason}"
            )

            # Process caregiver inbound commands (ACK/STATUS) on a polling interval
            self.alert_system.process_inbound_commands(status_text=status_text)

            # Alert logic based on fused state (rate limited + suppressible)
            if result.state == "unsafe_confirmed" and result.position in ALERT_POSITIONS:
                sent = self.alert_system.send_alert(result.position, result.confidence, result.method)
                if sent:
                    logger.warning(
                        f"ALERT: Unsafe sleep suspected ({result.position}) "
                        f"(p_unsafe={result.p_unsafe:.2f}, obs={result.observability:.2f})"
                    )
                    self.last_alert_position = result.position

            elif result.state == "degraded":
                # Can't reliably confirm safe sleep; alert separately.
                self.alert_system.send_degraded_alert(
                    reason=result.reason,
                    observability=result.observability,
                )
            
            # Retry any queued alerts
            self.alert_system.retry_queued_alerts()
            
            # Explicitly delete frame to free memory immediately
            del frame
            
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
