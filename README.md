# Baby Monitor for Raspberry Pi

A production-ready Python-based baby monitor that uses webcam input, hybrid detection methods (MediaPipe pose + motion detection), and SMS alerts when the baby rolls onto their side or stomach.

## Features

- **Hybrid Detection**: MediaPipe Pose (primary) + Motion Detection (fallback)
- **Works with Babies**: Motion detection handles cases where MediaPipe struggles
- **Robust Error Handling**: Never crashes, handles all error scenarios gracefully
- **Confidence-Based Alerts**: Only alerts when detection is confident (prevents false alarms)
- **SMS Notifications**: Twilio integration for instant alerts
- **Production Ready**: Comprehensive logging, error recovery, and monitoring

## Important Note: MediaPipe and Babies

MediaPipe Pose was primarily trained on adult bodies and may have reduced accuracy with infants. This program uses a hybrid approach:

- **MediaPipe Pose**: Primary detection method (works when confidence is high)
- **Motion Detection**: Automatic fallback when MediaPipe confidence is low
- **Confidence Scoring**: Only sends alerts when detection is confident

The system is designed to work reliably even when MediaPipe struggles with baby detection.

## Hardware Requirements

- Raspberry Pi (3B+ or newer recommended)
- USB webcam
- MicroSD card with Raspberry Pi OS
- Internet connection for SMS alerts

## Software Requirements

- Python 3.8 or higher
- Raspberry Pi OS (or compatible Linux distribution)

## Installation

### On Your Development Machine

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### On Raspberry Pi

#### Option 1: Automated Setup (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/JaydenDB/Baby_Monitor.git
   cd Baby_Monitor
   ```

2. Run the setup script:
   ```bash
   chmod +x setup_pi.sh
   ./setup_pi.sh
   ```

#### Option 2: Manual Setup

1. Install system dependencies:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip libopencv-dev python3-opencv
   ```

2. Install Python packages:
   ```bash
   pip3 install -r requirements.txt
   ```

## Configuration

### 1. Twilio Setup

1. Create a Twilio account at https://www.twilio.com/
2. Get your Account SID and Auth Token from the Twilio Console
3. Get a Twilio phone number (or use trial number for testing)

### 2. Environment Variables

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` file with your credentials:
   ```bash
   nano .env
   ```

3. Add your Twilio credentials:
   ```
   TWILIO_ACCOUNT_SID=your_account_sid
   TWILIO_AUTH_TOKEN=your_auth_token
   TWILIO_PHONE_NUMBER=+1234567890
   PARENT_PHONE_NUMBER=+1234567890
   ```

### 3. Camera Configuration

Test camera access:
```bash
python3 -c "import cv2; cap = cv2.VideoCapture(0); print('Camera OK' if cap.isOpened() else 'Camera Error')"
```

If camera is not accessible:
- Check camera is connected: `lsusb`
- Check permissions: `groups` (user should be in `video` group)
- Add user to video group: `sudo usermod -a -G video $USER` (then logout/login)

### 4. Adjust Settings (Optional)

Edit `config.py` or `.env` to adjust:
- `CHECK_INTERVAL`: Time between position checks (default: 2.0 seconds)
- `ALERT_CONFIDENCE`: Minimum confidence to send alert (default: 0.5)
- `ALERT_RATE_LIMIT`: Minutes between alerts (default: 5)
- Camera resolution and FPS

## Usage

### Run Manually

```bash
python3 main.py
```

### Run as Background Service

1. Create systemd service file:
   ```bash
   sudo nano /etc/systemd/system/baby-monitor.service
   ```

2. Add the following (adjust paths as needed):
   ```ini
   [Unit]
   Description=Baby Monitor Service
   After=network.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/baby-monitor
   ExecStart=/usr/bin/python3 /home/pi/baby-monitor/main.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable baby-monitor.service
   sudo systemctl start baby-monitor.service
   ```

4. Check status:
   ```bash
   sudo systemctl status baby-monitor.service
   ```

5. View logs:
   ```bash
   journalctl -u baby-monitor.service -f
   ```

## How It Works

1. **Camera Capture**: Continuously captures frames from webcam
2. **Position Detection**: 
   - Tries MediaPipe Pose detection first
   - Falls back to motion detection if MediaPipe confidence is low
   - Combines results when both methods are available
3. **Alert System**: 
   - Sends SMS when baby is on side or stomach
   - Rate limited to prevent spam
   - Only alerts when confidence threshold is met

## Detection Methods

### MediaPipe Pose (Primary)
- Uses Google's pre-trained pose estimation
- Detects 33 body keypoints
- Works well when baby is clearly visible
- May have reduced accuracy with very small babies

### Motion Detection (Fallback)
- Uses background subtraction and contour analysis
- Works reliably regardless of body size
- Detects position changes through movement patterns
- Activates automatically when MediaPipe confidence is low

## Troubleshooting

### Camera Not Working
- Check camera connection: `lsusb`
- Test with: `python3 -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened())"`
- Check permissions: `groups` (should include `video`)
- Try different camera index in config (0, 1, 2, etc.)

### SMS Not Sending
- Verify Twilio credentials in `.env` file
- Test Twilio connection: Check logs for errors
- Verify phone numbers are in E.164 format (+1234567890)
- Check Twilio account balance

### False Alarms
- Increase `ALERT_CONFIDENCE` threshold in config
- Increase `ALERT_RATE_LIMIT` to reduce frequency
- Check logs to see which detection method is being used
- Adjust `MOTION_THRESHOLD` if motion detection is too sensitive

### Program Crashes
- Check logs in `baby_monitor.log`
- Verify all dependencies are installed
- Ensure camera is connected and accessible
- Check Python version (3.8+ required)

## Logs

Logs are written to `baby_monitor.log` and optionally to console.

Log levels:
- `INFO`: Normal operation, position changes
- `WARNING`: Alerts sent, low confidence detections
- `ERROR`: Camera errors, SMS failures, exceptions

## Updating

To update the program:

```bash
cd Baby_Monitor
git pull
pip3 install -r requirements.txt
sudo systemctl restart baby-monitor.service
```

## Safety Disclaimer

This is a monitoring tool and should not be the sole method of baby supervision. Always follow safe sleep guidelines and never leave a baby unattended. This program is provided as-is without warranty.

## License

This project is provided as-is for personal use.

## Support

For issues or questions:
1. Check the logs: `tail -f baby_monitor.log`
2. Review this README
3. Check Twilio and camera connections
4. Verify all configuration settings

## GitHub Deployment

This program is designed to be deployed via GitHub:

1. Push code to GitHub repository
2. Clone on Raspberry Pi: `git clone https://github.com/JaydenDB/Baby_Monitor.git`
3. Follow setup instructions above
4. Update with: `git pull` when needed
