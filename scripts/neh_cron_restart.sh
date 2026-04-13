#!/usr/bin/env bash
# If NEH_RESTART_FLAG_PATH exists (touched by Admin → Settings when the operator checks
# "request restart"), remove it and restart the bot. Intended to run from cron every minute.
#
# Environment (optional overrides):
#   NEH_HOME             — repo root (default: parent of this script’s directory)
#   NEH_RESTART_FLAG_PATH — must match the same variable in the bot’s .env
#   NEH_SCREEN_SESSION   — GNU screen session name (default: nothing-ever-happens)
#
# Crontab example (root, same user that runs the bot):
#   * * * * * NEH_HOME=/root/nothing-ever-happens NEH_RESTART_FLAG_PATH=/root/nothing-ever-happens/data/.neh_restart_requested /root/nothing-ever-happens/scripts/neh_cron_restart.sh >>/root/nothing-ever-happens/logs/cron_restart.log 2>&1
#
# If you use systemd instead of screen, replace the restart block below with e.g.:
#   systemctl restart neh-bot.service

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEH_HOME="$(cd "${NEH_HOME:-$SCRIPT_DIR/..}" && pwd)"
FLAG="${NEH_RESTART_FLAG_PATH:-$NEH_HOME/data/.neh_restart_requested}"
SCREEN="${NEH_SCREEN_SESSION:-nothing-ever-happens}"

if [[ ! -f "$FLAG" ]]; then
  exit 0
fi

echo "$(date -Iseconds) neh_cron_restart: flag found at $FLAG, restarting session $SCREEN" >&2
rm -f "$FLAG"

if ! command -v screen >/dev/null 2>&1; then
  echo "$(date -Iseconds) neh_cron_restart: error: screen not installed" >&2
  exit 1
fi

screen -S "$SCREEN" -X quit 2>/dev/null || true
sleep 2
mkdir -p "$NEH_HOME/logs"
screen -dmS "$SCREEN" bash -lc "cd \"$NEH_HOME\" && source venv/bin/activate && exec python -m bot.main >>\"$NEH_HOME/logs/screen.log\" 2>&1"
echo "$(date -Iseconds) neh_cron_restart: new screen session started" >&2
