#!/bin/bash
# Start all MoltNet services for a demo run
#
# Usage:
#   ./scripts/start_services.sh           # Start all services
#   ./scripts/start_services.sh --wait    # Start and wait for ready
#
# Services started:
#   - Observatory (port 9100) - Telemetry dashboard
#   - Moltbook (port 9101) - Knowledge sharing
#   - MoltGit (port 9103) - Code repository
#   - Task Shop (port 9104) - Benchmark marketplace

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_DIR/.pids"
LOG_DIR="$PROJECT_DIR/service_logs"

# Ports
OBSERVATORY_PORT=9100
MOLTBOOK_PORT=9101
MOLTGIT_PORT=9103
TASKSHOP_PORT=9104
GATEWAY_PORT=8080

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

mkdir -p "$PID_DIR"
mkdir -p "$LOG_DIR"

check_port() {
    local port=$1
    if lsof -i :$port >/dev/null 2>&1; then
        return 0  # Port in use
    else
        return 1  # Port free
    fi
}

wait_for_service() {
    local name=$1
    local port=$2
    local max_wait=30
    local waited=0

    while [ $waited -lt $max_wait ]; do
        if curl -s "http://localhost:$port/health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

start_service() {
    local name=$1
    local port=$2
    local module=$3

    if check_port $port; then
        echo -e "${YELLOW}$name already running on port $port${NC}"
        return 0
    fi

    echo -n "Starting $name on port $port... "

    cd "$PROJECT_DIR"
    nohup uv run uvicorn "$module:app" --host 0.0.0.0 --port "$port" \
        > "$LOG_DIR/${name}.log" 2>&1 &
    local pid=$!
    echo $pid > "$PID_DIR/${name}.pid"

    # Wait for service to be ready
    sleep 2
    if wait_for_service "$name" "$port"; then
        echo -e "${GREEN}OK${NC} (PID: $pid)"
        return 0
    else
        echo -e "${RED}FAILED${NC}"
        return 1
    fi
}

echo "========================================"
echo "Starting MoltNet Services"
echo "========================================"
echo

# Start services
start_service "observatory" $OBSERVATORY_PORT "observatory.main"
start_service "moltbook" $MOLTBOOK_PORT "moltbook.main"
start_service "moltgit" $MOLTGIT_PORT "moltgit.main"
start_service "taskshop" $TASKSHOP_PORT "taskshop.main"

# Start gateway (for real bot runs with Claude CLI)
start_gateway() {
    local port=$GATEWAY_PORT

    if check_port $port; then
        echo -e "${YELLOW}gateway already running on port $port${NC}"
        return 0
    fi

    echo -n "Starting gateway on port $port... "

    cd "$PROJECT_DIR"
    nohup uv run python -m clawdbot.gateway.service --port "$port" --claude-slots 2 \
        > "$LOG_DIR/gateway.log" 2>&1 &
    local pid=$!
    echo $pid > "$PID_DIR/gateway.pid"

    # Wait for service to be ready
    sleep 2
    if curl -s "http://localhost:$port/health" >/dev/null 2>&1; then
        echo -e "${GREEN}OK${NC} (PID: $pid)"
        return 0
    else
        echo -e "${RED}FAILED${NC}"
        return 1
    fi
}

start_gateway

echo
echo "========================================"
echo "Service Status"
echo "========================================"
echo "  Observatory: http://localhost:$OBSERVATORY_PORT"
echo "  Moltbook:    http://localhost:$MOLTBOOK_PORT"
echo "  MoltGit:     http://localhost:$MOLTGIT_PORT"
echo "  Task Shop:   http://localhost:$TASKSHOP_PORT"
echo "  Gateway:     http://localhost:$GATEWAY_PORT (Claude CLI router)"
echo
echo "Logs: $LOG_DIR/"
echo "PIDs: $PID_DIR/"
echo
echo "To stop services: ./scripts/stop_services.sh"
