// D-31: the single definition of "this robot has a position fix".
//
// Deliberately shaped like utils/staleness.js, and for the same reason. Before
// that module the 5 s staleness threshold lived only in FleetCards.jsx, so a
// robot whose telemetry had stopped still drew normally on the map and still
// showed live-looking numbers in RobotDetail. Position validity is the same
// class of fact — one wire field that four views have to agree about — so it
// gets one module rather than four inlined `!== false` tests that can drift
// apart the way LABEL_SEP_PX_X drifted from the label it guarded (D-16(a)).
//
// WHAT THE FIELD MEANS. selene_msgs/msg/RobotState gained a trailing
// `bool pose_valid` closing D-31: `GazeboOdometrySensor.read()` never raises,
// and before the first /odom_world message arrives it returns a cached
// OdometryReading with is_valid=False and x/y at the dataclass default 0.0
// (selene_hal/selene_hal/gazebo_hal.py:357-359, :385-387). AgentNode
// ._publish_state copied that straight into RobotState.pose, so every robot
// published a confident (0, 0) at 2 Hz from node start until its Gazebo model
// existed. Launch starts every agent at t=12 s
// (selene_sim/launch/unified_sim.launch.py:177-178) while spawns are staggered
// 2 s apart (selene_sim/launch/simulation.launch.py:206-210), so the later
// robots in the shipped ten-robot fleet fabricate for 2-8 s each.
//
// The .msg says, in its own words: "`pose` IS STILL POPULATED when this is
// false -- the flag, not the value, carries the meaning ... A consumer that
// integrates, averages or renders `pose` must test this field first." The
// message keeps flowing because it is also the heartbeat FleetMonitor reads.
//
// WHY (0,0) IS THE DANGEROUS VALUE AND NOT AN OBVIOUSLY BROKEN ONE. The world
// is 500x500 m centred on the origin (utils/worldConfig.js), so world (0, 0) is
// mid-map, on traversable terrain, inside DEFAULT_VIEW's framing. A robot drawn
// there looks like a robot that is there. Nothing about the icon, the state dot
// or the battery gauge says otherwise, which is what makes this a fabrication
// rather than a glitch.
//
// ---------------------------------------------------------------------------
// THE DEFAULT, AND WHY THE DASHBOARD'S DIFFERS FROM THE ORCHESTRATOR'S.
// ---------------------------------------------------------------------------
//
// ROS 2 default-initialises bool to false and a subscriber there cannot
// distinguish "the publisher set it false" from "the publisher never set it".
// The Python consumers therefore had to pick a side of a two-way trade and they
// picked opposite sides on purpose:
//
//   * selene_orchestrator/.../orchestrator_node.py:1517 reads `bool(msg
//     .pose_valid)` DIRECTLY. Against a stale generated package that raises
//     AttributeError, loudly, which is what it wants: appending a field changes
//     the type hash, so a publisher without it cannot connect at all.
//   * scripts/phase5_probe.py:962 reads `bool(getattr(msg, 'pose_valid', True))`
//     WITH a default, so a pre-D-31 workspace degrades instead of dying.
//
// THE BROWSER IS NOT ON THAT DILEMMA, because rosbridge delivers JSON. A
// publisher whose definition predates D-31 yields an object with NO pose_valid
// KEY — `undefined`, not `false`. So this side gets three states where ROS 2
// gets two, and it should use all three rather than collapsing them:
//
//   msg.pose_valid === true        the publisher says there is a fix
//   msg.pose_valid === false       the publisher says there is NO fix   <- D-31
//   key absent                     the publisher predates the field
//
// The third case is treated as "assume a fix, and SAY SO" — the phase5_probe
// side of the trade, made visible instead of silent. Three reasons, in order of
// weight:
//
//  1. It is a WHOLE-FLEET condition, not a per-robot one. rosbridge_server
//     serialises using ITS OWN build of selene_msgs, so the key is present for
//     every robot or for none; a mixed fleet over one bridge is not reachable.
//     Reading an absent key as "no fix" would therefore not degrade the map, it
//     would EMPTY it — every robot silently gone, which is the failure mode this
//     module exists to prevent, applied to the whole fleet at once.
//  2. Against a pre-D-31 bridge, assuming a fix reproduces the old behaviour
//     exactly. That behaviour is wrong for 2-8 s per robot at startup and
//     correct thereafter, and it is documented; an empty map is wrong for the
//     entire session and looks like a dead backend.
//  3. The cost of (2) is paid down by making it visible rather than assumed:
//     `poseValidityReported` is false in that case and RobotDetail prints an
//     explicit "publisher sends no pose_valid" note beside the coordinates it is
//     therefore not able to qualify.
//
// NOT VERIFIED HERE: that rosbridge omits the key rather than substituting
// false. It is read from the rosbridge JSON contract (a field the local .msg
// does not define cannot be serialised) and from the ROS 2 type-hash behaviour
// the .msg comment describes, not executed against a live bridge. If a bridge
// did substitute `false`, this module would read it as an explicit no-fix and
// the whole fleet would move to the no-fix list — visibly, with every robot
// named, which is the failure this file would want in that case anyway.

/**
 * Decode RobotState.pose_valid off the wire.
 *
 * Returns the effective validity AND whether the publisher reported it at all,
 * because those are two different facts and the UI says different things about
 * them. `null` is folded in with `undefined`: some bridge shims null a field
 * they cannot serialise, and that is "not reported", not "no fix".
 */
export function decodePoseValidity(msg) {
  const raw = msg ? msg.pose_valid : undefined;
  const reported = raw !== undefined && raw !== null;
  return {
    // `!!raw` rather than `raw === true`: a bridge that hands us 1/0 for a ROS
    // bool means the same thing it means in ROS. A REPORTED falsy value is a
    // no-fix; only an absent one falls back.
    poseValid: reported ? !!raw : true,
    poseValidReported: reported,
  };
}

/**
 * True when this robot's `pose` may be used as a position.
 *
 * `!== false` rather than `=== true` so that a robot record without the field —
 * a fixture, or a record built before the reducer projected it — reads as
 * having a fix, which is the same legacy rule decodePoseValidity applies to the
 * wire. One rule, stated once.
 */
export function hasPositionFix(robot) {
  return !!robot && robot.pose_valid !== false;
}

/**
 * True when the publisher actually carried pose_valid for this robot, i.e. when
 * `hasPositionFix` above is a MEASUREMENT rather than the legacy assumption.
 */
export function poseValidityReported(robot) {
  return !!robot && robot.poseValidReported === true;
}

/**
 * The ids of every known robot that has no position fix, sorted.
 *
 * Sorted because this feeds an on-screen list and an unsorted Object.values()
 * order would reshuffle the names as robots update. Staleness is deliberately
 * NOT considered: a robot that has gone quiet AND has no fix still has no fix,
 * and the two conditions are reported in separate places.
 */
export function robotsWithoutFix(robots) {
  if (!robots) return [];
  return Object.values(robots)
    .filter((r) => r && !hasPositionFix(r))
    .map((r) => r.robot_id)
    .sort();
}
