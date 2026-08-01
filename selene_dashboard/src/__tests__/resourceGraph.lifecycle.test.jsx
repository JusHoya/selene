/**
 * THE RESOURCE KNOWLEDGE MAP'S RENDER LOOP — lifecycle, not pixels.
 *
 * THE DEFECT THIS PINS. The operator's report was "the knowledge map does not
 * work": open the view, wait, and the header, legend and stats panel fill with
 * real numbers over a black rectangle that never draws. The cause was not in the
 * drawing code at all. `ResourceGraph` took an empty-state early return while
 * `readings.length === 0` — the state the app is in on EVERY page load, because
 * the reducer initialises `resourceReadings` to `[]` — and that branch rendered
 * no <canvas> and attached no container ref. All three canvas effects therefore
 * ran against null refs and bailed, and their dependency arrays
 * (`[updateCanvasSize]`, `[]`, `[handleWheel]`) could never change again. When
 * readings finally arrived and the canvas mounted, NOTHING RE-RAN: the loop was
 * never scheduled and the canvas kept its default 300x150 backing store.
 *
 * The second trigger is a rosbridge reconnect: RESET empties `resourceReadings`,
 * the canvas unmounts, and when readings resume React mounts a NEW canvas while
 * the loop keeps drawing into the detached element it captured on first commit.
 *
 * The third is that ONE uncaught throw inside the frame was permanently fatal,
 * because the re-schedule was the last statement of the loop body.
 *
 * WHAT THIS FILE CAN AND CANNOT DO. It runs the REAL component under real React
 * 18 in jsdom, so the commit ordering, the ref attachment and the effect
 * dependency arrays are the shipped ones. jsdom does not rasterise: there is no
 * 2D context, no layout and no paint (see src/testUtils/rafHarness.js for the
 * four shims that stand in and exactly what each models). So every assertion
 * here is about SCHEDULING and ELEMENT IDENTITY — "a frame was requested", "the
 * frame landed on the canvas that is in the DOM", "the canvas got a real backing
 * store". None of it is evidence that the view is legible or that the marks are
 * in the right place. Only opening it in Chrome against a live backend is, and
 * that has not been done for this repair.
 *
 * MUTATION RUN, so the split between regression test and guard is on the record
 * rather than asserted. Restoring the pre-repair ResourceGraph.jsx (the file at
 * commit ff80ed1) under this suite unchanged gives 4 failed / 3 passed:
 *   FAIL  readings arriving while the view is already open
 *   FAIL  a canvas that mounts after the first commit gets a real backing store
 *   FAIL  after an empty -> non-empty cycle ... the canvas in the DOM
 *   FAIL  a throw inside the frame is survivable
 *   PASS  CONTROL (by design — it attributes a harness failure)
 *   PASS  a re-render with the same readings does not start a second loop
 *   PASS  unmounting cancels the pending frame
 * The last two are GUARDS ON THE REPAIR, not regression tests: they pass before
 * and after, and exist because keying the loop on element identity introduces a
 * new way to be wrong (a loop restarted on every render) that the old code could
 * not have.
 */

// `act` from 'react', not from 'react-dom/test-utils': React 18.3.1 warns on
// every call to the latter, which would put a console.error flood in front of
// the one console.error this suite deliberately asserts on.
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import ResourceGraph from '../components/ResourceGraph';
import { installCanvasLoopHarness } from '../testUtils/rafHarness';

const BOX_W = 800;
const BOX_H = 600;

// Frames must advance by at least FRAME_INTERVAL (1000/30 ms) or the loop's own
// throttle skips the draw — which is correct behaviour and not what is under
// test, so every pump below steps 100 ms.
const FRAME_STEP = 100;

let harness;
let host;
let root;

function reading(clientSeq, x, y, ice = 5.0) {
  return {
    scout_id: 'scout_01',
    location: { x, y },
    ice_concentration: ice,
    sensor_uncertainty: 0.5,
    clientSeq,
  };
}

const THREE = [reading(3, -100, -150, 6.1), reading(2, -110, -155, 2.4), reading(1, -95, -140, 8.0)];

function render(props) {
  act(() => {
    root.render(<ResourceGraph onClose={() => {}} {...props} />);
  });
}

function canvasNow() {
  return host.querySelector('canvas');
}

/** clearRect calls recorded against `el`'s own context, 0 if it never asked. */
function drawsOn(el) {
  const ctx = el ? harness.canvases.contextFor(el) : undefined;
  return ctx ? ctx.clearRects : 0;
}

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  harness = installCanvasLoopHarness({ width: BOX_W, height: BOX_H });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  harness.restore();
  delete global.IS_REACT_ACT_ENVIRONMENT;
});

// (1) CONTROL. This one passed before the repair as well as after, and it is
// here so a failure elsewhere in the file can be attributed: if this goes red
// the harness is broken, not the component. Without the layout shim it recorded
// zero draws for the wrong reason (the loop bails on a zero-sized canvas), which
// is precisely the vacuous pass it exists to rule out.
test('CONTROL: mounting with readings already present starts the loop and draws', () => {
  render({ readings: THREE });

  expect(canvasNow()).not.toBeNull();
  expect(harness.raf.requests).toBeGreaterThan(0);

  act(() => {
    harness.raf.pumpFrame(FRAME_STEP);
  });

  expect(drawsOn(canvasNow())).toBeGreaterThan(0);
});

