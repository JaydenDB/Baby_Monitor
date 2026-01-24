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
    ENABLE_INBOUND_COMMANDS,
    TWILIO_INBOUND_POLL_SECONDS,
    ACK_SILENCE_MINUTES,
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
        self.max_queue_size = 10  # Maximum queued alerts to prevent unbounded memory growth

        # Caregiver acknowledgement / suppression window
        self.suppress_until = 0.0
        self.ack_silence_seconds = float(ACK_SILENCE_MINUTES * 60)

        # Inbound command polling
        self.enable_inbound_commands = bool(ENABLE_INBOUND_COMMANDS)
        self.inbound_poll_seconds = float(TWILIO_INBOUND_POLL_SECONDS)
        self._last_inbound_poll = 0.0
        self._seen_inbound_sids = []  # keep small to prevent unbounded memory growth
        self._seen_inbound_sids_max = 50
        self._last_inbound_date = None  # datetime in UTC (Twilio uses aware datetime)
        
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

    def _format_message(self, position, confidence, method_used, timestamp=None):
        """Create the SMS message body for an unsafe position alert."""
        # Keep timestamp stable for queued retries if provided
        ts = timestamp or datetime.now()
        position_text = "side" if position == POSITION_SIDE else "stomach"
        return (
            f"⚠️ Baby Monitor Alert\n\n"
            f"Baby has rolled onto their {position_text}.\n"
            f"Detection confidence: {confidence:.0%}\n"
            f"Method: {method_used}\n"
            f"Time: {ts.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _format_degraded_message(self, reason, observability=None, timestamp=None):
        ts = timestamp or datetime.now()
        obs_text = f"{observability:.0%}" if isinstance(observability, (int, float)) else "n/a"
        return (
            "⚠️ Baby Monitor Warning\n\n"
            "Monitor cannot reliably confirm safe sleep right now.\n"
            f"Observability: {obs_text}\n"
            f"Reason: {reason}\n"
            f"Time: {ts.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "Reply STATUS for the current state, or ACK to silence alerts temporarily."
        )

    def _send_sms(self, message):
        """Send an SMS via Twilio. Raises TwilioException on Twilio failures."""
        if not self.client:
            raise TwilioException("Twilio client not initialized")
        if not TWILIO_PHONE_NUMBER:
            raise TwilioException("Twilio phone number not configured")
        if not PARENT_PHONE_NUMBER:
            raise TwilioException("Parent phone number not configured")

        self.client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=PARENT_PHONE_NUMBER
        )

    def _is_suppressed(self):
        return time.time() < float(self.suppress_until or 0.0)

    def suppress_alerts(self, seconds=None):
        """Suppress alerts for a given duration (seconds)."""
        seconds = float(seconds) if seconds is not None else float(self.ack_silence_seconds)
        self.suppress_until = time.time() + max(0.0, seconds)
        logger.info(f"Alerts suppressed for {seconds:.0f}s")
    
    def send_alert(self, position, confidence, method_used):
        """
        Send SMS alert for unsafe position
        Returns: True if sent successfully, False otherwise
        """
        if self._is_suppressed():
            logger.info("Alerts are currently suppressed by caregiver acknowledgement")
            return False

        if position not in [POSITION_SIDE, POSITION_STOMACH]:
            return False
        
        # Check rate limiting
        if not self._can_send_alert(position):
            logger.info(f"Alert rate limited for position: {position}")
            return False
        
        message = self._format_message(position, confidence, method_used)
        
        try:
            self._send_sms(message)
            
            # Update last alert time
            self.last_alert_time[position] = time.time()
            
            position_text = "side" if position == POSITION_SIDE else "stomach"
            logger.info(f"Alert sent successfully for {position_text} position")
            return True
            
        except TwilioException as e:
            logger.error(f"Twilio API error: {e}")
            # Queue alert for retry, but limit queue size to prevent memory issues
            if len(self.alert_queue) >= self.max_queue_size:
                # Remove oldest alert to make room
                self.alert_queue.pop(0)
                logger.warning(f"Alert queue full ({self.max_queue_size}), removing oldest alert")
            self.alert_queue.append({
                'position': position,
                'confidence': confidence,
                'method_used': method_used,
                # Store creation timestamp for expiry window
                'timestamp': time.time()
            })
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error sending alert: {e}")
            return False

    def send_degraded_alert(self, reason, observability=None):
        """
        Send an SMS alert when monitoring is degraded (can't confirm safe sleep).
        Uses its own rate limit key to avoid spamming.
        """
        if self._is_suppressed():
            logger.info("Degraded alert suppressed by caregiver acknowledgement")
            return False

        key = "degraded"
        if not self._can_send_alert(key):
            logger.info("Degraded alert rate limited")
            return False

        message = self._format_degraded_message(reason=reason, observability=observability)
        try:
            self._send_sms(message)
            self.last_alert_time[key] = time.time()
            logger.info("Degraded monitoring alert sent successfully")
            return True
        except TwilioException as e:
            logger.error(f"Twilio API error sending degraded alert: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending degraded alert: {e}")
            return False

    def send_status_message(self, status_text):
        """Send an informational status message to the parent phone number."""
        if not self.client:
            logger.warning("Cannot send status: Twilio client not initialized")
            return False
        if not status_text:
            status_text = "Baby Monitor status unavailable."

        message = f"Baby Monitor Status:\n\n{status_text}"
        try:
            self._send_sms(message)
            return True
        except Exception as e:
            logger.error(f"Failed to send status message: {e}")
            return False

    def process_inbound_commands(self, status_text=None):
        """
        Poll Twilio for inbound SMS commands from the parent number.

        Supported:
          - ACK: suppress alerts for ACK_SILENCE_MINUTES
          - STATUS: respond with the current status_text (provided by caller)
          - HELP: basic usage
        """
        if not self.enable_inbound_commands:
            return
        if not self.client or not TWILIO_PHONE_NUMBER or not PARENT_PHONE_NUMBER:
            return

        now = time.time()
        if now - self._last_inbound_poll < self.inbound_poll_seconds:
            return
        self._last_inbound_poll = now

        try:
            # Fetch recent messages to our Twilio number from the parent.
            msgs = self.client.messages.list(
                to=TWILIO_PHONE_NUMBER,
                from_=PARENT_PHONE_NUMBER,
                limit=20,
            )
        except Exception as e:
            logger.error(f"Failed to poll inbound SMS: {e}")
            return

        # Process in chronological order.
        for msg in reversed(msgs):
            try:
                if getattr(msg, "direction", "") != "inbound":
                    continue

                sid = getattr(msg, "sid", None)
                if sid and sid in self._seen_inbound_sids:
                    continue

                date_sent = getattr(msg, "date_sent", None)
                if self._last_inbound_date is not None and date_sent is not None and date_sent <= self._last_inbound_date:
                    continue

                body = (getattr(msg, "body", "") or "").strip()
                cmd = body.upper()

                if cmd == "ACK":
                    self.suppress_alerts()
                    until = datetime.fromtimestamp(self.suppress_until).strftime("%Y-%m-%d %H:%M:%S")
                    self.send_status_message(
                        f"ACK received. Alerts silenced until {until}.\n\nReply STATUS for current state."
                    )

                elif cmd == "STATUS":
                    self.send_status_message(status_text or "Status unavailable.")

                elif cmd in ("HELP", "?"):
                    self.send_status_message("Commands: STATUS, ACK, HELP")

                else:
                    # Ignore unknown commands to avoid noisy loops.
                    continue

                # Mark processed
                if sid:
                    self._seen_inbound_sids.append(sid)
                    if len(self._seen_inbound_sids) > self._seen_inbound_sids_max:
                        self._seen_inbound_sids = self._seen_inbound_sids[-self._seen_inbound_sids_max :]

                if date_sent is not None:
                    self._last_inbound_date = date_sent

            except Exception as e:
                logger.error(f"Error processing inbound SMS command: {e}")
    
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
        
        # Work on a snapshot and rebuild the queue to avoid mutating
        # self.alert_queue while iterating (send_alert() may queue).
        pending = list(self.alert_queue)
        retry_queue = []

        for alert in pending:
            # Only retry recent alerts (within last hour)
            if time.time() - alert['timestamp'] > 3600:
                continue
            
            if not self._can_send_alert(alert['position']):
                retry_queue.append(alert)

            else:
                # Send directly without re-queueing inside send_alert()
                try:
                    message = self._format_message(
                        alert['position'],
                        alert['confidence'],
                        alert['method_used'],
                        # preserve original event time in message
                        timestamp=datetime.fromtimestamp(alert['timestamp'])
                    )
                    self._send_sms(message)
                    self.last_alert_time[alert['position']] = time.time()
                    logger.info("Successfully sent queued alert")
                except TwilioException as e:
                    logger.error(f"Twilio API error while retrying queued alert: {e}")
                    retry_queue.append(alert)
                except Exception as e:
                    logger.error(f"Unexpected error retrying queued alert: {e}")
                    retry_queue.append(alert)

        # Enforce queue size limit
        if len(retry_queue) > self.max_queue_size:
            # Keep only the most recent alerts
            retry_queue = retry_queue[-self.max_queue_size:]
            logger.warning(f"Alert queue exceeded limit, keeping only {self.max_queue_size} most recent alerts")
        
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
