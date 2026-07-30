#!/bin/bash
# SELENE WSL2 Setup Script
# Run this inside your WSL2 Ubuntu terminal from anywhere in the repo:
#   cd <repo>/                 # e.g. /mnt/w/Hoya_Space/Projects/selene
#   bash scripts/setup_wsl2.sh
#
# This installs ROS 2 Jazzy + Gazebo Harmonic + Node.js 18+ on Ubuntu 24.04

set -e

# Repo root, derived from this script's location (no hardcoded usernames).
SELENE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "============================================"
echo " SELENE WSL2 Environment Setup"
echo " Ubuntu 24.04 + ROS 2 Jazzy + Gazebo Harmonic + Node.js"
echo " Repo: $SELENE_SRC"
echo "============================================"
echo ""

# --- Step 1: ROS 2 Jazzy Repository ---
echo "[1/7] Adding ROS 2 Jazzy repository..."
sudo apt-get update -qq
sudo apt-get install -y -qq software-properties-common curl gnupg lsb-release
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" | \
    sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
echo "  ROS 2 repo added."

# --- Step 2: Gazebo Harmonic Repository ---
echo "[2/7] Adding Gazebo Harmonic repository..."
sudo curl -sSL https://packages.osrfoundation.org/gazebo.gpg \
    -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] \
http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" | \
    sudo tee /etc/apt/sources.list.d/gazebo-stable.list > /dev/null
echo "  Gazebo repo added."

# --- Step 3: Install ROS 2 Jazzy ---
echo "[3/7] Installing ROS 2 Jazzy (this may take several minutes)..."
sudo apt-get update -qq
sudo apt-get install -y \
    ros-jazzy-ros-base \
    ros-jazzy-ros-gz-sim \
    ros-jazzy-ros-gz-bridge \
    ros-jazzy-ros-gz-image \
    ros-jazzy-rosbridge-suite \
    ros-jazzy-lifecycle-msgs \
    ros-jazzy-nav-msgs \
    ros-jazzy-sensor-msgs \
    ros-jazzy-geometry-msgs \
    ros-jazzy-std-msgs \
    ros-jazzy-rviz2
echo "  ROS 2 Jazzy installed."

# --- Step 4: Install Gazebo Harmonic ---
echo "[4/7] Installing Gazebo Harmonic..."
sudo apt-get install -y gz-harmonic
echo "  Gazebo Harmonic installed."

# --- Step 5: Install Build Tools & Python Dependencies ---
echo "[5/7] Installing build tools and Python deps..."
# python3-pil: selene_sim/scripts/generate_heightmap.py does
# `from PIL import Image`. It was an undeclared dependency, so regenerating the
# heightmaps failed on a machine provisioned only by this script.
sudo apt-get install -y \
    python3-colcon-common-extensions \
    python3-pip \
    python3-pytest \
    python3-yaml \
    python3-numpy \
    python3-scipy \
    python3-pil

# Pydantic v2 is REQUIRED and must not come from apt.
#
# Ubuntu 24.04 ships python3-pydantic 1.10 as a compiled .so in
# /usr/lib/python3/dist-packages. selene_hal/selene_hal/robot_descriptor.py uses
# v2-only APIs (field_validator, model_validator, model_validate), so on v1 the
# HAL — and therefore every agent node — dies at import with:
#   ImportError: cannot import name 'field_validator' from 'pydantic'
# selene_hal/setup.py correctly declares pydantic>=2.0, which is exactly why
# this is easy to miss: the metadata is right and the environment is wrong.
#
# A plain pip upgrade does NOT fix it: pip cannot uninstall Debian's
# typing_extensions (no RECORD file), so the upgrade aborts and apt's v1 stays.
# Remove the apt package first, then install v2 shadowing typing_extensions.
# This sequence was verified on Ubuntu 24.04.3 + ROS 2 Jazzy (2026-07-29).
echo "  Ensuring Pydantic v2 (apt ships v1, which breaks the HAL)..."
if dpkg -l python3-pydantic 2>/dev/null | grep -q '^ii'; then
    sudo apt-get remove -y python3-pydantic
