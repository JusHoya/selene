import React, { useRef, useEffect, useCallback } from 'react';
import {
  posteriorCellRGBAAtCertainty,
  MAX_CONCENTRATION_WT,
} from '../utils/colors';
import './ResourceLegend.css';

// ==========================================================================
// D-17 — THE LEGEND IS THE FUNCTION THE MAP APPLIES, NOT A DESCRIPTION OF IT.
//
// WHAT WAS WRONG. This panel drew two independent one-dimensional bars:
//   * concentration, from `iceConcentrationColor(value, 1.0)` — the PURE ramp
//     at certainty 1.0; and
//   * certainty, from `certaintyRGB(5.0, certainty)` plus a locally re-derived
//     `ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * certainty`.
// The map draws neither of those. FleetMap.buildPosteriorRaster calls
// posteriorCellRGBA, which composes hue and certainty MULTIPLICATIVELY. So a
// cell observed once at 5.0 wt% — measured through the shipped ResourceMap:
// posterior mean 4.9875, variance 0.2494, certainty 0.6508 — renders
// rgb(31,199,204), and that colour is on NO point of the concentration bar
// (r is non-zero while b is not 255). Reaching the bar's colours needs
// certainty 1.0, i.e. variance <= VARIANCE_FLOOR, which takes 25 readings at a
// footprint centre with the shipped 0.5 wt% scout — and survey `min_spacing`
// (8.0 m) exceeds ResourceMap `footprint_radius` (5.0 m), so footprints do not
// overlap and most observed cells get exactly one reading. An operator could
// not invert a map cell against the legend at all.
//
// WHAT IT IS NOW. One two-dimensional swatch: concentration across, certainty
// up, every pixel evaluated through posteriorCellRGBAAtCertainty — the same
// function posteriorCellRGBA reduces to once it has turned a variance into a
// certainty. The legend cannot drift from the raster because it IS the
// raster's colour law sampled on a grid; there is no second copy of the ramp,
// the gray lerp or the alpha ramp anywhere in this file.
//
// That choice was made deliberately in preference to anything that had to
// LOOK right, because nothing in this environment can render it: a legend that
// is correct by construction is checkable from the source, and a legend that
// is merely well-chosen is not. What a human still has to confirm is legibility
// — see the note on the backdrop composite below.
// ==========================================================================

// Height of the swatch in CSS pixels. Enough rows that the certainty axis is a
// gradient rather than a handful of bands, small enough for a corner panel.
const SWATCH_HEIGHT_PX = 56;

// Background the swatch composites over, as [r, g, b]. The panel itself is
// rgba(10,14,26,0.85) over the map (ResourceLegend.css:5) and the map
// background is #0a0e1a, so this is what a map cell is drawn over too.
//
// COMPOSITED EXPLICITLY, per pixel, rather than by painting rgba() onto the
// canvas: `out = bg + (fg - bg) * a` IS canvas 'source-over' onto an opaque
// backdrop, and writing it out means the alpha half of the colour law is
// visible in this file instead of being an implicit property of the 2D
// context. It also lets the whole swatch go down in one putImageData.
const LEGEND_BACKDROP_RGB = [10, 14, 26];

// The narrowest certainty range the swatch will draw. A snapshot whose cells
// all sit within a hair of one certainty would otherwise produce a swatch
// whose vertical axis spans nothing and whose end labels read the same number.
const MIN_BAND_SPAN = 0.1;

