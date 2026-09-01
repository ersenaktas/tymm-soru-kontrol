#!/bin/bash
set -e

# Start Xvfb virtual framebuffer on display :99
Xvfb :99 -screen 0 1280x1024x24 -ac +extension GLX +render -noreset > /dev/null 2>&1 &
XVFB_PID=$!

export DISPLAY=:99

# Wait a brief moment for Xvfb to initialize
sleep 1

# Start the web server
exec python -m pilot.web