// (2) THE OPERATOR'S CASE. Mount empty — the state of every page load — then
// let readings arrive while the view is open.
test('readings arriving while the view is already open start the loop', () => {
  render({ readings: [] });
  expect(canvasNow()).toBeNull();

  const requestsWhileEmpty = harness.raf.requests;

  render({ readings: THREE });

  const canvas = canvasNow();
  expect(canvas).not.toBeNull();
  // The loop must be SCHEDULED, not merely schedulable.
  expect(harness.raf.requests).toBeGreaterThan(requestsWhileEmpty);
  expect(harness.raf.pendingCount()).toBe(1);

  act(() => {
    harness.raf.pumpFrame(FRAME_STEP);
  });

  expect(drawsOn(canvas)).toBeGreaterThan(0);
});

// (3) The sizing effect has to re-run for the canvas that appears later, or the
// backing store stays at the HTML default 300x150 while CSS stretches it.
test('a canvas that mounts after the first commit gets a real backing store', () => {
  render({ readings: [] });
  render({ readings: THREE });

  const canvas = canvasNow();
  const dpr = window.devicePixelRatio || 1;

  expect(canvas.style.width).toBe(`${BOX_W}px`);
  expect(canvas.style.height).toBe(`${BOX_H}px`);
  expect(canvas.width).toBe(BOX_W * dpr);
  expect(canvas.height).toBe(BOX_H * dpr);
  // The pre-repair values, stated so a regression is recognisable.
  expect(canvas.width).not.toBe(300);
  expect(canvas.height).not.toBe(150);
});

// (4) THE RECONNECT CASE. RESET empties the readings, the canvas unmounts, and
// the readings come back. The frames must follow the element that is on screen.
test('after an empty -> non-empty cycle the frames land on the canvas in the DOM', () => {
  render({ readings: THREE });
  const first = canvasNow();
  act(() => {
    harness.raf.pumpFrame(FRAME_STEP);
  });
  expect(drawsOn(first)).toBeGreaterThan(0);

  // A reconnect: RESET clears resourceReadings, then a new session repopulates
  // it with new identities (the reducer never re-issues a clientSeq).
  render({ readings: [] });
  render({ readings: [reading(11, -100, -150), reading(10, -108, -158)] });

  const second = canvasNow();
  expect(second).not.toBe(first);

  const firstBefore = drawsOn(first);
  act(() => {
    harness.raf.pumpFrame(2 * FRAME_STEP);
  });

  expect(drawsOn(second)).toBeGreaterThan(0);
  // The detached element must be getting nothing. Before the repair this was
  // the ONLY element being drawn into.
  expect(drawsOn(first)).toBe(firstBefore);
  expect(second.width).toBe(BOX_W * (window.devicePixelRatio || 1));
});

// (5) One throw inside a frame must not be the end of the loop.
test('a throw inside the frame is survivable, logged once, and does not stop the loop', () => {
  const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
  try {
    render({ readings: THREE });
    act(() => {
      harness.raf.pumpFrame(FRAME_STEP);
    });

    const canvas = canvasNow();
    const ctx = harness.canvases.contextFor(canvas);
    const before = ctx.clearRects;

    // One transient fault, then the context behaves again — which models the
    // real failure (a node index that does not exist for one frame), not a
    // permanently broken canvas.
    ctx.throwOnNth('clearRect', 1);
    act(() => {
      harness.raf.pumpFrame(2 * FRAME_STEP);
    });

    // Nothing drew on that frame...
    expect(ctx.clearRects).toBe(before);
    // ...but a frame is still pending, which is the whole assertion. Before the
    // repair nothing was ever pending again.
    expect(harness.raf.pendingCount()).toBe(1);

    const ours = errSpy.mock.calls.filter(
      (c) => typeof c[0] === 'string' && c[0].includes('ResourceGraph render loop threw'),
    );
    expect(ours).toHaveLength(1);

    // And the next frame recovers.
    act(() => {
      harness.raf.pumpFrame(3 * FRAME_STEP);
    });
    expect(ctx.clearRects).toBeGreaterThan(before);

    // Still exactly one log: a 30 Hz console flood is not an acceptable price
    // for recovery, so the guard is one-shot.
    const oursAfter = errSpy.mock.calls.filter(
      (c) => typeof c[0] === 'string' && c[0].includes('ResourceGraph render loop threw'),
    );
    expect(oursAfter).toHaveLength(1);
  } finally {
    errSpy.mockRestore();
  }
});

// (6) THE GUARD ON THE REPAIR ITSELF. Keying the loop on element identity means
// a change that made the canvas element unstable would tear down and restart the
// loop on every render — leaking a loop per render, which is worse than the bug.
test('a re-render with the same readings does not start a second loop', () => {
  render({ readings: THREE });
  expect(harness.raf.pendingCount()).toBe(1);

  act(() => {
    harness.raf.pumpFrame(FRAME_STEP);
  });
  expect(harness.raf.pendingCount()).toBe(1);

  const canvasBefore = canvasNow();
  const requestsBefore = harness.raf.requests;

  // Same array identity: the memo, the effects and the element must all no-op.
  render({ readings: THREE });

  expect(canvasNow()).toBe(canvasBefore);
  expect(harness.raf.requests).toBe(requestsBefore);
  expect(harness.raf.pendingCount()).toBe(1);

  // A prop that is not `readings` must not restart it either.
  render({ readings: THREE, droppedReadings: 3 });
  expect(harness.raf.pendingCount()).toBe(1);
});

// The unmount path, which the element-identity change also rewires.
test('unmounting cancels the pending frame and schedules no more', () => {
  render({ readings: THREE });
  act(() => {
    harness.raf.pumpFrame(FRAME_STEP);
  });
  expect(harness.raf.pendingCount()).toBe(1);

  act(() => {
    root.render(null);
  });

  expect(harness.raf.pendingCount()).toBe(0);
  const requestsAfter = harness.raf.requests;
  act(() => {
    harness.raf.pumpFrame(2 * FRAME_STEP);
  });
  expect(harness.raf.requests).toBe(requestsAfter);
});
