// A15: FALLBACK ONLY — hardcoded fleet composition.
//
// This list is NOT the source of truth for the fleet. It is used only when
// dynamic discovery via the rosapi node is unavailable (e.g. a bridge without
// rosbridge_suite's rosapi, or a hand-rolled mock bridge). The launch file
// supports num_scouts / num_excavators / num_haulers, so any fleet that is not
// exactly the default 2+1+1 composition will NOT be represented by this list.
// See hooks/useFleetDiscovery.js for the discovery path.
export const FALLBACK_ROBOT_IDS = [
  'scout_01', 'scout_02', 'excavator_01', 'hauler_01',
];

// Backwards-compatible alias. Prefer FALLBACK_ROBOT_IDS at call sites so the
// fallback nature is obvious.
export const ROBOT_IDS = FALLBACK_ROBOT_IDS;

// Topic templates (replace {id} with robot_id)
export const TOPICS = {
  ROBOT_STATE: (id) => `/${id}/state`,
  BATTERY_STATE: (id) => `/${id}/battery_state`,
  PLANNED_PATH: (id) => `/${id}/planned_path`,
  NEUTRON_SPEC: (id) => `/${id}/sensors/neutron_spec`,
  // Raw per-reading updates from each scout. Still consumed by ResourceGraph
  // (the concentration-vs-time trace), which needs individual samples; the map
  // heatmap no longer builds from these — see RESOURCE_MAP below.
  MAP_UPDATE: '/orchestrator/map_update',
  // D-02: the orchestrator's FUSED POSTERIOR grid, published since D-09 at
  // resource_map_publish_rate (0.5 Hz). This is what the map heatmap renders,
  // so the dashboard and the RViz2 overlay show the same estimate rather than
  // two different reductions of the same readings.
  RESOURCE_MAP: '/orchestrator/resource_map',
  FLEET_ALERT: '/orchestrator/alerts',
  MISSION_PROGRESS: '/orchestrator/mission_progress',
  // D-03: the authoritative task-table snapshot (2 Hz). Replaces the
  // client-side lifecycle inference that used to be reconstructed from
  // TASK_ANNOUNCEMENT / TASK_ASSIGNMENT / RobotState.current_task_id.
  TASK_QUEUE: '/orchestrator/task_queue',
  // D-03: kept as constants because both topics are still published, but the
  // dashboard no longer subscribes to either. Everything they were used to
  // infer now arrives on TASK_QUEUE as orchestrator-side truth.
  TASK_ANNOUNCEMENT: '/orchestrator/task_announcement',
  TASK_ASSIGNMENT: '/orchestrator/task_assignment',
};

// roslib message type strings
export const MSG_TYPES = {
  ROBOT_STATE: 'selene_msgs/RobotState',
  BATTERY_STATE: 'sensor_msgs/BatteryState',
  RESOURCE_MAP_UPDATE: 'selene_msgs/ResourceMapUpdate',
  // Short two-part form, matching every other entry here. Topic SUBSCRIPTION
  // resolves either spelling; only the rosapi introspection request below is
  // strict about the three-part form (see the note at ROBOT_STATE_TYPE_CANDIDATES).
  RESOURCE_MAP: 'selene_msgs/ResourceMap',
  TASK_QUEUE: 'selene_msgs/TaskQueueState',
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

// A15: rosapi introspection service used for dynamic fleet discovery.
// rosbridge_suite ships the rosapi node alongside rosbridge_websocket.
export const ROSAPI = {
  TOPICS_FOR_TYPE: '/rosapi/topics_for_type',
};

// A15: Candidate service-type strings for /rosapi/topics_for_type, tried in
// order. The srv definitions live in `rosapi_msgs` on ROS 2 and in `rosapi`
// on ROS 1; rosbridge's ROS 2 call_service capability also resolves the type
// from the graph itself, so the string is advisory there. Trying both keeps a
// type-string mismatch from silently forcing the hardcoded fallback.
// VERIFIED: 'rosapi_msgs/srv/TopicsForType' answers on ROS 2 Jazzy with
// rosbridge_suite (measured against a live rosapi node, 2026-07-29).
export const ROSAPI_TOPICS_FOR_TYPE_TYPES = [
  'rosapi_msgs/srv/TopicsForType',
  'rosapi/TopicsForType',
];

// A15: Candidate *message*-type strings for the topics_for_type REQUEST body,
// tried in order. This is a separate axis from the service type above and it
// matters more, because rosapi compares the requested type string against the
// graph's type string EXACTLY — it does not normalise between the ROS 1 short
// form and the ROS 2 three-part form.
//
// MEASURED on ROS 2 Jazzy against a live rosapi node (2026-07-29), with two
// RobotState publishers up:
//   'selene_msgs/msg/RobotState' -> topics=['/excavator_01/state','/scout_01/state']
//   'selene_msgs/RobotState'     -> topics=[]   (result=True, i.e. a SUCCESS)
// The ROS 2 form must therefore come first. Note the failure mode: the wrong
// string returns success-with-empty, not an error, so a rotation that only
// advances on the error callback can never escape it. useFleetDiscovery also
// rotates on an empty success until a non-empty reply locks the choice.
//
// MSG_TYPES.ROBOT_STATE below keeps the short form because topic SUBSCRIPTION
// resolves either spelling; only this introspection request is strict.
export const ROBOT_STATE_TYPE_CANDIDATES = [
  'selene_msgs/msg/RobotState',
  'selene_msgs/RobotState',
];
