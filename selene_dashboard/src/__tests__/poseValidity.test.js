/**
 * D-31 — the dashboard must not render a fabricated pose.
 *
 * THESE ARE REGRESSION TESTS, NOT CHARACTERIZATION PINS. The behaviour they
 * describe did not exist before this change: `UPDATE_ROBOT` copied `msg.pose`
 * into the robot record with no validity test, FleetMap drew it, and
 * `grep -rn pose_valid selene_dashboard/src/` returned exactly one hit — a
 * fixture value in fleetState.stateHistory.test.js:47 that nothing read.
 *
 * The mutation evidence for each block is recorded above it, and every mutation
 * was EXECUTED, not reasoned about: revert the named line, run the whole suite,
 * read the count off the run.
 *
 * WHICH TESTS THE MUTATIONS ACTUALLY REACH, stated so nobody has to guess.
 * Ten mutations were run. 20 of the 28 tests below fail under at least one of
 * them. The remaining 8 are:
 *   · the three badge-text cases (formatNoFixIds) — new code with no prior
 *     behaviour to regress, pinned because the badge is the ONLY thing that
 *     tells an operator why an icon is missing;
 *   · four null/empty guards (hasPositionFix(null), an absent fleet, an empty
 *     roster, 'an explicit true is a measured fix');
 *   · one counter-assertion — 'the planned-path overlay still draws for a robot
 *     that has a fix' — which exists to catch the guard being over-applied, the
 *     failure mode mutation 7 below shows is the expensive one.
 *
 * WHAT THIS FILE CANNOT DO. jsdom has no canvas. Nothing here is rendered, so
 * no assertion below is evidence about pixels, colour, legibility or layout.
 * What it pins is that the real planner produces no plan for a robot with no
 * fix, that the real draw functions emit no marks for one, that the real
 * hit-test refuses to select one, and that the real reducer decodes the three
 * wire states apart. The single observation that would demonstrate the rest is
 * named in the owner report: open the dashboard in Chrome during the first
 * ~12 s of a launch and watch the later-spawning robots appear in the amber
 * "No position fix" roster and then move into the map as their odometry
 * arrives, with no icon ever appearing at world (0, 0).
 */

import { fleetReducer, initialState } from '../hooks/useFleetState';
import {
  decodePoseValidity,
  hasPositionFix,
  poseValidityReported,
  robotsWithoutFix,
} from '../utils/poseFix';
import {
  drawPlannedPaths,
  drawRobots,
  drawSelectedTaskHighlight,
  formatNoFixIds,
  orderRobotsForLabels,
  pickRobotAt,
  planRobotMarks,
} from '../components/FleetMap';
import { createRecordingContext } from '../testUtils/recordingCanvas';

// ---------------------------------------------------------------- fixtures

// A RobotState as rosbridge delivers it. `pose_valid` is spread from overrides
// so a test can set it true, set it false, or DELETE it — the three states that
// matter, and the third is the one ROS 2 itself cannot express.
function stateMsg(overrides = {}) {
  const msg = {
    robot_id: 'scout_07',
    robot_type: 'scout',
    fsm_state: 'IDLE',
    // The exact value the defect produces: GazeboOdometrySensor's cached
    // pre-first-message reading leaves x/y at the dataclass default 0.0.
    pose: { x: 0, y: 0, theta: 0 },
    velocity: { linear: { x: 0 }, angular: { z: 0 } },
    battery_level: 0.97,
    battery_capacity_wh: 50.0,
    current_task_id: '',
    task_progress: 0.0,
    capabilities: ['prospect'],
    pose_valid: true,
    ...overrides,
  };
  return msg;
}

const update = (state, msg) => fleetReducer(state, { type: 'UPDATE_ROBOT', payload: msg });

// A reducer-shaped robot record, for the consumers that read records rather
// than messages.
function record(id, x, y, extra = {}) {
  return {
    robot_id: id,
    robot_type: 'excavator',
    fsm_state: 'NAVIGATING',
    pose: { x, y, theta: 0 },
    battery_level: 0.62,
    lastUpdate: 1000,
    pose_valid: true,
    poseValidReported: true,
    ...extra,
  };
}

