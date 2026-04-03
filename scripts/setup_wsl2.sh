#!/bin/bash
# SELENE WSL2 Setup Script
# Run this inside your WSL2 Ubuntu terminal:
#   cd /mnt/c/Users/hoyer/WorkSpace/Projects/selene
#   bash scripts/setup_wsl2.sh
#
# This installs ROS 2 Jazzy + Gazebo Harmonic on Ubuntu 24.04

set -e

echo "============================================"
echo " SELENE WSL2 Environment Setup"
echo " Ubuntu 24.04 + ROS 2 Jazzy + Gazebo Harmonic"
echo "============================================"
echo ""

# --- Step 1: ROS 2 Jazzy Repository ---
echo "[1/6] Adding ROS 2 Jazzy repository..."
sudo apt-get update -qq
sudo apt-get install -y -qq software-properties-common curl gnupg lsb-release
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" | \
    sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
echo "  ROS 2 repo added."

# --- Step 2: Gazebo Harmonic Repository ---
echo "[2/6] Adding Gazebo Harmonic repository..."
sudo curl -sSL https://packages.osrfoundation.org/gazebo.gpg \
    -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] \
http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" | \
    sudo tee /etc/apt/sources.list.d/gazebo-stable.list > /dev/null
echo "  Gazebo repo added."

# --- Step 3: Install ROS 2 Jazzy ---
echo "[3/6] Installing ROS 2 Jazzy (this may take several minutes)..."
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
echo "[4/6] Installing Gazebo Harmonic..."
sudo apt-get install -y gz-harmonic
echo "  Gazebo Harmonic installed."

# --- Step 5: Install Build Tools & Python Dependencies ---
echo "[5/6] Installing build tools and Python deps..."
sudo apt-get install -y \
    python3-colcon-common-extensions \
    python3-pip \
    python3-pytest \
    python3-yaml \
    python3-numpy \
    python3-scipy \
    python3-pydantic
# Install any missing Python packages
pip3 install --break-system-packages pydantic pyyaml 2>/dev/null || true
echo "  Build tools installed."

# --- Step 6: Shell Setup ---
echo "[6/6] Configuring shell..."
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
echo "   source /opt/ros/jazzy/setup.bash"
echo "   cd /mnt/c/Users/hoyer/WorkSpace/Projects/selene"
echo "   colcon build --symlink-install"
echo "   source install/setup.bash"
echo "   ros2 launch selene_sim simulation.launch.py"
echo "============================================"