// The certainty range the swatch covers, given whatever the caller knows.
//
// THE FULL 0..1 AXIS IS THE HONEST DEFAULT AND IT IS ALSO MOSTLY DEAD. At
// ALPHA_MIN 0.05 a certainty-0 swatch pixel composites to a delta of
// 4.0 / 4.1 / 4.2 per channel over #0a0e1a — about 1.6% of full scale, at or
// below a just-noticeable difference on a dark surface — so the bottom of the
// axis is a black smear. That is not a defect in the swatch: it is what a
// certainty-0 cell looks like ON THE MAP, and a legend that brightened it
// would be lying about the raster. The weakest evidence the shipped fleet can
// actually produce — one reading from the 0.5 wt% scout at the edge of its
// footprint, certainty 0.5008, alpha 0.4506 — composites to a delta of
// 36.0 / 36.9 / 37.9 at that same gray, nine times as far off the backdrop and
// plainly visible. (Both figures
// executed on 2026-07-31 and pinned by
// test_resource_map_viz.test_the_shipped_scout_cannot_reach_zero_certainty;
// neither was rendered.)
//
// So the fix for the dead half is to stop drawing it when — and only when —
// the caller can say what range the cells on screen occupy. That bound cannot
// be derived inside this component and it cannot be hardcoded either: it is a
// function of the sensor's noise_stddev, and ResourceMap.msg carries the
// posterior and its prior, never the instrument. It CAN be measured from the
// snapshot being drawn, which is strictly better than an RCDL-derived constant
// because it self-corrects when the fleet changes sensors.
//
// `certaintyBand` is that measurement. FleetMap computes it in a useMemo keyed
// on the snapshot and passes it (FleetMap.jsx, "D-17: the certainty range the
// cells on screen actually occupy"). It stays OPTIONAL, and that is not
// vestigial: the prop is null before the first snapshot and null again for a
// snapshot with no observed cells, and this component is also rendered by
// tests and by any future caller that has no map. Without it the swatch shows
// the whole mapping and says so in its end labels, which are always numeric for
// exactly this reason — the axis describes itself whether it is clipped or not.
function normaliseCertaintyBand(band) {
  const full = { min: 0, max: 1, clipped: false };
  if (!band) return full;
  const lo = Number(band.min);
  const hi = Number(band.max);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return full;
  const clamp = (v) => Math.min(Math.max(v, 0), 1);
  let min = clamp(Math.min(lo, hi));
  let max = clamp(Math.max(lo, hi));
  if (max - min < MIN_BAND_SPAN) {
    const mid = (min + max) / 2;
    min = Math.max(0, Math.min(1 - MIN_BAND_SPAN, mid - MIN_BAND_SPAN / 2));
    max = min + MIN_BAND_SPAN;
  }
  return { min, max, clipped: true };
}