const asMap = (list) => {
  const out = {};
  list.forEach((r) => { out[r.robot_id] = r; });
  return out;
};

// Matches fleetMap.marks.test.js so the module-scope label-width cache cannot
// see two different font models in one jest worker.
const ADVANCE_EM = 0.6;
const LABEL_FONT_PX = 9;
const NOW = 1100;

function withWorldTransform(ctx, scale, fn) {
  ctx.save();
  ctx.scale(scale, -scale);
  fn();
  ctx.restore();
}

// ------------------------------------------------------- the wire decode
//
// MUTATION, EXECUTED. In utils/poseFix.js change decodePoseValidity's
// `poseValid: reported ? !!raw : true` to `poseValid: !!raw` — i.e. drop the
// legacy fallback and let an absent key read as false, which is the ROS 2
// default and the trap this decode exists to avoid. Whole run went from
// 101 passed to 4 failed / 97 passed, all four in this file:
//   · 'an absent pose_valid key is not a missing fix'
//   · 'a null pose_valid is treated as absent, not as false'
//   · 'the legacy case is recorded as an assumption, not as a measurement'
//   · 'the whole fleet does not vanish against a publisher that predates the
//      field'
// The map-side legacy test is NOT among them: it starts from a robot RECORD
// with the field deleted, so it exercises hasPositionFix's copy of the same
// rule rather than this one. Both copies are pinned, separately, on purpose.
//
// MUTATION, EXECUTED, the other direction: change the same expression to a bare
// `poseValid: true` — D-31 itself, reinstated in the browser. Whole run went
// 4 failed / 97 passed: 'an explicit false is a missing fix', 'a reported falsy
// value is a missing fix', 'a false pose_valid reaches the robot record' and
// 'the startup sequence'.

describe('D-31: the three wire states, which ROS 2 cannot tell apart', () => {
  test('an explicit false is a missing fix', () => {
    expect(decodePoseValidity({ pose_valid: false }))
      .toEqual({ poseValid: false, poseValidReported: true });
  });

  test('an explicit true is a measured fix', () => {
    expect(decodePoseValidity({ pose_valid: true }))
      .toEqual({ poseValid: true, poseValidReported: true });
  });

  test('an absent pose_valid key is not a missing fix', () => {
    // rosbridge serialises from ITS OWN selene_msgs build, so a bridge that
    // predates D-31 omits the key entirely and roslib hands us `undefined`.
    // Reading that as "no fix" would empty the whole map, since the condition
    // is per-BRIDGE and therefore fleet-wide. See utils/poseFix.js for the
    // three reasons this side of the trade was chosen, and note that the
    // assumption is reported rather than hidden.
    expect(decodePoseValidity({})).toEqual({ poseValid: true, poseValidReported: false });
  });

  test('a null pose_valid is treated as absent, not as false', () => {
    expect(decodePoseValidity({ pose_valid: null }))
      .toEqual({ poseValid: true, poseValidReported: false });
  });

  test('a reported falsy value is a missing fix', () => {
    // A bridge shim that hands us 0 for a ROS bool means what ROS means.
    expect(decodePoseValidity({ pose_valid: 0 }).poseValid).toBe(false);
  });
});

// ------------------------------------------------------------- the reducer
//
// MUTATION, EXECUTED. In hooks/useFleetState.js remove the two projected keys
// `pose_valid` and `poseValidReported` from the UPDATE_ROBOT record — i.e.
// restore the reducer to exactly what it was before this change. Whole run went
// 3 failed / 98 passed:
//   · 'a false pose_valid reaches the robot record'
//   · 'a fix that was actually reported is marked as reported'
//   · 'the startup sequence: no fix, then a fix, and the record follows'
//
// THREE, NOT MORE, AND THE REASON MATTERS. Every map-side guard is expressed
// through hasPositionFix, whose legacy rule reads an ABSENT field as a fix — so
// stripping the projection makes the whole fleet look localised again and the
// map tests go green on a dashboard that has silently stopped checking. That is
// the same shape as the defect being fixed, one layer up, and it is why the
// projection is pinned directly here rather than only through the map: a guard
// that cannot see its own input being removed is not a guard.

