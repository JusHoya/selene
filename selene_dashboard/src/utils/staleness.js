// A-stale: single definition of "this robot's telemetry has stopped".
//
// The reducer stamps `lastUpdate` on every RobotState message. Before this
// module the 5s threshold lived only in FleetCards.jsx, so staleness was
// visible on the fleet cards and nowhere else — a robot whose telemetry had
// stopped still drew normally on the map, still showed live-looking values in
// RobotDetail, and still counted as "active".

// A robot is considered stale if we have not heard from it for this long.
// Robot state is published well inside this window in the nominal case
// (dashboard subscribes with throttle_rate: 500 ms).
export const STALE_THRESHOLD_MS = 5000;

/** Milliseconds since the last telemetry update, or null if never seen. */
export function staleAgeMs(robot, now = Date.now()) {
  if (!robot || !robot.lastUpdate) return null;
  return Math.max(0, now - robot.lastUpdate);
}

/** True when the robot has a lastUpdate stamp that is older than the threshold. */
export function isStale(robot, now = Date.now(), threshold = STALE_THRESHOLD_MS) {
  const age = staleAgeMs(robot, now);
  return age != null && age > threshold;
}

/** Whole seconds since last update, for display ("last update 12s ago"). */
export function staleAgeSeconds(robot, now = Date.now()) {
  const age = staleAgeMs(robot, now);
  return age == null ? null : Math.floor(age / 1000);
}
