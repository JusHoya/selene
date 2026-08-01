/**
 * A jsdom harness for testing a requestAnimationFrame render LOOP's lifecycle.
 *
 * WHY THIS EXISTS. The Resource Knowledge Map's defect was never in what it
 * drew — it was that the loop was never started at all in the case the operator
 * hits (ResourceGraph took an empty-state early return on the first commit,
 * which rendered no <canvas>, so all three canvas effects ran against null refs
 * and none of their dependency arrays could ever change again). Pinning that
 * repair needs the ACTUAL React commit sequence and the ACTUAL scheduling calls,
 * not a re-derivation of them: a test that re-implements the effect ordering is
 * a second copy of the thing under test and drifts with it.
 *
 * FOUR SHIMS, and every one of them was needed before the diagnosis harness
 * produced a meaningful result. They are listed here with what each MODELS,
 * because a shim that is wrong in the same direction as the bug makes a test
 * pass for the wrong reason:
 *
 *   1. requestAnimationFrame / cancelAnimationFrame. jsdom implements rAF on a
 *      16 ms timer, which makes frames a function of the test's wall clock. This
 *      replaces both with a manual queue and a `pumpFrame(ts)` that runs exactly
 *      the callbacks pending at the moment it is called. Callbacks scheduled
 *      DURING a pump land in the next batch — that is what makes "the loop
 *      rescheduled itself" an observable fact rather than a timing race.
 *
 *   2. ResizeObserver. jsdom does not implement it at all, so
 *      `new ResizeObserver(...)` throws a ReferenceError inside the sizing
 *      effect. The stub records observed elements and can fire the callback on
 *      demand; it never fires on its own, because jsdom has no layout to
 *      observe.
 *
 *   3. A LAYOUT BOX. jsdom measures every element as 0x0, and the loop under
 *      test bails on a zero-sized canvas (`if (w === 0 || h === 0)`). Without a
 *      box the CONTROL case records zero draws — the same observation as the
 *      DEFECT case, for a completely different reason. That was measured during
 *      the diagnosis and it is the single most dangerous shim here, so
 *      `installLayoutBox` is explicit and per-test rather than a global default.
 *      It models a static box: no scrolling, no borders, no transforms.
 *
 *   4. A 2D CONTEXT. jsdom's `HTMLCanvasElement.prototype.getContext('2d')`
 *      returns null (the native `canvas` package is not installed, and pulling
 *      it in would put a node-gyp build in front of the dashboard). The stub
 *      below draws NOTHING and asserts NOTHING about pixels. It counts calls,
 *      keyed by the canvas ELEMENT it belongs to, which is what lets a test ask
 *      "did the frame land on the canvas that is currently in the DOM, or on the
 *      detached one the loop captured three commits ago?".
 *
 * WHAT THIS CANNOT DO. It is not a browser and it does not rasterise. It cannot
 * see geometry, colour, layering or legibility, and it cannot tell you the view
 * is readable. Every assertion built on it is about LIFECYCLE and BOOKKEEPING.
 * A green suite here is not evidence the Knowledge Map renders; only opening it
 * in Chrome against a live backend is, and that is recorded as an open gap.
 */

/**
 * Replace global requestAnimationFrame / cancelAnimationFrame with a manual
 * queue.
 *
 * Returns a handle with:
 *   requests      total rAF calls since install (never decremented)
 *   cancels       total cancelAnimationFrame calls since install
 *   pendingCount()  callbacks scheduled and not yet run or cancelled
 *   pumpFrame(ts)   run every currently-pending callback with `ts`; returns how
 *                   many ran. Callbacks scheduled during the pump are NOT run.
 *   restore()     put the originals back
 */
export function installRafHarness() {
  const originalRaf = global.requestAnimationFrame;
  const originalCancel = global.cancelAnimationFrame;

  let nextId = 1;
  let pending = new Map();

  const handle = {
    requests: 0,
    cancels: 0,
    pendingCount() {
      return pending.size;
    },
    pumpFrame(ts) {
      const batch = pending;
      pending = new Map();
      let ran = 0;
      batch.forEach((cb) => {
        ran += 1;
        cb(ts);
      });
      return ran;
    },
    restore() {
      global.requestAnimationFrame = originalRaf;
      global.cancelAnimationFrame = originalCancel;
      pending = new Map();
    },
  };

  global.requestAnimationFrame = (cb) => {
    const id = nextId;
    nextId += 1;
    handle.requests += 1;
    pending.set(id, cb);
    return id;
  };
  global.cancelAnimationFrame = (id) => {
    handle.cancels += 1;
    pending.delete(id);
  };

  return handle;
}

/**
 * Install a ResizeObserver stub. It never fires by itself — jsdom has no layout
 * — but `handle.fireAll()` lets a test drive a resize deliberately.
 */
export function installResizeObserver() {
  const original = global.ResizeObserver;
  const instances = [];

  class StubResizeObserver {
    constructor(callback) {
      this.callback = callback;
      this.observed = [];
      this.disconnected = false;
      instances.push(this);
    }

    observe(el) {
      this.observed.push(el);
    }

    unobserve(el) {
      this.observed = this.observed.filter((e) => e !== el);
    }

    disconnect() {
      this.disconnected = true;
      this.observed = [];
    }
  }

  global.ResizeObserver = StubResizeObserver;

  return {
    instances,
    fireAll() {
      instances.filter((i) => !i.disconnected).forEach((i) => i.callback([]));
    },
    restore() {
      global.ResizeObserver = original;
    },
  };
}

