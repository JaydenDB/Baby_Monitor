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

# Alert Settings
ALERT_RATE_LIMIT_MINUTES = int(os.getenv('ALERT_RATE_LIMIT', '5'))  # Max 1 alert per N minutes
ALERT_REQUIRE_CONFIDENCE = float(os.getenv('ALERT_CONFIDENCE', '0.5'))  # Minimum confidence to alert

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
