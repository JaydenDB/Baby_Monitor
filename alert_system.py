"""
SMS alert system using Twilio
Handles rate limiting and error recovery
"""
import logging
import time
from datetime import datetime
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    PARENT_PHONE_NUMBER,
    ALERT_RATE_LIMIT_MINUTES,
    POSITION_SIDE,
    POSITION_STOMACH
)

logger = logging.getLogger(__name__)


class AlertSystem:
    """Handles SMS alerts with rate limiting and error handling"""
    
    def __init__(self):
        self.client = None
        self.last_alert_time = {}
        self.alert_queue = []
        self.rate_limit_seconds = ALERT_RATE_LIMIT_MINUTES * 60
        
        # Initialize Twilio client if credentials are available
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            try:
                self.client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                logger.info("Twilio client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
                self.client = None
        else:
            logger.warning("Twilio credentials not configured. SMS alerts will not work.")
    
    def send_alert(self, position, confidence, method_used):
        """
        Send SMS alert for unsafe position
        Returns: True if sent successfully, False otherwise
        """
        if position not in [POSITION_SIDE, POSITION_STOMACH]:
            return False
        
        # Check rate limiting
        if not self._can_send_alert(position):
            logger.info(f"Alert rate limited for position: {position}")
            return False
        
        if not self.client:
            logger.warning("Cannot send alert: Twilio client not initialized")
            return False
        
        if not PARENT_PHONE_NUMBER:
            logger.warning("Cannot send alert: Parent phone number not configured")
            return False
        
        # Format alert message
        position_text = "side" if position == POSITION_SIDE else "stomach"
        message = (
            f"⚠️ Baby Monitor Alert\n\n"
            f"Baby has rolled onto their {position_text}.\n"
            f"Detection confidence: {confidence:.0%}\n"
            f"Method: {method_used}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        try:
            # Send SMS
            self.client.messages.create(
                body=message,
                from_=TWILIO_PHONE_NUMBER,
                to=PARENT_PHONE_NUMBER
            )
            
            # Update last alert time
            self.last_alert_time[position] = time.time()
            
            logger.info(f"Alert sent successfully for {position_text} position")
            return True
            
        except TwilioException as e:
            logger.error(f"Twilio API error: {e}")
            # Queue alert for retry
            self.alert_queue.append({
                'position': position,
                'confidence': confidence,
                'method_used': method_used,
                'timestamp': time.time()
            })
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error sending alert: {e}")
            return False
    
    def _can_send_alert(self, position):
        """
        Check if alert can be sent (rate limiting)
        Returns: True if can send, False if rate limited
        """
        if position not in self.last_alert_time:
            return True
        
        time_since_last = time.time() - self.last_alert_time[position]
        return time_since_last >= self.rate_limit_seconds
    
    def retry_queued_alerts(self):
        """Retry any queued alerts that failed to send"""
        if not self.alert_queue or not self.client:
            return
        
        retry_queue = []
        for alert in self.alert_queue:
            # Only retry recent alerts (within last hour)
            if time.time() - alert['timestamp'] > 3600:
                continue
            
            if self._can_send_alert(alert['position']):
                if self.send_alert(alert['position'], alert['confidence'], alert['method_used']):
                    logger.info("Successfully sent queued alert")
                else:
                    retry_queue.append(alert)
            else:
                retry_queue.append(alert)
        
        self.alert_queue = retry_queue
    
    def test_connection(self):
        """
        Test Twilio connection
        Returns: True if connection works, False otherwise
        """
        if not self.client:
            return False
        
        try:
            # Try to fetch account info
            account = self.client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
            logger.info(f"Twilio connection test successful. Account: {account.friendly_name}")
            return True
        except Exception as e:
            logger.error(f"Twilio connection test failed: {e}")
            return False
