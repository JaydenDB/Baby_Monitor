#!/bin/bash
# Setup script for Raspberry Pi
# Installs dependencies and configures the Baby Monitor

set -e  # Exit on error

echo "=========================================="
echo "Baby Monitor - Raspberry Pi Setup"
echo "=========================================="

# Check if running on Raspberry Pi (optional check)
if [ ! -f /proc/device-tree/model ]; then
    echo "Warning: This may not be a Raspberry Pi"
fi

# Update package list
echo "Updating package list..."
sudo apt-get update

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    libopencv-dev \
    python3-opencv \
    libcamera-dev \
    v4l-utils

# Create virtual environment (optional but recommended)
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install Python dependencies
echo "Installing Python packages..."
pip install -r requirements.txt

# Check camera access
echo "Checking camera access..."
if command -v v4l2-ctl &> /dev/null; then
    echo "Available cameras:"
    v4l2-ctl --list-devices
else
    echo "v4l2-ctl not found. Install with: sudo apt-get install v4l-utils"
fi

# Test camera with Python
echo "Testing camera with Python..."
python3 -c "
import cv2
cap = cv2.VideoCapture(0)
if cap.isOpened():
    print('✓ Camera is accessible')
    cap.release()
else:
    print('✗ Camera is NOT accessible. Check camera connection and permissions.')
"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit .env file and add your Twilio credentials!"
    echo "   nano .env"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env file with your Twilio credentials:"
echo "   nano .env"
echo ""
echo "2. Test the program:"
echo "   python3 main.py"
echo ""
echo "3. (Optional) Set up as systemd service for auto-start:"
echo "   See README.md for instructions"
echo ""