fi
pip3 install --break-system-packages --ignore-installed typing_extensions \
    "pydantic>=2.0" pyyaml
python3 - <<'PYCHECK' || exit 1
import sys
try:
    import pydantic
    from pydantic import field_validator, model_validator  # noqa: F401
except Exception as exc:
    print(f"  ERROR: Pydantic v2 not importable after install: {exc}", file=sys.stderr)
    sys.exit(1)
major = int(str(pydantic.VERSION).split(".")[0])
if major < 2:
    print(f"  ERROR: pydantic {pydantic.VERSION} resolved; the RCDL parser needs >= 2.0.",
          file=sys.stderr)
    print(f"         Resolved from: {pydantic.__file__}", file=sys.stderr)
    sys.exit(1)
print(f"  pydantic {pydantic.VERSION} OK (from {pydantic.__file__})")
PYCHECK
echo "  Build tools installed."

# --- Step 6: Install Node.js 18+ (dashboard prerequisite) ---
echo "[6/7] Installing Node.js 18+ (dashboard)..."
NODE_MAJOR_REQUIRED=18
NODE_MAJOR_INSTALL=20   # NodeSource LTS line
CURRENT_NODE_MAJOR=0
if command -v node > /dev/null 2>&1; then
    # Non-numeric / unexpected output falls back to 0 so the arithmetic tests below
    # stay valid under `set -e`.
    CURRENT_NODE_MAJOR=$(node -v 2>/dev/null | sed -n 's/^v\([0-9][0-9]*\).*/\1/p')
    CURRENT_NODE_MAJOR=${CURRENT_NODE_MAJOR:-0}
fi
if [ "$CURRENT_NODE_MAJOR" -ge "$NODE_MAJOR_REQUIRED" ]; then
    echo "  Node.js $(node -v) already present (>= ${NODE_MAJOR_REQUIRED}); skipping install."
else
    if [ "$CURRENT_NODE_MAJOR" -gt 0 ]; then
        echo "  Node.js $(node -v) is older than ${NODE_MAJOR_REQUIRED}; installing ${NODE_MAJOR_INSTALL}.x."
    fi
    # NodeSource setup script; works on Ubuntu 22.04 and 24.04.
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR_INSTALL}.x" | sudo -E bash -
    sudo apt-get install -y nodejs
fi

# Verify: the rest of the toolchain (sync_and_build.sh, dashboard.launch.py)
# resolves npm via PATH, so both binaries must be reachable.
if ! command -v node > /dev/null 2>&1; then
    echo "  ERROR: node is still not on PATH after install." >&2
    exit 1
fi
if ! command -v npm > /dev/null 2>&1; then
    echo "  ERROR: npm is still not on PATH after install." >&2
    exit 1
fi
echo "  node: $(node -v) at $(command -v node)"
echo "  npm:  $(npm -v) at $(command -v npm)"

# --- Step 7: Shell Setup ---
echo "[7/7] Configuring shell..."
SETUP_LINE="source /opt/ros/jazzy/setup.bash"
if ! grep -q "$SETUP_LINE" ~/.bashrc; then
    echo "$SETUP_LINE" >> ~/.bashrc
    echo "  Added ROS 2 Jazzy to ~/.bashrc"
else
    echo "  ROS 2 already in ~/.bashrc"
fi

echo ""
echo "============================================"
echo " Setup complete!"
echo ""
echo " Next steps:"
echo "   bash \"$SELENE_SRC/scripts/sync_and_build.sh\""
echo "   source ~/selene/install/setup.bash"
echo "   ros2 launch selene_sim unified_sim.launch.py"
echo ""
echo " Preflight check before a demo:"
echo "   bash \"$SELENE_SRC/scripts/check_env.sh\""
echo "============================================"
