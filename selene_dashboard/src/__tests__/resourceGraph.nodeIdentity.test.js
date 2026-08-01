/**
 * A NODE MUST BELONG TO ITS OWN READING — and so must the operator's selection.
 *
 * `state.resourceReadings` PREPENDS: the newest sample is index 0 and everything
 * else shifts down by one on every arrival. `ResourceGraph` used to join its
 * simulation nodes to that array by COUNTING — it tracked the previous length,
 * treated the delta as "how many were prepended", and in the branch where the
 * length had not changed it re-pointed `nodes[i].reading = readings[i]` by index.
 * Two independent failures follow, and neither is visible in a rendering test
 * because the picture stays plausible:
 *
 *   AT THE 500-READING CAP the length stops changing while the contents keep
 *   shifting, so the "unchanged" branch ran on every arrival and every node
 *   quietly adopted a DIFFERENT reading while keeping its settled position. Node
 *   size, colour and tooltip then described a sample that is somewhere else.
 *
 *   AT THE 499->500 TRANSITION with two readings landing in one commit, the
 *   delta is 1 while two were prepended, so the association is off by one until
 *   the next arrival happens to re-sync it.
 *
 * Separately, hover and selection were POSITIONAL indices into the same
 * prepending array, so the white selection ring and the cyan "connected to
 * selected" edges jumped to a different reading every time any scout finished a
 * waypoint, with no operator action at all.
 *
 * The repair is `reconcileNodes`, which rebuilds the table by the reducer-minted
 * `clientSeq` and therefore makes `nodes[i].reading === readings[i]` a
 * CONSTRUCTED invariant rather than a maintained one. Everything below asserts
 * that invariant against the REAL reducer, with no rendering anywhere.
 *
 * MUTATIONS RUN, because "an invariant holds" is easy to assert vacuously and
 * two different wrong algorithms fail it in two different places:
 *
 *   (i)  reconcileNodes matching by INDEX (`prevNodes[idx]`) — 3 failed / 4:
 *        'a settled node keeps its position', 'at the 500 cap ...', 'a reading
 *        with no clientSeq ...'.
 *   (ii) reconcileNodes replaced by the pre-fix COUNT-BASED algorithm (delta in
 *        array length, plus the index re-point when the length is unchanged) —
 *        3 failed / 4: 'at the 500 cap ...', 'two readings landing in one
 *        reconcile step ...', 'a reading with no clientSeq ...'.
 *
 * 'every node points at its own reading after each of twelve arrivals' passes
 * under BOTH mutations and is therefore a CHARACTERIZATION PIN of the steady
 * state, not a regression test — index matching and counting both satisfy it
 * while getting the cap and the position wrong. It is kept because it is the
 * statement of the invariant everything else is a corner of. The edge-scale test
 * at the bottom is likewise a rot-check, not a regression test.
 */

import { computeEdges, reconcileNodes } from '../components/ResourceGraph';
import { fleetReducer, initialState } from '../hooks/useFleetState';

// A deterministic stand-in for Math.random. reconcileNodes only uses it for
// placement, and placement is not what is under test — pinning it just keeps
// failures reproducible.
function seededRand(seed = 12345) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

const rand = seededRand();

// The raw ResourceMapUpdate shape App.jsx now dispatches unmodified.
function wireMsg(i) {
  return {
    scout_id: i % 2 === 0 ? 'scout_01' : 'scout_02',
    location: { x: -100 + (i % 17), y: -150 + (i % 13) },
    ice_concentration: 1 + (i % 9),
    sensor_uncertainty: 0.5,
  };
}

const arrive = (state, i) => fleetReducer(
  state, { type: 'ADD_RESOURCE_READING', payload: wireMsg(i) },
);

// What the component's effect does around reconcileNodes: centroid of the
// existing nodes, or the canvas centre on a cold start.
function reconcileStep(prevNodes, readings) {
  let cx = 400;
  let cy = 300;
  if (prevNodes.length > 0) {
    cx = prevNodes.reduce((s, n) => s + n.x, 0) / prevNodes.length;
    cy = prevNodes.reduce((s, n) => s + n.y, 0) / prevNodes.length;
  }
  return reconcileNodes(prevNodes, readings, cx, cy, rand);
}

function expectInvariant(nodes, readings) {
  expect(nodes).toHaveLength(readings.length);
  for (let i = 0; i < readings.length; i += 1) {
    // Object identity, not deep equality: the point is that this node IS that
    // reading's node, and deep equality would pass on two identical samples.
    expect(nodes[i].reading).toBe(readings[i]);
  }
}

