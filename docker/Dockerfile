FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive

# Install Gazebo Harmonic
RUN apt-get update && apt-get install -y \
    wget lsb-release gnupg curl \
    && wget https://packages.osrfoundation.org/gazebo.gpg \
        -O /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update \
    && apt-get install -y gz-harmonic \
    && rm -rf /var/lib/apt/lists/*

# Install ROS-Gazebo bridge and dev tools
RUN apt-get update && apt-get install -y \
    python3-colcon-common-extensions \
    python3-pip \
    ros-humble-ros-gz-sim \
    ros-humble-ros-gz-bridge \
    ros-humble-ros-gz-image \
    ros-humble-rosbridge-suite \
    ros-humble-lifecycle-msgs \
    ros-humble-nav-msgs \
    ros-humble-sensor-msgs \
    ros-humble-geometry-msgs \
    ros-humble-rviz2 \
    && rm -rf /var/lib/apt/lists/*

# Python dev tools
RUN pip3 install --no-cache-dir \
    pytest>=7.0 pytest-cov flake8 mypy black \
    numpy>=1.23 scipy>=1.9 pydantic>=2.0 pyyaml

# Node.js 18 LTS for dashboard
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ros2_ws/src
COPY . /ros2_ws/src/selene/

WORKDIR /ros2_ws
RUN /bin/bash -c "source /opt/ros/humble/setup.bash && colcon build --symlink-install"

WORKDIR /ros2_ws/src/selene/selene_dashboard
RUN npm install

WORKDIR /ros2_ws
RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc \
    && echo "source /ros2_ws/install/setup.bash" >> /root/.bashrc

ENTRYPOINT ["/bin/bash"]
