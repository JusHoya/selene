#!/bin/bash
# Sync project to Linux filesystem and build. Run once after code changes.
# Usage: bash scripts/sync_and_build.sh

set -e
rsync -a --delete --exclude=build --exclude=install --exclude=log --exclude=.git \
  --exclude=__pycache__ --exclude='*.egg-info' --exclude=node_modules \
  /mnt/c/Users/hoyer/WorkSpace/Projects/selene/ ~/selene/

source /opt/ros/jazzy/setup.bash
cd ~/selene
echo "Building ROS 2 packages..."
colcon build --symlink-install 2>&1 | tail -3
echo "Installing dashboard dependencies..."
cd ~/selene/selene_dashboard && npm install --silent 2>&1 | tail -1
echo ""
echo "Build complete. Run: bash scripts/start.sh"
echo "Dashboard will open at: http://localhost:3000"