test('every node points at its own reading after each of twelve arrivals', () => {
  let state = initialState;
  let nodes = [];
  for (let i = 0; i < 12; i += 1) {
    state = arrive(state, i);
    nodes = reconcileStep(nodes, state.resourceReadings);
    expectInvariant(nodes, state.resourceReadings);
  }
});

test('a settled node keeps its position and velocity when a new reading arrives', () => {
  let state = arrive(initialState, 0);
  state = arrive(state, 1);
  let nodes = reconcileStep([], state.resourceReadings);

  // Let the force simulation "settle" them somewhere non-trivial.
  nodes.forEach((n, i) => {
    n.x = 100 + i * 37;
    n.y = 200 - i * 11;
    n.vx = 0.5;
    n.vy = -0.25;
  });
  const watched = nodes[0];
  const watchedReading = watched.reading;
  const snapshot = { x: watched.x, y: watched.y, vx: watched.vx, vy: watched.vy };

  state = arrive(state, 2);
  nodes = reconcileStep(nodes, state.resourceReadings);

  // It was at index 0 and is now at index 1, because the array prepends.
  expect(state.resourceReadings[1]).toBe(watchedReading);
  expect(nodes[1]).toBe(watched);
  expect(nodes[1]).toMatchObject(snapshot);
  expectInvariant(nodes, state.resourceReadings);
});

test('at the 500 cap the evicted reading loses its node instead of donating it', () => {
  let state = initialState;
  let nodes = [];
  for (let i = 0; i < 504; i += 1) {
    state = arrive(state, i);
    nodes = reconcileStep(nodes, state.resourceReadings);
  }
  expect(state.resourceReadings).toHaveLength(500);

  // THE DEFECT, at the length where it fires. The array is full, so the next
  // arrival does not change its LENGTH — it only shifts the contents by one and
  // pops the tail. The count-based version saw a delta of zero, concluded
  // nothing had been added, and re-pointed node[i].reading = readings[i] by
  // index: every node kept its settled position, size and colour while silently
  // adopting the neighbouring sample. Pick a node in the middle, give it a
  // recognisable position, and require that the SAME OBJECT still carries the
  // SAME reading afterwards.
  const watched = nodes[250];
  const watchedReading = watched.reading;
  watched.x = 4242.5;
  watched.y = -1717.25;

  state = arrive(state, 504);
  nodes = reconcileStep(nodes, state.resourceReadings);

  const moved = nodes.find((n) => n.reading === watchedReading);
  expect(moved).toBe(watched);
  expect(moved.x).toBe(4242.5);
  expect(moved.y).toBe(-1717.25);
  // It slid one place further from the head, and its node came with it.
  expect(nodes[251]).toBe(watched);

  expect(state.resourceReadings).toHaveLength(500);
  expect(nodes).toHaveLength(500);
  expectInvariant(nodes, state.resourceReadings);

  // clientSeq 1..5 were evicted by the cap. No surviving node may still be
  // carrying one of them, and no node object may have been recycled onto a
  // different reading — that recycling IS the defect.
  const liveKeys = new Set(state.resourceReadings.map((r) => r.clientSeq));
  expect(liveKeys.has(1)).toBe(false);
  expect(liveKeys.has(505)).toBe(true);
  nodes.forEach((n) => {
    expect(liveKeys.has(n.reading.clientSeq)).toBe(true);
  });
  // Every node holds a distinct reading. Under the index-based re-point this
  // could be true while every pairing was wrong, so it is a supporting check,
  // not the assertion.
  expect(new Set(nodes.map((n) => n.reading.clientSeq)).size).toBe(500);
});

test('two readings landing in one reconcile step at the cap keep the invariant', () => {
  let state = initialState;
  let nodes = [];
  // Fill to 499 with one reconcile per arrival, the steady-state path.
  for (let i = 0; i < 499; i += 1) {
    state = arrive(state, i);
    nodes = reconcileStep(nodes, state.resourceReadings);
  }
  expect(state.resourceReadings).toHaveLength(499);

  // Now two dispatches before the effect gets a chance to run — a single React
  // commit carrying two messages. The length goes 499 -> 500, a delta of one,
  // while TWO were prepended: the exact off-by-one the count-based version had.
  state = arrive(state, 499);
  state = arrive(state, 500);
  expect(state.resourceReadings).toHaveLength(500);

  nodes = reconcileStep(nodes, state.resourceReadings);
  expectInvariant(nodes, state.resourceReadings);
});

