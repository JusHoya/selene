// Robot IDs (default fleet composition)
export const ROBOT_IDS = ['scout_01', 'scout_02', 'excavator_01', 'hauler_01'];

// Topic templates (replace {id} with robot_id)
export const TOPICS = {
  ROBOT_STATE: (id) => `/${id}/state`,
  BATTERY_STATE: (id) => `/${id}/battery_state`,
  PLANNED_PATH: (id) => `/${id}/planned_path`,
  NEUTRON_SPEC: (id) => `/${id}/sensors/neutron_spec`,
  MAP_UPDATE: '/orchestrator/map_update',
  FLEET_ALERT: '/orchestrator/alerts',
  MISSION_PROGRESS: '/orchestrator/mission_progress',
  TASK_ANNOUNCEMENT: '/orchestrator/task_announcement',
  TASK_ASSIGNMENT: '/orchestrator/task_assignment',
};

// roslib message type strings
export const MSG_TYPES = {
  ROBOT_STATE: 'selene_msgs/RobotState',
  BATTERY_STATE: 'sensor_msgs/BatteryState',
  RESOURCE_MAP_UPDATE: 'selene_msgs/ResourceMapUpdate',
  FLEET_ALERT: 'selene_msgs/FleetAlert',
  MISSION_PROGRESS: 'selene_msgs/MissionProgress',
  FLOAT32: 'std_msgs/Float32',
  PATH: 'nav_msgs/Path',
  TASK_ANNOUNCEMENT: 'selene_msgs/TaskAnnouncement',
  TASK_ASSIGNMENT: 'selene_msgs/TaskAssignment',
  BID_RESPONSE: 'selene_msgs/BidResponse',
};

// Wave2-A4: Orchestrator service names for dashboard->backend calls
export const SERVICES = {
  INJECT_TASK: '/orchestrator/inject_task',
  OVERRIDE_ROBOT: '/orchestrator/override_robot',
};

// Wave2-A4: roslib service type strings
export const SERVICE_TYPES = {
  INJECT_TASK: 'selene_msgs/srv/InjectTask',
  OVERRIDE_ROBOT: 'selene_msgs/srv/OverrideRobot',
};