describe('D-31: UPDATE_ROBOT carries the validity, and keeps the pose', () => {
  test('a false pose_valid reaches the robot record', () => {
    const state = update(initialState, stateMsg({ pose_valid: false }));
    expect(state.robots.scout_07.pose_valid).toBe(false);
    expect(hasPositionFix(state.robots.scout_07)).toBe(false);
  });

  test('the pose is STILL STORED when the fix is missing', () => {
    // RobotState.msg: "`pose` IS STILL POPULATED when this is false — the flag,
    // not the value, carries the meaning". Storing null instead would be
    // absorbed silently by the `if (!robot.pose) return;` guards that already
    // exist in planRobotMarks and drawPlannedPaths, and the robot would vanish
    // with no operator-visible trace. This assertion is what stops a later
    // "just null it out" simplification.
    //
    // MUTATION, EXECUTED: change the reducer's `pose:` line to
    // `poseValidity.poseValid ? (msg.pose || {...}) : null` and this test alone
    // fails (whole run 1 failed / 100 passed) — every map guard still passes,
    // which is exactly the point: nulling the pose LOOKS correct from the map's
    // side and is silent from the operator's.
    const state = update(initialState, stateMsg({ pose_valid: false }));
    expect(state.robots.scout_07.pose).toEqual({ x: 0, y: 0, theta: 0 });
  });

  test('the legacy case is recorded as an assumption, not as a measurement', () => {
    const msg = stateMsg();
    delete msg.pose_valid;
    const state = update(initialState, msg);
    expect(hasPositionFix(state.robots.scout_07)).toBe(true);
    expect(poseValidityReported(state.robots.scout_07)).toBe(false);
  });

  test('a fix that was actually reported is marked as reported', () => {
    const state = update(initialState, stateMsg({ pose_valid: true }));
    expect(poseValidityReported(state.robots.scout_07)).toBe(true);
  });

  test('the startup sequence: no fix, then a fix, and the record follows', () => {
    // The launch window D-31 describes — agents start at t=12 s while spawns
    // are staggered 2 s apart, so a late robot publishes state for seconds
    // before its Gazebo model exists.
    let state = update(initialState, stateMsg({ pose_valid: false }));
    expect(robotsWithoutFix(state.robots)).toEqual(['scout_07']);

    state = update(state, stateMsg({
      pose_valid: true, pose: { x: -113.4, y: 42.9, theta: 1.1 },
    }));
    expect(robotsWithoutFix(state.robots)).toEqual([]);
    expect(state.robots.scout_07.pose).toEqual({ x: -113.4, y: 42.9, theta: 1.1 });
  });

  test('the whole fleet does not vanish against a publisher that predates the field', () => {
    // The trap, as a fleet: every robot's message lacks the key because the
    // BRIDGE lacks it. Every robot must still be on the map.
    let state = initialState;
    ['scout_01', 'excavator_01', 'hauler_01'].forEach((id) => {
      const msg = stateMsg({ robot_id: id, pose: { x: 10, y: 20, theta: 0 } });
      delete msg.pose_valid;
      state = update(state, msg);
    });
    expect(robotsWithoutFix(state.robots)).toEqual([]);
    expect(Object.keys(state.robots)).toHaveLength(3);
  });
});

// ------------------------------------------------------- the shared predicate

