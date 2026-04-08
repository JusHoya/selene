cmake_minimum_required(VERSION 3.8)
project(selene_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/RobotState.msg"
  "msg/TaskAnnouncement.msg"
  "msg/BidResponse.msg"
  "msg/TaskAssignment.msg"
  "msg/ResourceMapUpdate.msg"
  "msg/FleetAlert.msg"
  "msg/MissionProgress.msg"
  "srv/InjectTask.srv"
  "srv/OverrideRobot.srv"
  "srv/SetRobotCommand.srv"
  DEPENDENCIES builtin_interfaces geometry_msgs
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
