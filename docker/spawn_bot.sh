#!/bin/bash
# Spawn a new OpenClaw bot container
#
# Usage: ./spawn_bot.sh <bot-name> [balance] [cycles]
# Example: ./spawn_bot.sh bot-child-1 0.30 50

set -e

BOT_NAME="${1:-bot-$(date +%s)}"
BOT_BALANCE="${2:-0.50}"
BOT_CYCLES="${3:-100}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Spawning OpenClaw bot: $BOT_NAME"
echo "  Balance: \$$BOT_BALANCE"
echo "  Cycles: $BOT_CYCLES"

# Create workspace and log directories
mkdir -p "$PROJECT_DIR/workspaces/$BOT_NAME"
mkdir -p "$PROJECT_DIR/logs/$BOT_NAME"

# Run container
docker run -d \
    --name "moltnet-$BOT_NAME" \
    --network moltnet-openclaw \
    -v "$PROJECT_DIR/workspaces/$BOT_NAME:/workspace" \
    -v "$PROJECT_DIR/logs/$BOT_NAME:/logs" \
    -v "$HOME/.claude:/root/.claude:ro" \
    -v "$HOME/.anthropic:/root/.anthropic:ro" \
    -e "BOT_NAME=$BOT_NAME" \
    -e "BOT_BALANCE=$BOT_BALANCE" \
    -e "BOT_CYCLES=$BOT_CYCLES" \
    -e "OBSERVATORY_URL=http://observatory:9100" \
    -e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}" \
    -e "CEREBRAS_API_KEY=${CEREBRAS_API_KEY:-}" \
    --memory="1g" \
    --cpus="1" \
    --restart=no \
    moltnet-openclaw-bot

echo "Bot spawned: moltnet-$BOT_NAME"
echo "View logs: docker logs -f moltnet-$BOT_NAME"
echo "Workspace: $PROJECT_DIR/workspaces/$BOT_NAME"
