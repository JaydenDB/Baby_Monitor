"""
Discord webhook alert system for Baby Monitor
Handles rate limiting and error recovery
"""
import logging
import time
import requests
from datetime import datetime
from config import (
    DISCORD_WEBHOOK_URL,
    DISCORD_USERNAME,
    ALERT_RATE_LIMIT_MINUTES,
    ACK_SILENCE_MINUTES,
    POSITION_SIDE,
    POSITION_STOMACH
)

logger = logging.getLogger(__name__)


class AlertSystem:
    """Handles Discord webhook alerts with rate limiting and error handling"""
    
    def __init__(self):
        self.webhook_url = DISCORD_WEBHOOK_URL or ""
        self.username = DISCORD_USERNAME or "Baby Monitor"
        self.last_alert_time = {}
        self.alert_queue = []
        self.rate_limit_seconds = ALERT_RATE_LIMIT_MINUTES * 60
        self.max_queue_size = 10  # Maximum queued alerts to prevent unbounded memory growth

        # Caregiver acknowledgement / suppression window
        self.suppress_until = 0.0
        self.ack_silence_seconds = float(ACK_SILENCE_MINUTES * 60)
        
        # Check if webhook URL is configured
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured. Alerts will not work.")
        else:
            logger.info("Discord webhook alert system initialized")

    def _create_embed(self, title, description, color, fields=None, timestamp=None):
        """
        Create a Discord embed dictionary.
        
        Args:
            title: Embed title
            description: Embed description
            color: Integer color code (0xRRGGBB format)
            fields: List of field dicts with 'name' and 'value' keys
            timestamp: ISO timestamp string or None for current time
        """
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": (timestamp or datetime.utcnow().isoformat()) + "Z",
            "footer": {
                "text": "Baby Monitor System"
            }
        }
        
        if fields:
            embed["fields"] = fields
        
        return embed

    def _send_discord_webhook(self, embeds):
        """
        Send message to Discord webhook.
        Raises requests.RequestException on HTTP errors.
        """
        if not self.webhook_url:
            raise requests.RequestException("Discord webhook URL not configured")

        payload = {
            "username": self.username,
            "embeds": embeds if isinstance(embeds, list) else [embeds]
        }

        response = requests.post(
            self.webhook_url,
            json=payload,
            timeout=10
        )
        
        # Discord returns 204 No Content on success, 429 on rate limit, 404 on invalid webhook
        if response.status_code == 204:
            return True
        elif response.status_code == 429:
            # Rate limited - extract retry_after from response if available
            try:
                data = response.json()
                retry_after = data.get("retry_after", 60)
                logger.warning(f"Discord rate limited. Retry after {retry_after} seconds")
            except:
                pass
            raise requests.RequestException(f"Discord rate limit: HTTP {response.status_code}")
        elif response.status_code == 404:
            raise requests.RequestException(f"Discord webhook not found (404). Check webhook URL.")
        else:
            response.raise_for_status()
            return True

    def _is_suppressed(self):
        return time.time() < float(self.suppress_until or 0.0)

    def suppress_alerts(self, seconds=None):
        """Suppress alerts for a given duration (seconds)."""
        seconds = float(seconds) if seconds is not None else float(self.ack_silence_seconds)
        self.suppress_until = time.time() + max(0.0, seconds)
        logger.info(f"Alerts suppressed for {seconds:.0f}s")
    
    def send_alert(self, position, confidence, method_used):
        """
        Send Discord alert for unsafe position
        Returns: True if sent successfully, False otherwise
        """
        if self._is_suppressed():
            logger.info("Alerts are currently suppressed")
            return False

        if position not in [POSITION_SIDE, POSITION_STOMACH]:
            return False
        
        # Check rate limiting
        if not self._can_send_alert(position):
            logger.info(f"Alert rate limited for position: {position}")
            return False
        
        position_text = "side" if position == POSITION_SIDE else "stomach"
        
        embed = self._create_embed(
            title="⚠️ Baby Monitor Alert",
            description=f"Baby has rolled onto their {position_text}.",
            color=0xFF0000,  # Red
            fields=[
                {"name": "Position", "value": position_text, "inline": True},
                {"name": "Confidence", "value": f"{confidence:.0%}", "inline": True},
                {"name": "Detection Method", "value": method_used, "inline": True},
                {"name": "Time", "value": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "inline": False}
            ]
        )
        
        try:
            self._send_discord_webhook(embed)
            
            # Update last alert time
            self.last_alert_time[position] = time.time()
            
            logger.info(f"Alert sent successfully for {position_text} position")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Discord webhook error: {e}")
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
        Send a Discord alert when monitoring is degraded (can't confirm safe sleep).
        Uses its own rate limit key to avoid spamming.
        """
        if self._is_suppressed():
            logger.info("Degraded alert suppressed")
            return False

        key = "degraded"
        if not self._can_send_alert(key):
            logger.info("Degraded alert rate limited")
            return False

        obs_text = f"{observability:.0%}" if isinstance(observability, (int, float)) else "n/a"
        
        embed = self._create_embed(
            title="⚠️ Baby Monitor Warning",
            description="Monitor cannot reliably confirm safe sleep right now.",
            color=0xFF8800,  # Orange
            fields=[
                {"name": "Observability", "value": obs_text, "inline": True},
                {"name": "Reason", "value": reason, "inline": False},
                {"name": "Time", "value": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "inline": False}
            ]
        )
        
        try:
            self._send_discord_webhook(embed)
            self.last_alert_time[key] = time.time()
            logger.info("Degraded monitoring alert sent successfully")
            return True
        except requests.RequestException as e:
            logger.error(f"Discord webhook error sending degraded alert: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending degraded alert: {e}")
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
        if not self.alert_queue or not self.webhook_url:
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
                    position_text = "side" if alert['position'] == POSITION_SIDE else "stomach"
                    embed = self._create_embed(
                        title="⚠️ Baby Monitor Alert (Retry)",
                        description=f"Baby has rolled onto their {position_text}.",
                        color=0xFF0000,  # Red
                        fields=[
                            {"name": "Position", "value": position_text, "inline": True},
                            {"name": "Confidence", "value": f"{alert['confidence']:.0%}", "inline": True},
                            {"name": "Detection Method", "value": alert['method_used'], "inline": True},
                            {"name": "Time", "value": datetime.fromtimestamp(alert['timestamp']).strftime('%Y-%m-%d %H:%M:%S'), "inline": False}
                        ],
                        timestamp=datetime.fromtimestamp(alert['timestamp']).isoformat() + "Z"
                    )
                    self._send_discord_webhook(embed)
                    self.last_alert_time[alert['position']] = time.time()
                    logger.info("Successfully sent queued alert")
                except requests.RequestException as e:
                    logger.error(f"Discord webhook error while retrying queued alert: {e}")
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
        Test Discord webhook connection
        Returns: True if connection works, False otherwise
        """
        if not self.webhook_url:
            return False
        
        try:
            # Send a test message
            embed = self._create_embed(
                title="Baby Monitor Test",
                description="Connection test successful.",
                color=0x00FF00  # Green
            )
            self._send_discord_webhook(embed)
            logger.info("Discord webhook connection test successful")
            return True
        except Exception as e:
            logger.error(f"Discord webhook connection test failed: {e}")
            return False