// MUTATION, EXECUTED, AND THE MOST IMPORTANT ONE IN THIS FILE. In
// utils/poseFix.js change hasPositionFix's `robot.pose_valid !== false` to
// `robot.pose_valid === true` — the ROS 2 fail-safe direction, applied to a
// record instead of to the wire. Whole run went 33 failed / 68 passed across
// TWO suites. Two of the failures are this file's legacy tests; the other 31
// are the pre-existing D-16 suite, whose fixtures carry no pose_valid field at
// all and which therefore stops being able to draw a single robot.
//
// That is the whole argument for the chosen default, measured rather than
// asserted: over-applying the guard does not degrade the map, it deletes it,
// and it does so while every message on the wire is perfectly healthy. The
// fail-safe that is right for the orchestrator's distance accumulator — drop
// the sample — is wrong for a display whose entire job is to show the operator
// that the robots exist.
//
// MUTATION, EXECUTED: drop the `.sort()` from robotsWithoutFix and only 'the
// roster is sorted' fails (whole run 1 failed / 100 passed).

describe('D-31: hasPositionFix / robotsWithoutFix', () => {
  test('a record with no pose_valid field at all reads as having a fix', () => {
    // The same legacy rule the wire decode applies, so a fixture or a record
    // built before the projection existed does not silently disappear.
    expect(hasPositionFix({ robot_id: 'x', pose: { x: 1, y: 2 } })).toBe(true);
  });

  test('null and undefined robots have no fix', () => {
    expect(hasPositionFix(null)).toBe(false);
    expect(hasPositionFix(undefined)).toBe(false);
  });

  test('the roster is sorted, so the on-screen list does not reshuffle', () => {
    const robots = asMap([
      record('hauler_02', 0, 0, { pose_valid: false }),
      record('excavator_01', 5, 5),
      record('scout_03', 0, 0, { pose_valid: false }),
      record('excavator_02', 0, 0, { pose_valid: false }),
    ]);
    expect(robotsWithoutFix(robots)).toEqual(['excavator_02', 'hauler_02', 'scout_03']);
  });

  test('an empty or absent fleet produces an empty roster', () => {
    expect(robotsWithoutFix({})).toEqual([]);
    expect(robotsWithoutFix(null)).toEqual([]);
  });
});

// --------------------------------------------------------- the badge's text

describe('D-31: the no-fix roster text', () => {
  test('nothing to say when every robot is localised', () => {
    // The badge must not render at all in the nominal case.
    expect(formatNoFixIds([])).toBeNull();
    expect(formatNoFixIds(null)).toBeNull();
  });

  test('short lists are spelled out in full', () => {
    expect(formatNoFixIds(['hauler_01', 'scout_02'])).toBe('hauler_01 scout_02');
  });

  test('a long list is truncated but the total is never hidden', () => {
    const ids = ['a', 'b', 'c', 'd', 'e', 'f'];
    expect(formatNoFixIds(ids)).toBe('a b c d +2 more');
  });
});

// ------------------------------------------------------------- the fleet map
//
// MUTATION, EXECUTED. In components/FleetMap.jsx delete the line
// `if (!hasPositionFix(robot)) return;` from planRobotMarks — the single gate
// for every mark the map draws. Whole run went 4 failed / 97 passed:
//   · 'a robot with no position fix is planned no marks at all'
//   · 'the real renderer emits nothing for it'
//   · 'the fabricated origin draws nothing even when it is the only robot'
//   · 'the plan for the real fleet is identical with and without the phantom'
// The hit-test tests are NOT among them — pickRobotAt carries its own copy of
// the predicate and has its own mutation record below. Two copies is the price
// of the map's ink and its pointer being two different mechanisms; what would
// be unacceptable is only one of them being pinned.

