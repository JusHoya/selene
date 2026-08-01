/**
 * A CHARACTERIZATION PIN, NOT A REGRESSION TEST — say so out loud.
 *
 * Every assertion in this file passes against the reducer as it stood before
 * D-34, unmodified. Nothing here can fail without a fix because nothing here
 * needed fixing. It is committed anyway, and the reason is specific.
 *
 * D-34 removes `throttle_rate: 500` from the ROBOT_STATE subscription in
 * App.jsx, because that rosbridge server-side limit re-aliased the topic at
 * exactly 2 Hz and would have DROPPED the FSM-transition samples the agent now
 * publishes — making an agent-side fix invisible to the browser. Removing it
 * means this reducer starts seeing a HIGHER and IRREGULAR sample rate, including
 * repeats of a state it has already recorded (a timer tick immediately following
 * a transition publish carries an identical fsm_state, and within one 20 Hz
 * odometry period an identical pose too).
 *
 * `UPDATE_ROBOT` already handles that correctly: `stateHistory` is appended only
 * when `prev.fsm_state !== msg.fsm_state`. That property is currently implicit —
 * one `if` with no test behind it — and the throttle removal makes something
 * depend on it that did not before. Pinning it is what stops a later "simplify
 * the reducer" pass from turning the un-throttled feed into a duplicated
 * transition log.
 *
 * The mutation that proves this file bites, EXECUTED: replace
 * `if (prev && prev.fsm_state !== msg.fsm_state)` with `if (prev)` in
 * UPDATE_ROBOT and this suite goes 3 failed / 2 passed — 'repeated samples of
 * the same state add nothing', 'a transition sample followed immediately by a
 * timer tick', and 'an unthrottled feed does not multiply the recorded
 * transitions'. That is a mutation of the CURRENT code. It is evidence the tests
 * are wired to the property, NOT evidence the property was ever broken.
 */

import { fleetReducer, initialState } from '../hooks/useFleetState';

function robotMsg(fsmState, overrides = {}) {
  return {
    robot_id: 'scout_01',
    robot_type: 'scout',
    fsm_state: fsmState,
    pose: { x: -100, y: -150, theta: 0.5 },
    velocity: { linear: { x: 0.2 }, angular: { z: 0 } },
    battery_level: 0.83,
    battery_capacity_wh: 50.0,
    current_task_id: '',
    task_progress: 0.0,
    capabilities: ['prospect'],
    pose_valid: true,
    ...overrides,
  };
}

const update = (state, msg) => fleetReducer(state, { type: 'UPDATE_ROBOT', payload: msg });
const historyOf = (state) => state.robots.scout_01.stateHistory;

test('repeated samples of the same state add nothing to the history', () => {
  let state = update(initialState, robotMsg('NAVIGATING'));
  // The very first sample records no edge — there is no previous state to
  // come from — which is why the length is 0 rather than 1 here.
  expect(historyOf(state)).toHaveLength(0);

  for (let i = 0; i < 10; i += 1) {
    state = update(state, robotMsg('NAVIGATING'));
  }
  expect(historyOf(state)).toHaveLength(0);
});

test('both edges of a three-state hand-off are recorded, in order', () => {
  // The D-34 sequence: a cancel drops the robot to IDLE for 0.247 s before the
  // next auction picks it up. Under the 500 ms rosbridge throttle that middle
  // sample could be dropped even when the agent published it, and the history
  // would then show a single NAVIGATING -> BIDDING edge that never happened.
  let state = update(initialState, robotMsg('NAVIGATING'));
  state = update(state, robotMsg('IDLE'));
  state = update(state, robotMsg('BIDDING'));

  const history = historyOf(state);
  expect(history).toHaveLength(2);
  // Newest first (the reducer unshifts).
  expect(history[0]).toMatchObject({ from: 'IDLE', to: 'BIDDING' });
  expect(history[1]).toMatchObject({ from: 'NAVIGATING', to: 'IDLE' });
});

test('a transition sample followed immediately by a timer tick records one edge', () => {
  // Exactly what the agent emits after D-34 Part A: the on-change publish, then
  // the next 0.5 s timer tick carrying the identical state.
  let state = update(initialState, robotMsg('WORKING'));
  state = update(state, robotMsg('RETURNING'));
  state = update(state, robotMsg('RETURNING'));
  expect(historyOf(state)).toHaveLength(1);
});

test('the history is capped and keeps the most recent transitions', () => {
  const states = ['IDLE', 'BIDDING', 'ASSIGNED', 'NAVIGATING', 'WORKING', 'RETURNING'];
  let state = update(initialState, robotMsg('IDLE'));
  for (let i = 1; i <= 40; i += 1) {
    state = update(state, robotMsg(states[i % states.length]));
  }
  const history = historyOf(state);
  // MAX_HISTORY is 20 in the reducer.
  expect(history).toHaveLength(20);
  expect(history[0].to).toBe(states[40 % states.length]);
});

test('an unthrottled feed does not multiply the recorded transitions', () => {
  // The property the throttle removal actually depends on, stated as a ratio:
  // four transitions interleaved with any number of repeat samples still give
  // four edges.
  const script = ['IDLE', 'BIDDING', 'ASSIGNED', 'NAVIGATING', 'WORKING'];
  let state = initialState;
  script.forEach((s) => {
    for (let i = 0; i < 7; i += 1) {
      state = update(state, robotMsg(s));
    }
  });
  expect(historyOf(state)).toHaveLength(script.length - 1);
});