function ResourceLegend({
  heatmapVisible,
  onToggleHeatmap,
  resourceMapStatus,
  mapAgeSec,
  observedCells,
  totalObservations,
  certaintyBand,
}) {
  const swatchRef = useRef(null);
  const band = normaliseCertaintyBand(certaintyBand);
  const bandMin = band.min;
  const bandMax = band.max;

  const drawSwatch = useCallback(() => {
    const canvas = swatchRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const cssWidth = canvas.clientWidth;
    const cssHeight = canvas.clientHeight;
    // A canvas measured before layout reports 0, and createImageData(0, n)
    // throws. The two bars this replaces had no such guard.
    if (!(cssWidth > 0 && cssHeight > 0)) return;

    const width = Math.max(1, Math.round(cssWidth * dpr));
    const height = Math.max(1, Math.round(cssHeight * dpr));
    canvas.width = width;
    canvas.height = height;
    // No ctx.scale(dpr, dpr): the ImageData below is written in DEVICE pixels
    // and putImageData ignores the transform, so scaling here would only
    // mislead the next reader.
    ctx.setTransform(1, 0, 0, 1, 0, 0);

    const image = ctx.createImageData(width, height);
    const data = image.data;
    const [bgR, bgG, bgB] = LEGEND_BACKDROP_RGB;

    for (let py = 0; py < height; py++) {
      // Canvas row 0 is the TOP, and the top is the CONFIDENT end — the same
      // orientation as the two numeric certainty labels beside the swatch,
      // whose larger value is drawn first. Nothing here shares the raster's
      // row order; that flip is a property of ResourceMap.msg, not of a legend.
      const t = height === 1 ? 1 : 1 - py / (height - 1);
      const certainty = bandMin + (bandMax - bandMin) * t;
      for (let px = 0; px < width; px++) {
        const wt = (width === 1 ? 0 : px / (width - 1)) * MAX_CONCENTRATION_WT;
        const [r, g, b, a] = posteriorCellRGBAAtCertainty(wt, certainty);
        const o = (py * width + px) * 4;
        data[o] = Math.round(bgR + (r - bgR) * a);
        data[o + 1] = Math.round(bgG + (g - bgG) * a);
        data[o + 2] = Math.round(bgB + (b - bgB) * a);
        data[o + 3] = 255;
      }
    }
    ctx.putImageData(image, 0, 0);
  }, [bandMin, bandMax]);

  // Redrawn on resize, not only on mount. The swatch is an ImageData sized in
  // device pixels at draw time, so a panel that changes width later — the
  // source line goes from 'rosbridge disconnected' to
  // 'fused posterior · 12s ago' and the panel reflows — would leave the canvas
  // stretched by the browser instead of re-evaluated. The old bars had the same
  // mount-only effect and got away with it because a linear gradient survives
  // stretching; a two-axis swatch does not, and it would not look wrong.
  useEffect(() => {
    drawSwatch();
    const canvas = swatchRef.current;
    // Guarded because this component is renderable outside a browser (jsdom
    // has no ResizeObserver by default), and a legend that throws takes the
    // map down with it.
    if (!canvas || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => drawSwatch());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [drawSwatch]);

  // Defaulted rather than required: App.jsx owns this prop, and a legend that
  // throws on a missing status would take the whole map down with it.
  const status = resourceMapStatus || { connected: false, received: false, dropped: 0 };

  let sourceLine;
  if (!status.received) {
    // Deliberately names the topic. "No data" tells an operator nothing they can
    // act on; the topic name tells them what to check with `ros2 topic echo`.
    sourceLine = status.connected
      ? 'awaiting /orchestrator/resource_map'
      : 'rosbridge disconnected';
  } else if (mapAgeSec == null) {
    sourceLine = 'fused posterior';
  } else {
    sourceLine = `fused posterior · ${mapAgeSec.toFixed(0)}s ago`;
  }

  const midWt = (MAX_CONCENTRATION_WT / 2).toFixed(
    MAX_CONCENTRATION_WT % 2 === 0 ? 0 : 1);

  return (
    <div className="resource-legend">
      <div className="resource-legend__title">Ice Concentration × Certainty</div>

      <div className="resource-legend__swatch-row">
        <div className="resource-legend__yaxis">
          <span>{bandMax.toFixed(2)}</span>
          <span>{bandMin.toFixed(2)}</span>
        </div>
        <canvas
          ref={swatchRef}
          className="resource-legend__swatch"
          style={{ width: '100%', height: SWATCH_HEIGHT_PX }}
        />
      </div>

      {/* The wt% labels sit inside a second swatch-row so they inherit the
          SAME leading column width as the certainty labels above. Setting a
          margin here instead would put the 22px + 6px gutter in two places and
          let the axis drift out from under its own tick labels. */}
      <div className="resource-legend__swatch-row">
        <div className="resource-legend__yaxis" aria-hidden="true" />
        <div className="resource-legend__labels">
          <span>0</span>
          <span>{midWt}</span>
          <span>{MAX_CONCENTRATION_WT} wt%</span>
        </div>
      </div>
      {/* The reading rule, in the two channels the swatch encodes. Without it
          a pale cell is ambiguous between "little ice" and "barely sampled",
          which is the D-02 defect one step downstream. */}
      <div className="resource-legend__source">
        hue = wt% · up = more certain
      </div>
      <div className="resource-legend__source">
        {band.clipped
          ? `certainty axis: cells on screen (${bandMin.toFixed(2)}–${bandMax.toFixed(2)})`
          : 'certainty axis: full mapping (0.00–1.00)'}
      </div>

      <div className="resource-legend__source">{sourceLine}</div>
      {status.received && (
        <div className="resource-legend__source">
          {observedCells} cells · {totalObservations} readings
        </div>
      )}
      {status.dropped > 0 && (
        <div className="resource-legend__warn">
          {status.dropped} snapshot{status.dropped === 1 ? '' : 's'} rejected
        </div>
      )}

      <button
        className={
          'resource-legend__toggle' +
          (heatmapVisible ? ' resource-legend__toggle--active' : '')
        }
        onClick={onToggleHeatmap}
      >
        <span className="resource-legend__indicator" />
        {heatmapVisible ? 'Heatmap On' : 'Heatmap Off'}
      </button>
    </div>
  );
}

export default ResourceLegend;