/**
 * Give every element in the document a non-degenerate layout box.
 *
 * THIS IS THE SHIM THAT CAN MAKE A TEST PASS FOR THE WRONG REASON, so read what
 * it models. `getBoundingClientRect` returns the same static box for every
 * element, anchored at the origin; `clientWidth` / `clientHeight` return its
 * integer dimensions. There is no scroll offset, no border, no per-element
 * layout and no stacking. It exists so that a component which correctly
 * measures its container and correctly sizes its canvas produces non-zero
 * dimensions — nothing more. A test asserting a POSITION derived from this box
 * would be asserting the shim, not the component.
 */
export function installLayoutBox({ width = 800, height = 600 } = {}) {
  const proto = global.Element.prototype;
  const originalRect = proto.getBoundingClientRect;
  const originalClientWidth = Object.getOwnPropertyDescriptor(proto, 'clientWidth');
  const originalClientHeight = Object.getOwnPropertyDescriptor(proto, 'clientHeight');

  proto.getBoundingClientRect = function stubRect() {
    return {
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: width,
      bottom: height,
      width,
      height,
      toJSON() {
        return this;
      },
    };
  };
  Object.defineProperty(proto, 'clientWidth', {
    configurable: true,
    get() {
      return Math.round(width);
    },
  });
  Object.defineProperty(proto, 'clientHeight', {
    configurable: true,
    get() {
      return Math.round(height);
    },
  });

  return {
    width,
    height,
    restore() {
      proto.getBoundingClientRect = originalRect;
      if (originalClientWidth) {
        Object.defineProperty(proto, 'clientWidth', originalClientWidth);
      } else {
        delete proto.clientWidth;
      }
      if (originalClientHeight) {
        Object.defineProperty(proto, 'clientHeight', originalClientHeight);
      } else {
        delete proto.clientHeight;
      }
    },
  };
}

/**
 * A 2D context that draws nothing and records that it was asked to.
 *
 * `clearRects` is used throughout as the "a frame reached the canvas" counter,
 * because the loop under test clears once per drawn frame and skips the clear
 * entirely on a throttled frame. It is a PROXY for drawing, not a picture.
 *
 * `throwOnNth(method, n)` arms a single failure: the n-th subsequent call to
 * `method` throws once and then the arming is spent. That models the real
 * failure mode being tested — one transient TypeError from indexing a node that
 * does not exist yet — rather than a permanently broken context, which would
 * tell you nothing about recovery.
 */
export function createNoopContext2D() {
  const gradient = { addColorStop() {} };
  const armed = new Map();

  const ctx = {
    clearRects: 0,
    calls: {},

    fillStyle: '#000',
    strokeStyle: '#000',
    lineWidth: 1,
    globalAlpha: 1,
    font: '10px sans-serif',
    textAlign: 'start',
    textBaseline: 'alphabetic',

    throwOnNth(method, n) {
      armed.set(method, n);
    },
  };

  const record = (name) => {
    ctx.calls[name] = (ctx.calls[name] || 0) + 1;
    if (armed.has(name)) {
      const remaining = armed.get(name) - 1;
      if (remaining <= 0) {
        armed.delete(name);
        throw new TypeError(`rafHarness: armed failure in ctx.${name}()`);
      }
      armed.set(name, remaining);
    }
  };

  const methods = [
    'save', 'restore', 'setTransform', 'transform', 'translate', 'scale',
    'rotate', 'beginPath', 'closePath', 'moveTo', 'lineTo', 'arc', 'rect',
    'fill', 'stroke', 'fillRect', 'strokeRect', 'fillText', 'setLineDash',
    'drawImage', 'putImageData',
  ];
  methods.forEach((name) => {
    ctx[name] = function stub() {
      record(name);
    };
  });

  ctx.clearRect = function clearRect() {
    record('clearRect');
    ctx.clearRects += 1;
  };
  ctx.createRadialGradient = function createRadialGradient() {
    record('createRadialGradient');
    return gradient;
  };
  ctx.createLinearGradient = function createLinearGradient() {
    record('createLinearGradient');
    return gradient;
  };
  ctx.measureText = function measureText(text) {
    record('measureText');
    return { width: 6 * String(text).length };
  };

  return ctx;
}

/**
 * Patch HTMLCanvasElement.prototype.getContext so every canvas element gets its
 * OWN recording context, remembered by element identity.
 *
 * The per-element bookkeeping is the point. "The loop kept drawing into the
 * canvas it captured before the remount" and "the loop draws into the canvas on
 * screen" are indistinguishable if all contexts are pooled, and that difference
 * is exactly the RESET/reconnect defect.
 */
export function installCanvasContexts() {
  const proto = global.HTMLCanvasElement.prototype;
  const original = proto.getContext;
  const byElement = new Map();

  proto.getContext = function getContext(kind) {
    if (kind !== '2d') return null;
    let ctx = byElement.get(this);
    if (!ctx) {
      ctx = createNoopContext2D();
      byElement.set(this, ctx);
    }
    return ctx;
  };

  return {
    /** The context handed to `el`, or undefined if `el` never asked for one. */
    contextFor(el) {
      return byElement.get(el);
    },
    /** Every context created so far, in creation order. */
    all() {
      return Array.from(byElement.values());
    },
    restore() {
      proto.getContext = original;
      byElement.clear();
    },
  };
}

/**
 * Convenience: install all four shims and return one handle that restores them
 * in reverse order. Tests that need finer control can install individually.
 */
export function installCanvasLoopHarness({ width = 800, height = 600 } = {}) {
  const layout = installLayoutBox({ width, height });
  const resize = installResizeObserver();
  const canvases = installCanvasContexts();
  const raf = installRafHarness();

  return {
    layout,
    resize,
    canvases,
    raf,
    restore() {
      raf.restore();
      canvases.restore();
      resize.restore();
      layout.restore();
    },
  };
}
