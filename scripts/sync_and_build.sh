#!/bin/bash
# Sync the project to the Linux filesystem and build. Run once after code changes.
#
# Usage:
#   bash scripts/sync_and_build.sh
#
# The source directory is derived from this script's own location, so the repo can
# live anywhere (/mnt/w/..., /mnt/c/..., or already on ext4) and no username is
# baked in. Override the destination with SELENE_DEST:
#   SELENE_DEST=/opt/selene bash scripts/sync_and_build.sh
#
# Optional: SELENE_PREBUILD_DASHBOARD=1 also runs `npm run build` so the demo can
# serve a prebuilt dashboard (see selene_sim/launch/dashboard.launch.py
# prebuilt:=true) instead of waiting on the webpack dev server.

set -e
set -o pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${SELENE_DEST:-$HOME/selene}"
ROS_SETUP="${SELENE_ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

# Resolve npm via PATH. Hardcoding /usr/bin/npm breaks nvm / fnm / asdf installs.
NPM="$(command -v npm || true)"
if [ -z "$NPM" ]; then
    echo "ERROR: npm was not found on PATH." >&2
    echo "  The dashboard requires Node.js 18+ and npm." >&2
    echo "  Install them with: bash \"$SRC/scripts/setup_wsl2.sh\"" >&2
    echo "  (or manually, see https://github.com/nodesource/distributions)" >&2
    exit 1
fi

if [ ! -f "$ROS_SETUP" ]; then
    echo "ERROR: ROS 2 setup script not found at $ROS_SETUP" >&2
    echo "  Install ROS 2 with: bash \"$SRC/scripts/setup_wsl2.sh\"" >&2
    echo "  or point SELENE_ROS_SETUP at your setup.bash." >&2
    exit 1
fi

if [ "$SRC" = "$DEST" ]; then
    echo "Source and destination are identical ($SRC) - skipping rsync."
else
    echo "Syncing $SRC -> $DEST ..."
    mkdir -p "$DEST"
    rsync -a --delete --exclude=build --exclude=install --exclude=log --exclude=.git \
      --exclude=__pycache__ --exclude='*.egg-info' --exclude=node_modules \
      "$SRC/" "$DEST/"
fi

# shellcheck source=/dev/null  # path is deliberately configurable via SELENE_ROS_SETUP
source "$ROS_SETUP"

COLCON_LOG=/tmp/selene_colcon_build.log
NPM_LOG=/tmp/selene_npm_install.log

cd "$DEST"
echo "Building ROS 2 packages..."
# Full output goes to a log; only the tail is shown. pipefail (set above) means a
# colcon failure aborts here instead of being masked by tail's exit status.
if ! colcon build --symlink-install > "$COLCON_LOG" 2>&1; then
    tail -30 "$COLCON_LOG" >&2
    echo "ERROR: colcon build failed. Full log: $COLCON_LOG" >&2
    exit 1
fi
tail -3 "$COLCON_LOG"

echo "Installing dashboard dependencies..."
cd "$DEST/selene_dashboard"
if ! "$NPM" install --silent > "$NPM_LOG" 2>&1; then
    tail -30 "$NPM_LOG" >&2
    echo "ERROR: npm install failed. Full log: $NPM_LOG" >&2
    exit 1
fi
tail -1 "$NPM_LOG"

if [ "${SELENE_PREBUILD_DASHBOARD:-0}" = "1" ]; then
    echo "Building dashboard production bundle (npm run build)..."
    if ! "$NPM" run build > /tmp/selene_npm_build.log 2>&1; then
        tail -30 /tmp/selene_npm_build.log >&2
        echo "ERROR: npm run build failed. Full log: /tmp/selene_npm_build.log" >&2
        exit 1
    fi
    tail -5 /tmp/selene_npm_build.log
fi

echo ""
echo "Build complete. Run: bash scripts/start.sh"
echo "  (or: ros2 launch selene_sim unified_sim.launch.py)"
echo "Dashboard will open at: http://localhost:3000"
