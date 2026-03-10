#!/bin/bash
# stop_strategy.sh - Stop trading strategy gracefully

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

if [ -f "strategy.pid" ]; then
    PID=$(cat strategy.pid)
    
    # Check if process is running
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping service (PID: $PID)..."
        kill "$PID"  # Send SIGTERM
        
        # Wait for up to 5 seconds for it to exit
        for i in {1..5}; do
            if ps -p "$PID" > /dev/null 2>&1; then
                sleep 1
            else
                break
            fi
        done
        
        # Force kill if still running
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Process did not stop gracefully. Forcing kill (-9)..."
            kill -9 "$PID"
        fi
        
        echo "Service stopped."
    else
        echo "Service is not running (PID $PID not found)."
    fi
    
    # Clean up PID file
    rm -f strategy.pid
else
    echo "Service is not running (strategy.pid not found)."
fi
