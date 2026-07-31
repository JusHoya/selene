/**
 * A CanvasRenderingContext2D good enough to record what FleetMap draws.
 *
 * WHY THIS EXISTS. Deviation D-16 is a geometry defect: the collision planner
 * reserved a box narrower than the label it guarded, did not reserve the
 * battery gauge at all, and gated the state abbreviation on the id label. The
 * only honest way to pin the repair is to assert that every mark the renderer
 * actually emits lands inside a box the planner actually reserved — and that
 * needs the drawing calls, not a re-derivation of them, or the test is just a
 * second copy of the same arithmetic and drifts with it.
 *
 * jsdom's HTMLCanvasElement.getContext('2d') returns null (the `canvas` native
 * package is not installed and pulling it in for this would put a node-gyp
 * build in front of the dashboard). `drawRobots` never touches the DOM, though
 * — it only calls 2D context methods — so a plain object that implements the
 * subset it uses, tracks the transform stack, and records each mark's device
 * bounding box is a complete stand-in.
 *
 * TRANSFORM MATH. The canvas 2D transform is the affine matrix
 * [a c e; b d f], applied as (x, y) -> (a*x + c*y + e, b*x + d*y + f).
 * FleetMap only ever uses translate / scale / rotate, so that is all this
 * implements; anything else would silently record wrong coordinates, so
 * setTransform and transform deliberately throw rather than approximate.
 *
 * measureText models a monospace font: width = advanceEm * fontSize * length,
 * with fontSize parsed out of ctx.font. That is a MODEL, not a browser — see
 * the note in fleetMap.marks.test.js about what it can and cannot pin.
 */

const FONT_SIZE_RE = /(-?[\d.]+)px/;

function mul(m, n) {
  // m then n, i.e. apply m first. Both are {a,b,c,d,e,f}.
  return {
    a: m.a * n.a + m.b * n.c,
    b: m.a * n.b + m.b * n.d,
    c: m.c * n.a + m.d * n.c,
    d: m.c * n.b + m.d * n.d,
    e: m.e * n.a + m.f * n.c + n.e,
    f: m.e * n.b + m.f * n.d + n.f,
  };
}

function apply(m, x, y) {
  return { x: m.a * x + m.c * y + m.e, y: m.b * x + m.d * y + m.f };
}

// The absolute scale factors of the current transform, used to convert a
// lineWidth (a user-space quantity) into the device-space halo it paints.
function scaleOf(m) {
  return {
    sx: Math.hypot(m.a, m.b),
    sy: Math.hypot(m.c, m.d),
  };
}

function boxOfPoints(points) {
  return {
    x0: Math.min(...points.map((p) => p.x)),
    y0: Math.min(...points.map((p) => p.y)),
    x1: Math.max(...points.map((p) => p.x)),
    y1: Math.max(...points.map((p) => p.y)),
  };
}

export function growBox(box, m) {
  return { x0: box.x0 - m, y0: box.y0 - m, x1: box.x1 + m, y1: box.y1 + m };
}

export function boxContains(outer, inner, eps = 1e-9) {
  return inner.x0 >= outer.x0 - eps && inner.x1 <= outer.x1 + eps
    && inner.y0 >= outer.y0 - eps && inner.y1 <= outer.y1 + eps;
}

