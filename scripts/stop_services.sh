#!/bin/bash
# Stop all MoltNet services
#
# Usage:
#   ./scripts/stop_services.sh        # Stop all services gracefully
#   ./scripts/stop_services.sh --kill # Force kill all services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_DIR/.pids"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FORCE_KILL=false
if [ "$1" == "--kill" ]; then
    FORCE_KILL=true
fi

stop_service() {
    local name=$1
    local pid_file="$PID_DIR/${name}.pid"

    if [ ! -f "$pid_file" ]; then
        echo -e "${YELLOW}$name: no PID file found${NC}"
        return 0
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 "$pid" 2>/dev/null; then
        echo -e "${YELLOW}$name: not running (stale PID $pid)${NC}"
        rm -f "$pid_file"
        return 0
    fi

    echo -n "Stopping $name (PID: $pid)... "

    if [ "$FORCE_KILL" = true ]; then
        kill -9 "$pid" 2>/dev/null || true
    else
        kill "$pid" 2>/dev/null || true
        # Wait for graceful shutdown
        for i in {1..10}; do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.5
        done
        # Force kill if still running
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi

    rm -f "$pid_file"
    echo -e "${GREEN}stopped${NC}"
}

# Also kill any orphaned uvicorn processes on our ports
kill_by_port() {
    local port=$1
    local name=$2
    local pid=$(lsof -t -i :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo -n "Killing $name on port $port (PID: $pid)... "
        kill -9 $pid 2>/dev/null || true
        echo -e "${GREEN}done${NC}"
    fi
}

echo "========================================"
echo "Stopping MoltNet Services"
echo "========================================"
echo

# Stop by PID file
stop_service "observatory"
stop_service "moltbook"
stop_service "moltgit"
stop_service "gateway"

# Also clean up any orphaned processes on our ports
echo
echo "Checking for orphaned processes..."
kill_by_port 9100 "observatory"
kill_by_port 9101 "moltbook"
kill_by_port 9103 "moltgit"
kill_by_port 8080 "gateway"

echo
echo -e "${GREEN}All services stopped.${NC}"