test('a selection held by clientSeq survives an arrival; a positional one does not', () => {
  let state = initialState;
  for (let i = 0; i < 5; i += 1) state = arrive(state, i);

  // The operator clicks the node at index 2.
  const clickedIdx = 2;
  const clicked = state.resourceReadings[clickedIdx];
  const selectedSeq = clicked.clientSeq;

  state = arrive(state, 99);

  const resolvedIdx = state.resourceReadings.findIndex((r) => r.clientSeq === selectedSeq);
  expect(state.resourceReadings[resolvedIdx]).toBe(clicked);

  // The same index now names a different sample. This is the assertion that
  // fails if selection ever goes back to being positional.
  expect(state.resourceReadings[clickedIdx]).not.toBe(clicked);
  expect(resolvedIdx).toBe(clickedIdx + 1);
});

test('a reading with no clientSeq gets a fresh node rather than matching another', () => {
  // Not reachable through the reducer, which always mints a key. It is asserted
  // so that a future producer bypassing the reducer degrades by losing position
  // stability (cosmetic) instead of by mis-binding data (the defect above).
  const unkeyed = [
    { location: { x: 0, y: 0 }, ice_concentration: 1, sensor_uncertainty: 0.5 },
    { location: { x: 1, y: 1 }, ice_concentration: 2, sensor_uncertainty: 0.5 },
  ];
  const first = reconcileNodes([], unkeyed, 0, 0, rand);
  const second = reconcileNodes(first, unkeyed, 0, 0, rand);

  expectInvariant(second, unkeyed);
  expect(second[0]).not.toBe(first[0]);
  expect(second[1]).not.toBe(first[1]);
});

/**
 * A ROT-CHECK, not a behaviour test.
 *
 * The edge cap and its on-screen note ("Showing the N strongest-similarity links
 * only") were written against a 16,751-edge hairball at the 500-reading cap.
 * The SHIPPED mission cannot produce one: the HTN planner caps a survey at
 * SURVEY_WAYPOINT_COUNT = 10 waypoints (selene_orchestrator/selene_orchestrator/
 * htn_planner.py:42), each prospect completion publishes exactly one
 * ResourceMapUpdate, and the adaptive planner never creates or deletes a task.
 * The ten points below are the literal output of
 *   selene_orchestrator.htn_planner._generate_survey_waypoints((-100, -150), 60)
 * executed against the repository on 2026-07-31.
 *
 * So MAX_DRAWN_EDGES = 900 and MAX_READINGS = 500 are both unreachable on the
 * shipped survey and the capped-edges note can never render. That is recorded
 * here as an executable fact rather than as a comment, so if anyone raises
 * SURVEY_WAYPOINT_COUNT this test says so instead of the cap silently starting
 * to bite. A requeued or retried survey publishes again, so the real number is
 * 10-15 rather than exactly 10; the conclusion survives an order of magnitude of
 * slack, the exact figure does not.
 */
test('the shipped ten-waypoint survey produces 18 edges, far under the 900 cap', () => {
  const waypoints = [
    [-105.0, -153.03847577293368],
    [-95.0, -135.71796769724492],
    [-85.0, -153.03847577293368],
    [-115.0, -135.71796769724492],
    [-95.0, -170.35898384862247],
    [-125.0, -153.03847577293368],
    [-115.0, -170.35898384862247],
    [-75.0, -135.71796769724492],
    [-105.0, -118.39745962155615],
    [-75.0, -170.35898384862247],
  ];
  const readings = waypoints.map(([x, y], i) => ({
    scout_id: 'scout_01',
    location: { x, y },
    ice_concentration: 1 + (i % 9),
    sensor_uncertainty: 0.5,
    clientSeq: i + 1,
  }));

  const { edges, totalCandidates } = computeEdges(readings);
  expect(totalCandidates).toBe(18);
  expect(edges).toHaveLength(totalCandidates);

  // Every edge indexes a node that reconcileNodes actually built — the
  // precondition the render loop used to violate under the race.
  const nodes = reconcileNodes([], readings, 400, 300, rand);
  edges.forEach((e) => {
    expect(nodes[e.i]).toBeDefined();
    expect(nodes[e.j]).toBeDefined();
  });
});