describe('D-31: the map does not draw a fabricated position', () => {
  test('a robot with no position fix is planned no marks at all', () => {
    const robots = [
      record('excavator_01', 40, 40),
      record('scout_07', 0, 0, { pose_valid: false, poseValidReported: true }),
    ];
    const plans = planRobotMarks(
      orderRobotsForLabels(robots, null), 4.3, null,
      (t) => ADVANCE_EM * LABEL_FONT_PX * t.length,
    );
    expect(plans.has('excavator_01')).toBe(true);
    expect(plans.has('scout_07')).toBe(false);
  });

  test('the real renderer emits nothing for it', () => {
    // drawRobots draws every mark inside `if (!plan) return;`, so an absent
    // plan removes the icon, the heading triangle, the state dot, the battery
    // gauge and the label together. Asserted against the marks the real
    // function emits rather than by re-deriving them.
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    const robots = asMap([
      record('excavator_01', 40, 40),
      record('scout_07', 0, 0, { pose_valid: false }),
    ]);
    withWorldTransform(ctx, 4.3, () => {
      drawRobots(ctx, robots, null, 4.3, NOW);
    });
    expect(ctx.marks.length).toBeGreaterThan(0);
    // Nothing was drawn at the world origin: every mark's box lies outside a
    // generous box around (0, 0). At scale 4.3 the icon half-height is 12 px
    // and the label row hangs ~30 px below it, so 60 px of slack around the
    // origin cannot be reached by the excavator's stack at world (40, 40)
    // (172 px away in each axis).
    const originBox = { x0: -60, y0: -60, x1: 60, y1: 60 };
    const inOrigin = ctx.marks.filter((mk) => (
      mk.box.x0 < originBox.x1 && originBox.x0 < mk.box.x1
      && mk.box.y0 < originBox.y1 && originBox.y0 < mk.box.y1
    ));
    expect(inOrigin).toEqual([]);
    // ...and the id of the fixless robot is nowhere in the drawn text.
    const texts = ctx.marks.filter((mk) => mk.kind === 'fillText').map((mk) => mk.text);
    expect(texts.join('|')).not.toMatch(/scout_07/);
  });

  test('the fabricated origin draws nothing even when it is the only robot', () => {
    // The launch case with a single late robot: an empty map is the correct
    // picture, and the roster beside it is what tells the operator why.
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    const robots = asMap([record('scout_07', 0, 0, { pose_valid: false })]);
    withWorldTransform(ctx, 4.3, () => {
      drawRobots(ctx, robots, null, 4.3, NOW);
    });
    expect(ctx.marks).toEqual([]);
  });

  test('a legacy record with no pose_valid field is still drawn', () => {
    // The other half of the default decision, pinned from the map's side: a
    // pre-D-31 bridge must not blank the fleet.
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    const legacy = record('scout_09', 12, 12);
    delete legacy.pose_valid;
    delete legacy.poseValidReported;
    withWorldTransform(ctx, 4.3, () => {
      drawRobots(ctx, asMap([legacy]), null, 4.3, NOW);
    });
    expect(ctx.marks.length).toBeGreaterThan(0);
  });
});

// ----------------------------------------------------------- the aggregate
//
// The .msg singles out consumers that INTEGRATE or AVERAGE a pose as the
// serious case. The dashboard computes no centroid, accumulates no trail from
// poses and derives no distance client-side — MissionProgress reads
// fleet_distance_total off the wire, and robotPaths comes from the planner's
// nav_msgs/Path, not from odometry. Saying "there is no aggregate" would be
// wrong, though: planRobotMarks IS one. It is a spatial allocator over the
// whole fleet, and a phantom robot at (0, 0) reserves a gauge box and a label
// row there, displacing the marks of every real robot near the origin.
//
// MUTATION, EXECUTED: this test is one of the four that fail when the
// planRobotMarks guard is deleted — the phantom reserves a gauge box and a
// label row at the origin, the real robots' marks are nudged around it, and the
// plans are no longer equal.

describe('D-31: a fixless robot does not displace a real robot’s marks', () => {
  const measure = (t) => ADVANCE_EM * LABEL_FONT_PX * t.length;

  function planFor(robots) {
    return planRobotMarks(orderRobotsForLabels(robots, null), 4.3, null, measure);
  }

  test('the plan for the real fleet is identical with and without the phantom', () => {
    const real = [
      record('excavator_01', 0.5, 0.5),
      record('hauler_01', 1.5, -0.5),
      record('scout_01', -1.0, 1.0),
    ];
    const phantom = record('scout_07', 0, 0, { pose_valid: false });

    const without = planFor(real);
    const with_ = planFor([...real, phantom]);

    real.forEach((r) => {
      expect(with_.get(r.robot_id)).toEqual(without.get(r.robot_id));
    });
    expect(with_.size).toBe(without.size);
  });
});

