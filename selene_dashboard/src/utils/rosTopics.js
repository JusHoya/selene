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
};