export function boxesOverlap(a, b) {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

export function createRecordingContext({ advanceEm = 0.6 } = {}) {
  let m = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
  const stack = [];
  let path = [];
  let arcs = [];

  const ctx = {
    // Recorded marks. Each is { kind, box (device px), ...detail }.
    marks: [],

    font: '10px sans-serif',
    fillStyle: '#000',
    strokeStyle: '#000',
    lineWidth: 1,
    globalAlpha: 1,
    shadowBlur: 0,
    shadowColor: '',
    textAlign: 'start',
    textBaseline: 'alphabetic',
    imageSmoothingEnabled: true,

    save() {
      stack.push({
        m: { ...m },
        font: this.font,
        lineWidth: this.lineWidth,
        globalAlpha: this.globalAlpha,
        textAlign: this.textAlign,
        textBaseline: this.textBaseline,
      });
    },
    restore() {
      const s = stack.pop();
      if (!s) throw new Error('recordingCanvas: restore() with an empty stack');
      m = s.m;
      this.font = s.font;
      this.lineWidth = s.lineWidth;
      this.globalAlpha = s.globalAlpha;
      this.textAlign = s.textAlign;
      this.textBaseline = s.textBaseline;
    },
    translate(x, y) { m = mul({ a: 1, b: 0, c: 0, d: 1, e: x, f: y }, m); },
    scale(sx, sy) { m = mul({ a: sx, b: 0, c: 0, d: sy, e: 0, f: 0 }, m); },
    rotate(r) {
      const cos = Math.cos(r);
      const sin = Math.sin(r);
      m = mul({ a: cos, b: sin, c: -sin, d: cos, e: 0, f: 0 }, m);
    },
    setTransform() { throw new Error('recordingCanvas: setTransform is not modelled'); },
    transform() { throw new Error('recordingCanvas: transform is not modelled'); },

    beginPath() { path = []; arcs = []; },
    moveTo(x, y) { path.push(apply(m, x, y)); },
    lineTo(x, y) { path.push(apply(m, x, y)); },
    closePath() {},
    arc(x, y, r) {
      const c = apply(m, x, y);
      const { sx, sy } = scaleOf(m);
      arcs.push({ x0: c.x - r * sx, y0: c.y - r * sy, x1: c.x + r * sx, y1: c.y + r * sy });
    },
    rect() { throw new Error('recordingCanvas: rect() is not modelled'); },
    setLineDash() {},
    createRadialGradient() { return { addColorStop() {} }; },
    drawImage() {},
    putImageData() {},
    createImageData() { throw new Error('recordingCanvas: createImageData is not modelled'); },

    _pathBox() {
      const boxes = arcs.slice();
      if (path.length > 0) boxes.push(boxOfPoints(path));
      if (boxes.length === 0) return null;
      return {
        x0: Math.min(...boxes.map((b) => b.x0)),
        y0: Math.min(...boxes.map((b) => b.y0)),
        x1: Math.max(...boxes.map((b) => b.x1)),
        y1: Math.max(...boxes.map((b) => b.y1)),
      };
    },
    _strokeHalo() {
      const { sx, sy } = scaleOf(m);
      return Math.max(this.lineWidth * sx, this.lineWidth * sy) / 2;
    },

    fill() {
      const box = this._pathBox();
      if (box) this.marks.push({ kind: 'fill', box, style: this.fillStyle });
    },
    stroke() {
      const box = this._pathBox();
      if (box) {
        this.marks.push({
          kind: 'stroke', box: growBox(box, this._strokeHalo()), style: this.strokeStyle,
        });
      }
    },
    fillRect(x, y, w, h) {
      const box = boxOfPoints([apply(m, x, y), apply(m, x + w, y + h)]);
      this.marks.push({ kind: 'fillRect', box, style: this.fillStyle });
    },
    strokeRect(x, y, w, h) {
      const box = boxOfPoints([apply(m, x, y), apply(m, x + w, y + h)]);
      this.marks.push({
        kind: 'strokeRect', box: growBox(box, this._strokeHalo()), style: this.strokeStyle,
      });
    },

    _fontSize() {
      const hit = FONT_SIZE_RE.exec(this.font);
      if (!hit) throw new Error(`recordingCanvas: unparsable font "${this.font}"`);
      return parseFloat(hit[1]);
    },
    // The advance model, split out from measureText so that fillText's own use
    // of it does not inflate `measureCalls`. That counter exists to check
    // FleetMap's measurement budget (D-16(a) buys a measured collision window
    // by caching), and it would be useless if the stub's bookkeeping showed up
    // in it — which it did, at exactly two per drawn label.
    _advance(text) {
      return advanceEm * this._fontSize() * String(text).length;
    },
    // Counts only calls made BY the code under test.
    measureCalls: 0,
    measureText(text) {
      this.measureCalls += 1;
      return { width: this._advance(text) };
    },
    fillText(text, x, y) {
      if (this.textAlign !== 'left' && this.textAlign !== 'center') {
        // Every label FleetMap draws sets textAlign explicitly; anything else
        // means the geometry below would be guesswork.
        throw new Error(`recordingCanvas: unmodelled textAlign "${this.textAlign}"`);
      }
      const w = this._advance(text);
      const h = this._fontSize();
      // textBaseline 'top' => the em box hangs downward from the anchor in the
      // CURRENT user space. FleetMap's label block flips y locally, so "down in
      // user space" is what the device transform then maps.
      const x0 = this.textAlign === 'center' ? x - w / 2 : x;
      const corners = [apply(m, x0, y), apply(m, x0 + w, y + h)];
      this.marks.push({
        kind: 'fillText', text: String(text), box: boxOfPoints(corners), style: this.fillStyle,
      });
    },
  };

  return ctx;
}
