/**
 * ADD_RESOURCE_READING — identity, eviction and rejection.
 *
 * Two properties, both of which the reducer used to lack entirely. The case was
 * three lines: prepend `action.payload`, pop past the cap, done.
 *
 * IDENTITY. A reading had no name. ResourceGraph joined its simulation nodes and
 * the operator's selection to readings by ARRAY POSITION, and this array
 * prepends, so every arrival moved both onto a different sample. `clientSeq` is
 * the fix, and it is carried across a RESET for exactly the reason
 * `resourceMapRevision` is (D-15): re-issuing key 1 for a new backend session is
 * the same collision, one layer up — anything still holding key 1 from the dead
 * session would silently re-bind to an unrelated sample instead of resolving to
 * nothing.
 *
 * VALIDATION. UPDATE_RESOURCE_MAP has rejected degenerate input since D-02 with
 * the reason stated in one line — "a canvas draws NaN as nothing at all" — while
 * this sibling case accepted anything at all, and App.jsx projected the message
 * inside the roslib callback with an unguarded `msg.location.x`. A single
 * non-finite ice_concentration puts a permanent "NaN wt%" in the stats panel,
 * because Peak and Avg are reductions over the whole array and nothing evicts a
 * bad sample except the 500-cap.
 *
 * MUTATION RUN: restoring the pre-fix three-line case
 *   const readings = [action.payload, ...state.resourceReadings];
 *   if (readings.length > MAX_READINGS) readings.pop();
 *   return { ...state, resourceReadings: readings };
 * gives 14 failed / 1 passed here. The one survivor —
 * 'a concentration outside the 0-10 display scale is accepted' — is a
 * CHARACTERIZATION PIN: the pre-fix reducer accepted everything, so of course it
 * accepted that too. It is committed because the rule it pins is a decision
 * (range is a display convention, not a wire contract) that a later tightening
 * pass would otherwise be free to get wrong in the name of validation.
 *
 * NOT A RENDERING TEST. Nothing here draws.
 */

import { fleetReducer, initialState } from '../hooks/useFleetState';

// The raw ResourceMapUpdate shape, as roslib delivers it.
function wireMsg(overrides = {}) {
  return {
    scout_id: 'scout_01',
    location: { x: -100.5, y: -150.25 },
    ice_concentration: 6.25,
    sensor_uncertainty: 0.5,
    stamp: { sec: 1000, nanosec: 0 },
    ...overrides,
  };
}

const add = (state, msg) => fleetReducer(state, { type: 'ADD_RESOURCE_READING', payload: msg });
const reset = (state) => fleetReducer(state, { type: 'RESET' });

test('the four wire fields pass through unchanged and clientSeq is additive', () => {
  const state = add(initialState, wireMsg());
  const r = state.resourceReadings[0];
  expect(r.scout_id).toBe('scout_01');
  expect(r.location).toEqual({ x: -100.5, y: -150.25 });
  expect(r.ice_concentration).toBe(6.25);
  expect(r.sensor_uncertainty).toBe(0.5);
  expect(r.clientSeq).toBe(1);
});

test('clientSeq is strictly increasing and never re-issued across five sessions', () => {
  let state = initialState;
  const seen = new Set();
  let previous = 0;
  for (let session = 0; session < 5; session += 1) {
    for (let i = 0; i < 4; i += 1) {
      state = add(state, wireMsg({ ice_concentration: session + i }));
      const { clientSeq } = state.resourceReadings[0];
      expect(seen.has(clientSeq)).toBe(false);
      expect(clientSeq).toBeGreaterThan(previous);
      previous = clientSeq;
      seen.add(clientSeq);
    }
    state = reset(state);
  }
  expect(seen.size).toBe(20);
});

test('RESET clears the readings but carries the identity counter forward', () => {
  let state = add(initialState, wireMsg());
  state = add(state, wireMsg());
  expect(state.resourceReadingSeq).toBe(2);

  state = reset(state);
  // The dead session's samples are gone...
  expect(state.resourceReadings).toEqual([]);
  // ...but the key supply is not session data.
  expect(state.resourceReadingSeq).toBe(2);

  state = add(state, wireMsg());
  expect(state.resourceReadings[0].clientSeq).toBe(3);
});

test('the 500 cap evicts the OLDEST reading', () => {
  let state = initialState;
  for (let i = 0; i < 505; i += 1) {
    state = add(state, wireMsg({ ice_concentration: i % 10 }));
  }
  expect(state.resourceReadings).toHaveLength(500);
  // Newest first, so index 0 is the last arrival and the tail is the oldest
  // survivor. Asserted on clientSeq rather than on payload contents, which
  // repeat every ten messages.
  expect(state.resourceReadings[0].clientSeq).toBe(505);
  expect(state.resourceReadings[499].clientSeq).toBe(6);
  expect(state.resourceReadingSeq).toBe(505);
});

describe('malformed readings are rejected, counted, and consume no identity', () => {
  const bad = {
    'a non-finite concentration': wireMsg({ ice_concentration: NaN }),
    'an infinite concentration': wireMsg({ ice_concentration: Infinity }),
    // The producer already drops sigma <= 0 or non-finite
    // (selene_agent/selene_agent/agent_node.py:1349-1369), so one arriving here
    // means something upstream of the agent's own filter is wrong.
    'a zero sigma': wireMsg({ sensor_uncertainty: 0 }),
    'a negative sigma': wireMsg({ sensor_uncertainty: -0.5 }),
    'a non-finite sigma': wireMsg({ sensor_uncertainty: NaN }),
    'a missing location': wireMsg({ location: undefined }),
    'a location with a non-numeric x': wireMsg({ location: { x: 'nope', y: 1 } }),
    'a location with a NaN y': wireMsg({ location: { x: 1, y: NaN } }),
    'a null message': null,
  };

  Object.entries(bad).forEach(([label, msg]) => {
    test(label, () => {
      // One good reading first, so "rejected" is distinguishable from "the
      // reducer does nothing at all".
      let state = add(initialState, wireMsg());
      expect(state.resourceReadings).toHaveLength(1);

      state = add(state, msg);
      expect(state.resourceReadings).toHaveLength(1);
      expect(state.resourceReadingsDropped).toBe(1);
      // A rejected message must not burn a key, or gaps in the sequence would
      // stop meaning "this reading was evicted".
      expect(state.resourceReadingSeq).toBe(1);

      state = add(state, wireMsg());
      expect(state.resourceReadings[0].clientSeq).toBe(2);
    });
  });
});

test('a concentration outside the 0-10 display scale is accepted, not dropped', () => {
  // The 0-10 wt% figure the node radius and the colour law assume is a DISPLAY
  // convention; ResourceMapUpdate.msg declares a bare float32. Clamping belongs
  // to the renderer — a 40 wt% reading should draw at the top of the scale and
  // be visible, not be discarded by the reducer.
  const state = add(initialState, wireMsg({ ice_concentration: 40.0 }));
  expect(state.resourceReadings).toHaveLength(1);
  expect(state.resourceReadings[0].ice_concentration).toBe(40.0);
  expect(state.resourceReadingsDropped).toBe(0);
});

test('the drop counter is per-session and RESET clears it', () => {
  let state = add(initialState, wireMsg({ ice_concentration: NaN }));
  expect(state.resourceReadingsDropped).toBe(1);
  state = reset(state);
  // Unlike the identity counter above: a count spanning sessions could not
  // answer "is the CURRENT backend sending me garbage", which is the only
  // question it exists to answer.
  expect(state.resourceReadingsDropped).toBe(0);
});
