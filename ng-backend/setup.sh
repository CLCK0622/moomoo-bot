#!/bin/bash

# setup.sh - Deploy AI Monitor on Ubuntu 24
# Run as root or with sudo

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./setup.sh)"
  exit 1
fi

PROJECT_DIR=$(pwd)
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_FILE="ai-monitor.service"
TIMER_FILE="ai-monitor.timer"

echo "🚀 Starting deployment in $PROJECT_DIR..."

# 1. Install System Dependencies
echo "📦 Installing system dependencies..."
apt update
apt install -y python3 python3-venv python3-pip

# 2. Setup Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo "🐍 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "🐍 Virtual environment exists, skipping creation."
fi

# 3. Install Python Requirements
echo "📥 Installing python requirements..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r requirements.txt

# 4. Create/Update Systemd Service Files with Correct Paths
echo "⚙️ Configuring systemd service..."

# Create Service File content dynamically
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Moomoo Bot AI Monitor Analysis Service
After=network.target

[Service]
Type=oneshot
User=$SUDO_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python ai-monitor/run_analysis.py
StandardOutput=append:$PROJECT_DIR/ai-monitor.log
StandardError=append:$PROJECT_DIR/ai-monitor.err
EnvironmentFile=$PROJECT_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

# Create Timer File content
cat > "$TIMER_FILE" <<EOF
[Unit]
Description=Run AI Monitor Analysis Daily at 07:00 and 18:00 US/Eastern

[Timer]
# Schedule: 07:00 and 18:00 (Local Time of VM)
OnCalendar=*-*-* 07:00:00
OnCalendar=*-*-* 18:00:00
Persistent=true
Unit=ai-monitor.service

[Install]
WantedBy=timers.target
EOF

# 5. Install Systemd Files
echo "🔧 Installing systemd units..."
cp "$SERVICE_FILE" /etc/systemd/system/
cp "$TIMER_FILE" /etc/systemd/system/

systemctl daemon-reload
systemctl enable "$TIMER_FILE"
systemctl start "$TIMER_FILE"

echo "✅ Deployment Complete!"
echo "   - Service: $SERVICE_FILE"
echo "   - Timer:   $TIMER_FILE"
echo "   - Logs:    $PROJECT_DIR/ai-monitor.log"
echo "   - Next run: systemctl list-timers ai-monitor.timer"
echo ""
echo "⚠️  IMPORTANT: Ensure your .env file is populated with OPENAI_API_KEY!"
echo "⚠️  IMPORTANT: Ensure FutuOpenD is running and accessible if market data is required."
