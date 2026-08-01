// A-stale: single definition of "this robot's telemetry has stopped".
//
// The reducer stamps `lastUpdate` on every RobotState message. Before this
// module the 5s threshold lived only in FleetCards.jsx, so staleness was
// visible on the fleet cards and nowhere else — a robot whose telemetry had
// stopped still drew normally on the map, still showed live-looking values in
// RobotDetail, and still counted as "active".

// A robot is considered stale if we have not heard from it for this long.
//
// Robot state is published well inside this window in the nominal case: the
// agent's own timer emits RobotState every 0.5 s, and since D-34 it ALSO emits
// one on every FSM transition, so the observed interval is 0.5 s or shorter.
//
// This comment used to justify the window with "dashboard subscribes with
// throttle_rate: 500 ms" — i.e. with a rosbridge server-side rate limit rather
// than with the publisher. That premise is now false (App.jsx subscribes
// unthrottled, deliberately: a throttle DROPS transition samples, which is the
// aliasing D-34 exists to remove) and it was the wrong basis anyway. A throttle
// can only ever make the observed interval LONGER, so quoting it as the reason a
// 5 s max-age test is safe had the argument backwards.
//
// The 5000 ms value itself is unchanged and is unaffected by the rate: this is a
// max-AGE test, so a higher publish rate can only move measured ages down.
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
