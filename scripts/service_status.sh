#!/bin/bash
# Check status of all MoltNet services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_DIR/.pids"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_service() {
    local name=$1
    local port=$2

    printf "%-12s " "$name:"

    # Check if responding
    if curl -s "http://localhost:$port/health" >/dev/null 2>&1; then
        local health=$(curl -s "http://localhost:$port/health" 2>/dev/null)
        local pid=$(lsof -t -i :$port 2>/dev/null || echo "?")
        echo -e "${GREEN}RUNNING${NC} (port $port, PID $pid)"

        # Show extra stats if available
        if [ "$name" == "moltbook" ]; then
            local stats=$(curl -s "http://localhost:$port/stats" 2>/dev/null)
            local entries=$(echo "$stats" | grep -o '"total_entries":[0-9]*' | cut -d: -f2)
            if [ -n "$entries" ]; then
                echo "             $entries entries"
            fi
        fi
        if [ "$name" == "moltgit" ]; then
            local stats=$(curl -s "http://localhost:$port/stats" 2>/dev/null)
            local repos=$(echo "$stats" | grep -o '"total_repos":[0-9]*' | cut -d: -f2)
            if [ -n "$repos" ]; then
                echo "             $repos repositories"
            fi
        fi
    else
        echo -e "${RED}NOT RUNNING${NC}"
    fi
}

echo "========================================"
echo "MoltNet Service Status"
echo "========================================"
echo

check_service "observatory" 9100
check_service "moltbook" 9101
check_service "moltgit" 9103

echo
echo "Dashboard URLs:"
echo "  Observatory: http://localhost:9100"
echo "  Moltbook:    http://localhost:9101/stats"
echo "  MoltGit:     http://localhost:9103/stats"
