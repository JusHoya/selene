/**
 * D-15 — the heatmap raster cache key must be unique for the browser tab.
 *
 * `FleetMap.buildPosteriorRaster` skips the rebuild when
 * `store.revision === map.revision`, and its store is a `useRef` that survives
 * a rosbridge reconnect (App.jsx renders FleetMap with no connection-keyed
 * `key`). The revision used to be counted off `state.resourceMap`, which
 * `case 'RESET'` nulls — so the first snapshot of a new backend session came
 * back as revision 1, matched a store still holding revision 1 from the DEAD
 * session, and the rebuild was skipped. A restarted orchestrator with an empty
 * map rendered as a fully surveyed one for up to one publish period, while
 * ResourceLegend already reported the new snapshot's counts.
 *
 * The regression test is the second assertion in the first case below: with the
 * counter reset by RESET it reads 1, twice, and the raster's `===` cannot tell
 * the two sessions apart.
 *
 * NOT A RENDERING TEST. Nothing here draws. It asserts the property the raster
 * cache depends on, which is the property that was false.
 */

import { fleetReducer, initialState } from '../hooks/useFleetState';

// A minimal well-formed ResourceMap that UPDATE_RESOURCE_MAP will accept. The
// reducer rejects a snapshot whose four parallel arrays disagree in length or
// whose geometry is degenerate, so this has to be complete.
function snapshot(cells = [0]) {
  return {
    resolution: 1.0,
    width: 500,
    height: 500,
    origin: { x: -250, y: -250 },
    prior_mean: 0.0,
    prior_variance: 100.0,
    total_observations: cells.length,
    cell_index: cells,
    cell_mean: cells.map(() => 3.5),
    cell_variance: cells.map(() => 0.25),
    cell_observation_count: cells.map(() => 1),
  };
}

const accept = (state, cells) => fleetReducer(
  state, { type: 'UPDATE_RESOURCE_MAP', payload: snapshot(cells) },
);
const reset = (state) => fleetReducer(state, { type: 'RESET' });

test('a reconnect does not re-issue a revision the raster has already cached', () => {
  // Exactly one snapshot rasterised before the drop — the case that collides.
  let state = accept(initialState, [10, 11]);
  const beforeDrop = state.resourceMap.revision;

  state = reset(state);
  expect(state.resourceMap).toBeNull();

  state = accept(state, [4000, 4001, 4002]);
  const afterReconnect = state.resourceMap.revision;

  expect(afterReconnect).not.toBe(beforeDrop);
  expect(afterReconnect).toBeGreaterThan(beforeDrop);
});

test('no revision is ever issued twice over many sessions', () => {
  let state = initialState;
  const seen = new Set();
  for (let session = 0; session < 5; session += 1) {
    for (let msg = 0; msg < 4; msg += 1) {
      state = accept(state, [session * 100 + msg]);
      const { revision } = state.resourceMap;
      expect(seen.has(revision)).toBe(false);
      seen.add(revision);
    }
    state = reset(state);
  }
  expect(seen.size).toBe(20);
});

test('RESET clears the map itself but carries the counter forward', () => {
  let state = accept(initialState, [1, 2, 3]);
  expect(state.resourceMapRevision).toBe(1);
  state = reset(state);
  // Everything that belongs to the dead session is gone...
  expect(state.resourceMap).toBeNull();
  expect(state.tasksById).toEqual({});
  expect(state.robots).toEqual({});
  // ...but the cache key is not session data and is deliberately kept.
  expect(state.resourceMapRevision).toBe(1);
});

test('a rejected snapshot does not consume a revision', () => {
  // Parallel arrays disagreeing in length: ResourceMap.msg requires a consumer
  // to reject the message. A rejected snapshot leaves the previous map standing
  // and must not advance the key, or the raster would rebuild from a map it
  // already holds.
  let state = accept(initialState, [7]);
  const before = state.resourceMap.revision;
  const bad = snapshot([7, 8]);
  bad.cell_variance = [0.25];
  state = fleetReducer(state, { type: 'UPDATE_RESOURCE_MAP', payload: bad });
  expect(state.resourceMapDropped).toBe(1);
  expect(state.resourceMap.revision).toBe(before);
  expect(state.resourceMapRevision).toBe(before);
});

test('the operator preferences RESET preserves are unchanged by this', () => {
  let state = fleetReducer(initialState, { type: 'TOGGLE_HEATMAP' });
  state = fleetReducer(state, { type: 'SET_SELECTED_ROBOT', payload: 'scout_01' });
  state = accept(state, [1]);
  state = reset(state);
  expect(state.heatmapVisible).toBe(false);
  expect(state.selectedRobotId).toBe('scout_01');
});
