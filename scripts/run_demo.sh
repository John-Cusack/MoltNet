#!/bin/bash
# Run a complete MoltNet demo with all services
#
# Usage:
#   ./scripts/run_demo.sh                      # Run with defaults (3 bots, 50 cycles)
#   ./scripts/run_demo.sh --bots 5 --cycles 100
#   ./scripts/run_demo.sh --archive-after      # Archive data after run completes
#   ./scripts/run_demo.sh --analyze            # Run analysis after completion
#
# This script:
#   1. Starts all services (Observatory, Moltbook, MoltGit)
#   2. Runs the demo colony
#   3. Optionally archives and/or analyzes results
#   4. Stops services (unless --keep-services)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Defaults
BOTS=3
CYCLES=50
ARCHIVE_AFTER=false
ANALYZE_AFTER=false
KEEP_SERVICES=false
SIMULATE=true  # Default to simulation mode

# Parse arguments
DEMO_ARGS=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --bots)
            BOTS="$2"
            shift 2
            ;;
        --cycles)
            CYCLES="$2"
            shift 2
            ;;
        --archive-after)
            ARCHIVE_AFTER=true
            shift
            ;;
        --analyze)
            ANALYZE_AFTER=true
            shift
            ;;
        --keep-services)
            KEEP_SERVICES=true
            shift
            ;;
        --no-simulate)
            SIMULATE=false
            shift
            ;;
        *)
            DEMO_ARGS="$DEMO_ARGS $1"
            shift
            ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================"
echo "MoltNet Demo Runner"
echo -e "========================================${NC}"
echo
echo "Configuration:"
echo "  Bots: $BOTS"
echo "  Cycles: $CYCLES"
echo "  Simulate: $SIMULATE"
echo "  Archive after: $ARCHIVE_AFTER"
echo "  Analyze after: $ANALYZE_AFTER"
echo "  Keep services: $KEEP_SERVICES"
echo

# Step 1: Start services
echo -e "${BLUE}[1/4] Starting services...${NC}"
"$SCRIPT_DIR/start_services.sh"
echo

# Step 2: Run demo
echo -e "${BLUE}[2/4] Running demo colony...${NC}"
echo

cd "$PROJECT_DIR"

DEMO_CMD="uv run python demo_openclaw_colony.py --bots $BOTS --cycles $CYCLES"
if [ "$SIMULATE" = true ]; then
    DEMO_CMD="$DEMO_CMD --simulate"
else
    echo -e "${YELLOW}Running REAL bots - Claude CLI or Cerebras API will be used${NC}"
    echo -e "${YELLOW}Make sure CEREBRAS_API_KEY is set for non-Claude models${NC}"
    echo
fi
DEMO_CMD="$DEMO_CMD $DEMO_ARGS"

echo "Running: $DEMO_CMD"
echo
$DEMO_CMD

DEMO_EXIT=$?

echo
if [ $DEMO_EXIT -eq 0 ]; then
    echo -e "${GREEN}Demo completed successfully.${NC}"
else
    echo -e "${YELLOW}Demo exited with code $DEMO_EXIT${NC}"
fi
echo

# Step 3: Archive (optional)
if [ "$ARCHIVE_AFTER" = true ]; then
    echo -e "${BLUE}[3/4] Archiving run data...${NC}"

    TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
    ARCHIVE_DIR="$PROJECT_DIR/runs/$TIMESTAMP"

    mkdir -p "$ARCHIVE_DIR"

    # Copy data
    if [ -d "$PROJECT_DIR/data" ]; then
        cp -r "$PROJECT_DIR/data" "$ARCHIVE_DIR/"
        echo "  Archived: data/"
    fi

    # Copy logs
    if [ -d "$PROJECT_DIR/logs" ]; then
        cp -r "$PROJECT_DIR/logs" "$ARCHIVE_DIR/"
        echo "  Archived: logs/"
    fi

    # Write metadata
    cat > "$ARCHIVE_DIR/metadata.json" << EOF
{
    "archived_at": "$(date -Iseconds)",
    "bots": $BOTS,
    "cycles": $CYCLES,
    "simulated": $SIMULATE,
    "demo_exit_code": $DEMO_EXIT
}
EOF

    echo -e "${GREEN}Archived to: $ARCHIVE_DIR${NC}"
    echo
else
    echo -e "${YELLOW}[3/4] Skipping archive (use --archive-after to enable)${NC}"
    echo
fi

# Step 4: Analyze (optional)
if [ "$ANALYZE_AFTER" = true ]; then
    echo -e "${BLUE}[4/4] Running analysis...${NC}"
    echo

    if [ "$ARCHIVE_AFTER" = true ]; then
        uv run python analyze_run.py --run "$ARCHIVE_DIR" --export-only
    else
        uv run python analyze_run.py --export-only
    fi
    echo
else
    echo -e "${YELLOW}[4/4] Skipping analysis (use --analyze to enable)${NC}"
    echo
fi

# Stop services unless --keep-services
if [ "$KEEP_SERVICES" = false ]; then
    echo -e "${BLUE}Stopping services...${NC}"
    "$SCRIPT_DIR/stop_services.sh"
else
    echo -e "${YELLOW}Keeping services running (--keep-services)${NC}"
    echo "Stop manually with: ./scripts/stop_services.sh"
fi

echo
echo -e "${GREEN}========================================"
echo "Demo complete!"
echo -e "========================================${NC}"
echo
echo "Data locations:"
echo "  Live data: ./data/, ./logs/"
if [ "$ARCHIVE_AFTER" = true ]; then
    echo "  Archived:  $ARCHIVE_DIR"
fi
echo
echo "To analyze:"
echo "  uv run python analyze_run.py"
if [ "$ARCHIVE_AFTER" = true ]; then
    echo "  uv run python analyze_run.py --run $ARCHIVE_DIR"
fi