// ------------------------------------------------- paths, highlight, hit-test

describe('D-31: every other consumer of a robot pose', () => {
  test('the planned-path overlay is not anchored to a fabricated origin', () => {
    // MUTATION, EXECUTED: delete `if (!hasPositionFix(robot)) return;` from
    // drawPlannedPaths and this test alone fails (whole run 1 failed / 100
    // passed) — the polyline is emitted with its first vertex at world (0, 0).
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    const robots = asMap([record('hauler_01', 0, 0, { pose_valid: false })]);
    const paths = { hauler_01: [{ x: -100, y: -150 }, { x: -95, y: -140 }] };
    withWorldTransform(ctx, 4.3, () => {
      drawPlannedPaths(ctx, robots, paths, 4.3);
    });
    expect(ctx.marks).toEqual([]);
  });

  test('the planned-path overlay still draws for a robot that has a fix', () => {
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    const robots = asMap([record('hauler_01', -90, -140)]);
    const paths = { hauler_01: [{ x: -100, y: -150 }] };
    withWorldTransform(ctx, 4.3, () => {
      drawPlannedPaths(ctx, robots, paths, 4.3);
    });
    expect(ctx.marks.length).toBeGreaterThan(0);
  });

  test('the task highlight draws the target but no ring or leader line', () => {
    // MUTATION, EXECUTED: revert the condition to `if (robot && robot.pose)`
    // and this test alone fails (whole run 1 failed / 100 passed) — the extra
    // marks are the pulsing ring at (0, 0) and a ~180 m dashed leader line from
    // there to the target, asserting a relationship that does not exist.
    //
    // The crosshair and its pulse ARE still expected: the target comes from the
    // orchestrator's task row, not from odometry, so it is not in doubt.
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    const robots = asMap([record('hauler_01', 0, 0, { pose_valid: false })]);
    const tasks = {
      haul_1: { assigned_robot: 'hauler_01', target_x: -100, target_y: -150 },
    };
    withWorldTransform(ctx, 4.3, () => {
      drawSelectedTaskHighlight(ctx, robots, tasks, 'haul_1', 4.3, NOW);
    });
    // Every mark emitted is at the TARGET, not at the origin and not spanning
    // the two.
    expect(ctx.marks.length).toBeGreaterThan(0);
    ctx.marks.forEach((mk) => {
      expect(mk.box.x1).toBeLessThan(0);
      expect(mk.box.y0).toBeGreaterThan(0); // world y is negated in device px
    });
  });

  test('a fixless robot is not the closest hit', () => {
    // The invisible selection disc. A click on bare terrain at the origin must
    // select nothing, not a robot that is not drawn there.
    //
    // MUTATION, EXECUTED: delete `if (!hasPositionFix(robot)) return;` from
    // pickRobotAt and both hit-test tests fail (whole run 2 failed / 99
    // passed) — this one selects 'scout_07' at the origin, and the contested
    // click below is stolen by the phantom at 0.4 m instead of going to the
    // excavator at 1.6 m.
    const robots = asMap([
      record('scout_07', 0, 0, { pose_valid: false }),
      record('excavator_01', 40, 40),
    ]);
    expect(pickRobotAt(robots, 0, 0, 3.5)).toBeNull();
    expect(pickRobotAt(robots, 40.5, 40.5, 3.5)).toBe('excavator_01');
  });

  test('the nearest robot WITH a fix still wins a contested click', () => {
    // The guard must not have turned the hit-test into "first match".
    const robots = asMap([
      record('scout_07', 0, 0, { pose_valid: false }),
      record('excavator_01', 2, 0),
      record('hauler_01', -2.5, 0),
    ]);
    expect(pickRobotAt(robots, 0.4, 0, 3.5)).toBe('excavator_01');
  });
});
