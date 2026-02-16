#!/bin/bash
# start_strategy.sh - Start trading strategy in background

# Detect OS
OS="$(uname)"
if [ "$OS" = "Darwin" ]; then
    # macOS
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
else
    # Linux
    SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
fi

cd "$SCRIPT_DIR"

# Check if already running
if [ -f "strategy.pid" ]; then
    PID=$(cat strategy.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "Service is already running (PID: $PID)"
        exit 0
    else
        echo "Found stale PID file. Removing..."
        rm strategy.pid
    fi
fi

# Activate venv
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Error: Virtual environment not found."
    exit 1
fi

# Create logs directory
mkdir -p logs

# Generate log filename
LOG_FILE="logs/strategy_$(date +%Y%m%d_%H%M%S).log"

# Update symlink (cross-platform compatible)
rm -f strategy.log
ln -s "$LOG_FILE" strategy.log

# Run in background
echo "Starting strategy..."
echo "Logging to: $LOG_FILE"
nohup python main.py > "$LOG_FILE" 2>&1 &

# Save PID
PID=$!
echo $PID > strategy.pid
echo "Service started with PID: $PID"
