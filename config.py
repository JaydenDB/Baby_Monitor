"""
Configuration settings for Baby Monitor
Loads sensitive credentials from .env file
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Camera Settings
CAMERA_INDEX = int(os.getenv('CAMERA_INDEX', '0'))  # Default to first camera
CAMERA_WIDTH = int(os.getenv('CAMERA_WIDTH', '640'))
CAMERA_HEIGHT = int(os.getenv('CAMERA_HEIGHT', '480'))
CAMERA_FPS = int(os.getenv('CAMERA_FPS', '30'))

# Detection Settings
CHECK_INTERVAL = float(os.getenv('CHECK_INTERVAL', '2.0'))  # Seconds between checks
MEDIAPIPE_CONFIDENCE_THRESHOLD_HIGH = float(os.getenv('MEDIAPIPE_CONFIDENCE_HIGH', '0.6'))
MEDIAPIPE_CONFIDENCE_THRESHOLD_MEDIUM = float(os.getenv('MEDIAPIPE_CONFIDENCE_MEDIUM', '0.3'))
MOTION_DETECTION_THRESHOLD = float(os.getenv('MOTION_THRESHOLD', '5000.0'))  # Pixels changed
CONTOUR_MIN_AREA = int(os.getenv('CONTOUR_MIN_AREA', '1000'))  # Minimum contour area

# Face Detection Settings
ENABLE_FACE_DETECTION = os.getenv('ENABLE_FACE_DETECTION', 'True').lower() == 'true'
FACE_DETECTION_MIN_CONFIDENCE = float(os.getenv('FACE_DETECTION_MIN_CONFIDENCE', '0.5'))

# Alert Settings
ALERT_RATE_LIMIT_MINUTES = int(os.getenv('ALERT_RATE_LIMIT', '5'))  # Max 1 alert per N minutes
ALERT_REQUIRE_CONFIDENCE = float(os.getenv('ALERT_CONFIDENCE', '0.5'))  # Minimum confidence to alert

# Safety Evaluation (fusion / temporal logic)
# The evaluator maintains a sliding time window of recent samples to stabilize decisions.
SAFETY_WINDOW_SECONDS = float(os.getenv('SAFETY_WINDOW_SECONDS', '30'))
UNSAFE_SUSPECT_SECONDS = float(os.getenv('UNSAFE_SUSPECT_SECONDS', '6'))
UNSAFE_CONFIRM_SECONDS = float(os.getenv('UNSAFE_CONFIRM_SECONDS', '12'))
UNSAFE_SUSPECT_P_THRESHOLD = float(os.getenv('UNSAFE_SUSPECT_P_THRESHOLD', '0.55'))
UNSAFE_CONFIRM_P_THRESHOLD = float(os.getenv('UNSAFE_CONFIRM_P_THRESHOLD', '0.65'))  # Lowered from 0.70 to reduce Type II errors

# Conservative Default: when uncertain, err on side of caution
CONSERVATIVE_DEFAULT_ENABLED = os.getenv('CONSERVATIVE_DEFAULT_ENABLED', 'True').lower() == 'true'
UNKNOWN_POSITION_ALARM_SECONDS = float(os.getenv('UNKNOWN_POSITION_ALARM_SECONDS', '30'))  # Escalate if unknown for this long

# Observability: how well the monitor can see/track the baby (0..1)
OBSERVABILITY_THRESHOLD = float(os.getenv('OBSERVABILITY_THRESHOLD', '0.30'))
OBSERVABILITY_DEGRADED_THRESHOLD = float(os.getenv('OBSERVABILITY_DEGRADED_THRESHOLD', '0.20'))
OBSERVABILITY_DEGRADED_SECONDS = float(os.getenv('OBSERVABILITY_DEGRADED_SECONDS', '60'))

# Inbound SMS commands (polling) for caregiver acknowledgement
ENABLE_INBOUND_COMMANDS = os.getenv('ENABLE_INBOUND_COMMANDS', 'True').lower() == 'true'
TWILIO_INBOUND_POLL_SECONDS = float(os.getenv('TWILIO_INBOUND_POLL_SECONDS', '10'))
ACK_SILENCE_MINUTES = int(os.getenv('ACK_SILENCE_MINUTES', '10'))

# Twilio SMS Settings
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '')
PARENT_PHONE_NUMBER = os.getenv('PARENT_PHONE_NUMBER', '')

# Logging Settings
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'baby_monitor.log')
LOG_TO_CONSOLE = os.getenv('LOG_TO_CONSOLE', 'True').lower() == 'true'

# Position Classifications
POSITION_BACK = 'back'
POSITION_SIDE = 'side'
POSITION_STOMACH = 'stomach'
POSITION_UNKNOWN = 'unknown'

# Alert Positions (positions that trigger alerts)
ALERT_POSITIONS = [POSITION_SIDE, POSITION_STOMACH]
