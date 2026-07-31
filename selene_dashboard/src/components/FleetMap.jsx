import React, { useRef, useState, useEffect, useCallback, useMemo } from 'react';
import {
  WORLD,
  PSR_ZONES,
  DEPOT,
  RECHARGE_STATION,
  ICE_DEPOSITS,
  ROCKS,
  PROSPECT_WAYPOINTS,
  DEFAULT_VIEW,
} from '../utils/worldConfig';
import {
  TYPE_COLORS,
  STATE_COLORS,
  STATE_ABBREV,
  posteriorCellRGBA,
  varianceToCertainty,
} from '../utils/colors';
import { isStale } from '../utils/staleness';
import { generateLunarTerrain, drawCraterOutlines } from '../utils/lunarTerrain';
import ResourceLegend from './ResourceLegend';
import './FleetMap.css';

// ---------- Cached lunar terrain ----------
let _terrainCanvas = null;
function getLunarTerrain() {
  if (!_terrainCanvas) {
    _terrainCanvas = generateLunarTerrain(1024, 1024);
  }
  return _terrainCanvas;
}

// ---------- Constants ----------
const PADDING_RATIO = 0.05;
const MIN_SCALE = 0.3;
const MAX_SCALE = 20;
const ZOOM_FACTOR = 1.1;
const ROBOT_HIT_RADIUS = 15; // pixels
const FRAME_INTERVAL = 1000 / 30; // 30 fps cap

// D-01 / D-16: the marks drawn for one robot are a fixed vertical stack. Every
// offset in it is a count of SCREEN pixels divided by `scale`, so the stack
// holds its size at any zoom:
//
//     state dot (upper-right of the icon)      <- always drawn
//     icon, half-height ICON_PX / ICON_SEL_PX  <- always drawn
//     GAUGE_GAP_PX
//     battery gauge, GAUGE_H_PX tall           <- always drawn
//     LABEL_GAP_PX
//     "scout_01 NAV" | "NAV" | nothing         <- droppable, in that order
//
// The gauge used to hang BELOW the label and was gated on the label having been
// placed, so a robot whose label lost a collision also lost its battery
// reading. D-01 put the gauge above the label and anchored it to the icon;
// planRobotMarks() below now reserves it as well, which is the half D-01
// missed (D-16(b)).
//
// D-01 also deleted LABEL_MIN_SCALE, which suppressed unselected labels below
// 0.9 px/m. The font is `${LABEL_FONT_PX / scale}px` inside a net-uniform
// `scale` transform, so a glyph is LABEL_FONT_PX CSS pixels at every zoom
// including the minimum; the gate was guarding a legibility problem that does
// not exist. (Static argument from the transform chain; not observed in a
// browser.)
const ICON_PX = 12;             // icon half-height, unselected
const ICON_SEL_PX = 16;         // icon half-height, selected
const ICON_STROKE_PX = 0.8;     // outline around the triangle
const SELECT_RING_PX = 1.5;     // selection ring stroke, radius 1.6x icon
const ERROR_RING_PX = 2;        // ERROR ring stroke, radius 1.3x icon
const STATE_DOT_R_PX = 3.5;     // filled disc radius; a 2px annulus is sub-pixel
const STATE_DOT_STROKE_PX = 1;  // outline so the dot reads on any terrain
const STATE_DOT_OFFSET = 0.9;   // multiple of the icon half-height, both axes
const GAUGE_W_PX = 20;
const GAUGE_H_PX = 3;
const GAUGE_STROKE_PX = 0.5;    // strokeRect straddles the fill edge
const GAUGE_GAP_PX = 4;         // icon bottom -> gauge
const LABEL_GAP_PX = 3;         // gauge -> label top

// The label font, in ONE place. It used to be spelled out at each fillText and
// the collision window was a separate constant that had to be kept in step with
// it by hand. It was not kept in step: see D-16(a) below.
const LABEL_FONT_PX = 9;
const LABEL_FONT_FAMILY = 'JetBrains Mono, monospace';

// The drawn height of one label row. `textBaseline = 'top'` puts the em box's
// top at the anchor, so the ink runs from there to about one em plus the
// descender; 1.2 em is the usual normal-line-height figure. This one IS an
// estimate, deliberately: measureText's actualBoundingBoxAscent/Descent are not
// available in every engine this has to run in, and the row height is not the
// dimension that has ever drifted. The WIDTH is measured — see below.
const LABEL_LINE_PX = Math.ceil(LABEL_FONT_PX * 1.2);   // 11

// One nudge clears exactly one label row plus the gap between rows, so two
// nudged labels stack instead of touching. This replaces LABEL_SEP_PX_Y, a
// hand-set 22 px described as "clears a label + its battery bar" — the bar no
// longer needs clearing by the step because it is reserved outright.
const LABEL_NUDGE_PX = LABEL_LINE_PX + LABEL_GAP_PX;    // 14
const LABEL_MAX_ATTEMPTS = 3;   // nudges tried before a label tier is refused
// The gauge cannot be dropped, so when two would coincide the later one steps
// down instead. Capped low on purpose: two steps put a gauge at most 28 px
// below its nominal slot, still directly beneath its own icon in x. Further
// than that and the bar stops reading as belonging to that robot, which is the
// very misattribution this is here to prevent.
const GAUGE_MAX_ATTEMPTS = 2;

// D-16(a): THE COLLISION WINDOW IS NOW MEASURED, NOT GUESSED.
//
// It used to be `LABEL_SEP_PX_X`, a constant that drifted twice. 52 px was
// sized for a bare id, but 'excavator_01' is 12 characters and at the 0.6 em
// advance this file assumes for JetBrains Mono that is ~64.8 px — the window
// was already 12.8 px too narrow. D-01 then appended a 4-character state suffix
// (' NAV') and widened the window to 64 px: the text grew 33 % while the window
// grew 23 %, taking the shortfall to 22.4 px against an ~86.4 px label, i.e.
// 26 % of the label. The comment that set it computed both numbers and
// concluded "64 px sits between them" without drawing the conclusion that two
// labels 64-86 px apart therefore pass the collision test and still overlap.
//
// A bigger constant would be the same defect with a different number. The
// window is now measureText() on the exact string that gets drawn, and only
// this fallback is nominal — it is used when an engine returns a width of zero
// or NaN (see makeLabelMeasurer) and never cached.
const FALLBACK_ADVANCE_EM = 0.6;
const UNKNOWN_ABBREV = '???';

// ---------- Drawing helpers ----------

function worldToCanvas(ctx, centerX, centerY, scale, canvasW, canvasH) {
  // Translate so (centerX, centerY) in world space is at canvas center.
  // Flip Y axis so world-Y-up maps to canvas-Y-down.
  ctx.translate(canvasW / 2, canvasH / 2);
  ctx.scale(scale, -scale); // negative Y to flip
  ctx.translate(-centerX, -centerY);
}

function drawGrid(ctx, scale) {
  const minor = 50; // meters

  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.025)';
  ctx.lineWidth = 1 / scale;
  ctx.beginPath();
  for (let x = WORLD.X_MIN; x <= WORLD.X_MAX; x += minor) {
    ctx.moveTo(x, WORLD.Y_MIN);
    ctx.lineTo(x, WORLD.Y_MAX);
  }
  for (let y = WORLD.Y_MIN; y <= WORLD.Y_MAX; y += minor) {
    ctx.moveTo(WORLD.X_MIN, y);
    ctx.lineTo(WORLD.X_MAX, y);
  }
  ctx.stroke();
  ctx.restore();
}

function drawGridLabels(ctx, centerX, centerY, scale, canvasW, canvasH) {
  // Draw labels in screen space (no flip)
  ctx.save();
  ctx.font = '10px JetBrains Mono, monospace';
  ctx.fillStyle = 'rgba(255,255,255,0.15)';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';

  const step = 100;
  for (let wx = WORLD.X_MIN; wx <= WORLD.X_MAX; wx += step) {
    const sx = canvasW / 2 + (wx - centerX) * scale;
    const sy = canvasH - 4;
    if (sx > 30 && sx < canvasW - 30) {
      ctx.fillText(`${wx}m`, sx, sy - 12);
    }
  }

  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let wy = WORLD.Y_MIN; wy <= WORLD.Y_MAX; wy += step) {
    const sy = canvasH / 2 - (wy - centerY) * scale;
    if (sy > 20 && sy < canvasH - 20) {
      ctx.fillText(`${wy}m`, 30, sy);
    }
  }
  ctx.restore();
}

function drawPSRZones(ctx, scale) {
  ctx.save();
  PSR_ZONES.forEach((zone) => {
    const [cx, cy] = zone.center;

    // Radial gradient simulating crater shadow depth — darkest at center,
    // softer at the rim. Layered over the procedural crater bowl.
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, zone.radius);
    grad.addColorStop(0.0, 'rgba(2, 4, 12, 0.85)');    // pitch-black floor
    grad.addColorStop(0.55, 'rgba(8, 12, 28, 0.55)');  // mid wall
    grad.addColorStop(1.0, 'rgba(20, 28, 50, 0.15)');  // soft rim fade
    ctx.beginPath();
    ctx.arc(cx, cy, zone.radius, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();

    // Dashed cyan border
    ctx.setLineDash([6 / scale, 4 / scale]);
    ctx.strokeStyle = '#00d4ff';
    ctx.lineWidth = 2 / scale;
    ctx.stroke();
    ctx.setLineDash([]);

    // Label — flip Y locally so text is upright; position below the zone
    ctx.save();
    ctx.translate(cx, cy - zone.radius - 4 / scale);
    ctx.scale(1, -1);
    ctx.font = `${11 / scale}px JetBrains Mono, monospace`;
    ctx.fillStyle = 'rgba(0,212,255,0.4)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('PSR Zone', 0, 0);
    ctx.restore();
  });
  ctx.restore();
}

// ---------- D-02: the fused posterior, rasterised ----------
//
// WHAT THIS REPLACED. The heatmap used to be one radial blob per raw
// ResourceMapUpdate, composited with 'screen', with opacity taken from
// `sensor_uncertainty`. Two things were wrong with that. The opacity axis was
// inert: sensor_uncertainty traces through
// selene_agent/selene_agent/skills/prospect.py:137-157 to the constant
// noise_stddev: 0.5 in selene_hal/config/scout.yaml:16, so every blob got
// alpha 0.35. And the picture was a pile of overlapping per-reading splats
// rather than the fused belief the orchestrator actually holds — two readings
// that disagreed showed as two blobs, not as one uncertain cell.
//
// The orchestrator has published its posterior on /orchestrator/resource_map
// since D-09. This draws THAT, one pixel per grid cell, with alpha and a gray
// tier derived from each cell's own posterior variance.
//
// WHY 'source-over' AND NOT 'screen'. 'screen' existed because overlapping
// radial blobs needed additive blending to accumulate. A grid has no overlap,
// and 'screen' can only lighten, so it would wash out precisely the dark
// LOW_CONFIDENCE_GRAY the PRD asks for at low certainty. Per-pixel alpha does
// the blending now, which is the honest mapping because alpha IS the
// confidence. Nothing here sets globalCompositeOperation, so it stays at the
// canvas default of 'source-over'.

// Rebuild the offscreen cell raster if the snapshot changed. Returns the
// canvas, or null when there is nothing to draw.
//
// `store` is a mutable ref object: { canvas, ctx, image, revision, width,
// height }. The raster is rewritten ONLY when resourceMap.revision changes —
// snapshots arrive at resource_map_publish_rate (0.5 Hz) while this render loop
// runs at 30 fps, so an identity or timestamp comparison would rebuild a
// 500x500 ImageData sixty times for every one time it changed. `revision` makes
// that check O(1).
//
// D-15: THE CACHE KEY'S UNIQUENESS IS NOT THIS FUNCTION'S TO GUARANTEE, and it
// used not to hold. `store` is a useRef and survives a rosbridge reconnect
// (App.jsx renders FleetMap with no connection-keyed `key`), while `revision`
// was counted from `state.resourceMap` — which RESET nulls. The first snapshot
// of a new backend session therefore arrived as revision 1 again, matched a
// store still holding revision 1, and the rebuild was skipped: the dead
// session's cells kept blitting while ResourceLegend already reported the new
// snapshot's counts. The dimension guard below cannot see it, because a
// restarted orchestrator publishes the same width and height. The counter now
// lives in reducer state and RESET carries it forward; see
// useFleetState.js UPDATE_RESOURCE_MAP.
function buildPosteriorRaster(store, map) {
  if (!map) return null;
  const width = map.width;
  const height = map.height;
  if (!(width > 0 && height > 0)) return null;

  if (!store.canvas || store.width !== width || store.height !== height) {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    store.canvas = canvas;
    store.ctx = canvas.getContext('2d');
    store.image = store.ctx.createImageData(width, height);
    store.width = width;
    store.height = height;
    store.revision = -1;
  }
  if (store.revision === map.revision) return store.canvas;

  const { cellIndex, cellMean, cellVariance, priorVariance } = map;
  // App.jsx guarantees these are equal-length and drops any snapshot where they
  // are not (ResourceMap.msg requires a consumer to reject such a message). The
  // assert is a development tripwire, not error handling.
  console.assert(
    cellIndex.length === cellMean.length && cellIndex.length === cellVariance.length,
    'FleetMap: resourceMap parallel arrays disagree in length',
  );
  const n = Math.min(cellIndex.length, cellMean.length, cellVariance.length);

  const data = store.image.data;
  // Every rebuild starts fully transparent. A cell absent from cellIndex is not
  // drawn at all — that is the structural "no data" end of the PRD's ramp — and
  // it must not inherit whatever the previous snapshot painted at that pixel.
  data.fill(0);

  for (let i = 0; i < n; i++) {
    const flat = cellIndex[i];
    const row = Math.floor(flat / width);
    const col = flat - row * width;
    if (row < 0 || row >= height || col < 0 || col >= width) continue;

    // ROW FLIP — the one line here that would fail silently and plausibly.
    //
    // ResourceMap.msg:79-92 states, with a citation to the mirrored-terrain
    // incident recorded in selene_sim/scripts/generate_heightmap.py, that row 0
    // is the SOUTH (minimum-y) edge and rows ascend with world y. Canvas
    // ImageData row 0 is the TOP of the image. So cell row r belongs in image
    // row height-1-r, and drawPosteriorRaster below anchors the blit at the
    // NORTH-WEST corner with a negative y scale to match — the same convention
    // the terrain blit already uses. Getting this backwards mirrors the map
    // north-south while still looking entirely plausible on screen; this
    // repository has shipped that exact defect once already.
    const p = ((height - 1 - row) * width + col) * 4;

    const rgba = posteriorCellRGBA(cellMean[i], cellVariance[i], priorVariance);
    data[p] = rgba[0];
    data[p + 1] = rgba[1];
    data[p + 2] = rgba[2];
    data[p + 3] = Math.round(rgba[3] * 255);
  }

  store.ctx.putImageData(store.image, 0, 0);
  store.revision = map.revision;
  return store.canvas;
}

// Blit the cell raster into world space. Called inside the world transform.
function drawPosteriorRaster(ctx, raster, map) {
  const { resolution, height, originX, originY } = map;
  // App.jsx validates the parallel arrays but not the geometry. A zero or
  // negative resolution would make the scale below singular and silently
  // collapse the whole overlay to a line, so refuse to draw instead.
  if (!(resolution > 0)) return;
  ctx.save();
  // One image pixel is one grid cell, and a cell is `resolution` metres across.
  // Nearest-neighbour: a cell is a measurement over a square of ground, not a
  // sample to interpolate between, and smoothing would invent gradients across
  // the boundary between an observed cell and an unobserved (transparent) one.
  ctx.imageSmoothingEnabled = false;
  // ResourceMap.msg:48-55 — `origin` is the OUTER corner of cell (0,0) at
  // minimum x and minimum y, so the grid spans originY .. originY + height*res.
  // Anchor at the north-west corner and flip y, exactly as the terrain blit
  // does with (WORLD.X_MIN, WORLD.Y_MAX), because the raster's row 0 is north.
  ctx.translate(originX, originY + height * resolution);
  ctx.scale(resolution, -resolution);
  ctx.drawImage(raster, 0, 0);
  ctx.restore();
}

function drawIceDeposits(ctx, scale) {
  ctx.save();
  ctx.setLineDash([4 / scale, 4 / scale]);
  ctx.strokeStyle = 'rgba(0,212,255,0.1)';
  ctx.lineWidth = 1 / scale;

  ICE_DEPOSITS.forEach((dep) => {
    ctx.beginPath();
    ctx.arc(dep.center[0], dep.center[1], dep.radius, 0, Math.PI * 2);
    ctx.stroke();
  });
  ctx.setLineDash([]);
  ctx.restore();
}

function drawDepot(ctx, scale) {
  ctx.save();
  const { x, y, radius } = DEPOT;
  const s = radius * 0.7;

  // Diamond shape
  ctx.beginPath();
  ctx.moveTo(x, y + s);
  ctx.lineTo(x + s, y);
  ctx.lineTo(x, y - s);
  ctx.lineTo(x - s, y);
  ctx.closePath();

  ctx.fillStyle = 'rgba(255,193,7,0.25)';
  ctx.fill();
  ctx.strokeStyle = '#ffc107';
  ctx.lineWidth = 1.5 / scale;
  ctx.stroke();

  // A-polish: DEPOT and RECHARGE_STATION used to share one world coordinate
  // (worldConfig.js), so their labels rendered on top of each other as an
  // illegible blob, and the fix was to offset only the LABEL — DEPOT above the
  // marker, RECHARGE below it. Since 2026-07-31 they are 86 m apart (the depot
  // moved to the crater floor; see worldConfig.js) so the collision no longer
  // arises, but the offsets are kept: they also separate each label from the
  // robot labels drawn to the RIGHT of the same marker, and reverting them
  // would trade one legible layout for an untested one.
  ctx.save();
  ctx.translate(x, y + s + 6 / scale);
  ctx.scale(1, -1);
  ctx.font = `bold ${10 / scale}px JetBrains Mono, monospace`;
  ctx.fillStyle = '#ffc107';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText('DEPOT', 0, 0);
  ctx.restore();

  ctx.restore();
}

function drawRechargeStation(ctx, scale) {
  ctx.save();
  const { x, y, radius } = RECHARGE_STATION;

  // Circle
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(0,230,118,0.15)';
  ctx.fill();
  ctx.strokeStyle = '#00e676';
  ctx.lineWidth = 1.5 / scale;
  ctx.stroke();

  // Lightning bolt icon
  const s = radius * 0.5;
  ctx.beginPath();
  ctx.moveTo(x - s * 0.3, y + s);
  ctx.lineTo(x + s * 0.15, y + s * 0.1);
  ctx.lineTo(x - s * 0.05, y + s * 0.1);
  ctx.lineTo(x + s * 0.3, y - s);
  ctx.lineTo(x - s * 0.15, y - s * 0.1);
  ctx.lineTo(x + s * 0.05, y - s * 0.1);
  ctx.closePath();
  ctx.fillStyle = '#00e676';
  ctx.fill();

  // A-polish: drawn to the RIGHT of the marker. DEPOT sits at the same world
  // position (by design) and labels above it; robots parked at the depot label
  // below themselves. Offsetting sideways is the only direction that collides
  // with neither. World coordinates are untouched — this is a label offset.
  ctx.save();
  ctx.translate(x + radius + 5 / scale, y);
  ctx.scale(1, -1);
  ctx.font = `bold ${9 / scale}px JetBrains Mono, monospace`;
  ctx.fillStyle = '#00e676';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText('RECHARGE', 0, 0);
  ctx.restore();

  ctx.restore();
}

function drawRocks(ctx, scale) {
  ctx.save();
  // Rock hazard markers — subtle outlines that complement terrain craters
  ctx.strokeStyle = 'rgba(180, 140, 100, 0.25)';
  ctx.lineWidth = 1 / scale;
  ROCKS.forEach((rock) => {
    ctx.beginPath();
    ctx.arc(rock.x, rock.y, rock.r + 0.5, 0, Math.PI * 2);
    ctx.stroke();
  });
  ctx.restore();
}

function drawProspectWaypoints(ctx, scale) {
  ctx.save();
  const armLen = 4 / scale;
  PROSPECT_WAYPOINTS.forEach((wp, i) => {
    const [x, y] = wp;

    // Crosshair
    ctx.strokeStyle = 'rgba(0,212,255,0.35)';
    ctx.lineWidth = 1 / scale;
    ctx.beginPath();
    ctx.moveTo(x - armLen, y);
    ctx.lineTo(x + armLen, y);
    ctx.moveTo(x, y - armLen);
    ctx.lineTo(x, y + armLen);
    ctx.stroke();

    // Small circle at center
    ctx.beginPath();
    ctx.arc(x, y, 1.5 / scale, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(0,212,255,0.35)';
    ctx.stroke();

    // Number label
    ctx.save();
    ctx.translate(x + armLen + 2 / scale, y);
    ctx.scale(1, -1);
    ctx.font = `${9 / scale}px JetBrains Mono, monospace`;
    ctx.fillStyle = 'rgba(0,212,255,0.35)';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${i + 1}`, 0, 0);
    ctx.restore();
  });
  ctx.restore();
}

// A-polish: deterministic draw order for label placement.
// Selected robot first (so it always wins its slot), then top-to-bottom on
// screen, then by id — so the plan does not jitter frame to frame.
export function orderRobotsForLabels(entries, selectedRobotId) {
  return entries.slice().sort((a, b) => {
    const aSel = a.robot_id === selectedRobotId ? 0 : 1;
    const bSel = b.robot_id === selectedRobotId ? 0 : 1;
    if (aSel !== bSel) return aSel - bSel;
    const ay = a.pose?.y ?? 0;
    const by = b.pose?.y ?? 0;
    if (ay !== by) return by - ay;
    return String(a.robot_id).localeCompare(String(b.robot_id));
  });
}

// ---------- D-16: one plan, covering every mark that gets drawn ----------
//
// SCREEN-PIXEL SPACE. Everything below works in px: `px_x = worldX * scale` and
// `px_y = -worldY * scale`, so px_y grows DOWNWARD exactly as canvas y does
// after the world transform's negative y scale. The inverse is
// `worldX = px_x / scale`, `worldY = -px_y / scale`, and drawRobots uses only
// that inverse — it never recomputes an offset of its own.
//
// The predecessor compared world distances against a px constant divided by
// `scale`, which is the same test done in a space where every dimension has to
// be divided before it can be compared. The two sides drifted apart twice; see
// D-16(a) at the constants. Comparing boxes in the space the constants are
// already expressed in makes the drift impossible rather than unlikely.
function overlaps(a, b) {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

// Hoisted out of the nudge loops below rather than written inline as
// `reserved.some((r) => overlaps(r, box))`: an arrow function declared inside a
// `while` that closes over the `let` it is testing is the no-loop-func pattern,
// and CRA's build lint rejects it. Passing the box in makes the check a pure
// function of its arguments, which is also how the tests read it.
function collidesAny(reserved, box) {
  return reserved.some((r) => overlaps(r, box));
}

function grow(box, m) {
  return { x0: box.x0 - m, y0: box.y0 - m, x1: box.x1 + m, y1: box.y1 + m };
}

// The furthest ink from the icon's centre, in px. The triangle is stroked, the
// selection ring sits at 1.6x and the ERROR ring at 1.3x, and each stroke puts
// half its width outside the path.
function iconReachPx(iconPx, isSelected, fsmState) {
  let r = iconPx + ICON_STROKE_PX / 2;
  if (fsmState === 'ERROR') {
    r = Math.max(r, iconPx * 1.3 + ERROR_RING_PX / 2);
  }
  if (isSelected) {
    r = Math.max(r, iconPx * 1.6 + SELECT_RING_PX / 2);
  }
  return r;
}

function iconBoxPx(it) {
  const r = it.reachPx;
  return { x0: it.cx - r, y0: it.cy - r, x1: it.cx + r, y1: it.cy + r };
}

// The state dot is drawn at world (x + icon*OFFSET, y + icon*OFFSET). World +y
// is UP on screen, so in px space it is up-and-right: px_y DECREASES.
function dotBoxPx(it) {
  const d = it.iconPx * STATE_DOT_OFFSET;
  const r = STATE_DOT_R_PX + STATE_DOT_STROKE_PX / 2;
  return {
    x0: it.cx + d - r, y0: it.cy - d - r,
    x1: it.cx + d + r, y1: it.cy - d + r,
  };
}

// The gauge's fillRect, in px. `dy` is the collision nudge from pass 1.
function gaugeRectPx(it, dy) {
  const top = it.cy + it.iconPx + GAUGE_GAP_PX + dy;
  return {
    x0: it.cx - GAUGE_W_PX / 2, y0: top,
    x1: it.cx + GAUGE_W_PX / 2, y1: top + GAUGE_H_PX,
  };
}

// px_y of the first label candidate: immediately below the gauge slot, whether
// or not this robot reports a battery level. A robot with no reading must not
// have its label jump up into the space every other robot's gauge occupies.
function labelTopPx(it) {
  return it.cy + it.iconPx + GAUGE_GAP_PX + GAUGE_H_PX + LABEL_GAP_PX + it.gaugeDy;
}

function labelBoxPx(it, topPx, widthPx) {
  return {
    x0: it.cx - widthPx / 2, y0: topPx,
    x1: it.cx + widthPx / 2, y1: topPx + LABEL_LINE_PX,
  };
}

// Measured label widths in CSS pixels, keyed on the exact string drawn.
//
// WHY ONE ENTRY SERVES EVERY ZOOM. drawRobots runs inside the world transform,
// so ctx.measureText returns WORLD units; the font is set to
// `${LABEL_FONT_PX / scale}px`, and a glyph advance is proportional to the font
// size, so (world width) x scale is the CSS-pixel width at every scale. That
// linearity is a property of text layout, not an assumption about this font.
//
// WHAT IT COSTS. The reachable key set is one string per robot id plus the nine
// STATE_ABBREV values — 19 strings for the ten-robot fleet
// spawn_positions.yaml describes. After the first frame in which a robot
// appears or changes state, planning AND drawing cost zero measureText calls.
// The code this replaces called measureText twice per robot per frame: 20 calls
// per frame at 30 fps, 600/s, for a fleet whose label widths change a few times
// a minute. This is strictly cheaper than what was already shipping, which is
// why measuring is affordable at all.
const _labelWidthPxCache = new Map();
const LABEL_CACHE_MAX = 512;

// A webfont that has not finished loading measures as the fallback monospace,
// so a width cached during the first paint would be wrong for the rest of the
// session. Drop the cache once, when the font set settles. Guarded: document
// .fonts exists in no test environment here and in no older browser.
if (typeof document !== 'undefined' && document.fonts
    && document.fonts.ready && typeof document.fonts.ready.then === 'function') {
  document.fonts.ready.then(() => _labelWidthPxCache.clear());
}

// Returns measure(text) -> CSS px. The caller must have set ctx.font to
// `${LABEL_FONT_PX / scale}px ${LABEL_FONT_FAMILY}` in the world transform.
export function makeLabelMeasurer(ctx, scale) {
  return (text) => {
    if (!text) return 0;
    const hit = _labelWidthPxCache.get(text);
    if (hit !== undefined) return hit;
    const px = ctx.measureText(text).width * scale;
    // At MAX_SCALE the font is 0.45 user units. An engine that rounds a font
    // that small to zero would poison the cache for the whole session, so an
    // unusable measurement falls back to the nominal advance and is NOT cached
    // — the next frame at a saner zoom gets to measure again.
    if (!Number.isFinite(px) || px <= 0) {
      return text.length * LABEL_FONT_PX * FALLBACK_ADVANCE_EM;
    }
    if (_labelWidthPxCache.size >= LABEL_CACHE_MAX) _labelWidthPxCache.clear();
    _labelWidthPxCache.set(text, px);
    return px;
  };
}

// Plan every mark for every robot.
//
// Returns Map(robot_id -> {
//   iconBox, dotBox,          // px, ALWAYS drawn, reported but not reserved
//   gaugeRect, gaugeBox,      // px, the fillRect and its ink box; null if the
//                             //     robot reports no battery_level
//   gaugeForced,              // true when it is drawn overlapping regardless
//   gaugeDy,                  // px the gauge was pushed down to clear another
//   label: null | { tier, box, topPx, widthPx, idWidthPx, idText, abbrev,
//                   forced },
// })
//
// `measureLabelPx` is injected rather than taken from a canvas so the geometry
// can be exercised without one; drawRobots passes makeLabelMeasurer(ctx, scale)
// and src/__tests__/fleetMap.marks.test.js passes a monospace model.
//
// WHAT IS RESERVED AND WHAT IS NOT. The gauge and the label row are reserved:
// both are placeable, so a plan can keep them apart. The icon and the state dot
// are reported but not reserved, because neither can move or be dropped —
// reserving them would only push labels away from icons, which is a legibility
// judgement about drop rates that cannot be made in an environment where
// nothing renders. They are in the returned plan so a test can assert that
// every mark drawn is a mark the plan describes.
export function planRobotMarks(orderedEntries, scale, selectedRobotId, measureLabelPx) {
  const measure = typeof measureLabelPx === 'function'
    ? measureLabelPx
    : (text) => text.length * LABEL_FONT_PX * FALLBACK_ADVANCE_EM;

  const items = [];
  orderedEntries.forEach((robot) => {
    if (!robot || !robot.pose) return;
    const isSelected = robot.robot_id === selectedRobotId;
    const iconPx = isSelected ? ICON_SEL_PX : ICON_PX;
    const idText = `${robot.robot_id} `;
    const abbrev = STATE_ABBREV[robot.fsm_state] || UNKNOWN_ABBREV;
    items.push({
      id: robot.robot_id,
      isSelected,
      iconPx,
      reachPx: iconReachPx(iconPx, isSelected, robot.fsm_state),
      cx: robot.pose.x * scale,
      cy: -robot.pose.y * scale,
      idText,
      abbrev,
      idWidthPx: measure(idText),
      abbrevWidthPx: measure(abbrev),
      hasGauge: typeof robot.battery_level === 'number',
      gaugeDy: 0,
    });
  });

  const reserved = [];
  const plans = new Map();

  // PASS 1 — the marks that are always drawn, for every robot, before any
  // droppable one is placed.
  //
  // D-16(b): the battery gauge was in no plan at all. D-01 freed it from the
  // label — a robot that lost a label collision used to lose its charge reading
  // with it — and anchored it to the icon, but nothing then reserved the space
  // it occupies. So a nudged label could land on a neighbour's gauge, and two
  // robots within GAUGE_W_PX in x and GAUGE_H_PX in y drew their bars on top of
  // each other. Two overlaid 20x3 px bars are indistinguishable, which is worse
  // than a missing one: it reads as a valid charge belonging to the wrong
  // robot.
  //
  // The gauge is never dropped. When two would coincide the later one in draw
  // order steps DOWN by whole rows, staying centred under its own icon in x so
  // it cannot detach from the robot it describes. Three robots parked on the
  // depot therefore show three stacked bars instead of one bar and two lies.
  items.forEach((it) => {
    let gaugeRect = null;
    let gaugeBox = null;
    let gaugeForced = false;
    if (it.hasGauge) {
      gaugeRect = gaugeRectPx(it, 0);
      gaugeBox = grow(gaugeRect, GAUGE_STROKE_PX / 2);
      let attempts = 0;
      while (attempts < GAUGE_MAX_ATTEMPTS && collidesAny(reserved, gaugeBox)) {
        it.gaugeDy += LABEL_NUDGE_PX;
        attempts += 1;
        gaugeRect = gaugeRectPx(it, it.gaugeDy);
        gaugeBox = grow(gaugeRect, GAUGE_STROKE_PX / 2);
      }
      // The budget can run out — GAUGE_MAX_ATTEMPTS is capped low on purpose so
      // a bar never drifts far enough from its icon to be read as another
      // robot's. When it does, the gauge is still drawn (it is the one mark
      // that is never dropped) and the plan SAYS SO, so a caller or a test can
      // tell an unavoidable pile-up from a planner that did not try.
      gaugeForced = collidesAny(reserved, gaugeBox);
      reserved.push(gaugeBox);
    }
    it.plan = {
      iconBox: iconBoxPx(it),
      dotBox: dotBoxPx(it),
      gaugeRect,
      gaugeBox,
      gaugeDy: it.gaugeDy,
      gaugeForced,
      label: null,
    };
    plans.set(it.id, it.plan);
  });

  // PASS 2 — the droppable row: the id and the state abbreviation.
  //
  // D-16(c): STATE_ABBREV used to be drawn only inside `if (labelPlaced)`.
  // colors.js calls it "the COLOUR-BLIND-SAFE channel of the state encoding",
  // and D-01's own arithmetic shows that robots clustered at the depot lose
  // their labels — so the channel that exists for an operator who cannot rely
  // on the dot's hue vanished exactly when robots crowd, leaving state encoded
  // by hue alone for the one reader who cannot use hue. That is the coupling
  // D-01 removed from the gauge, reintroduced beside it.
  //
  // The row is placed in two tiers. 'excavator_01 RET' is tried first; if it
  // fits nowhere, the bare 'RET' is tried, and at the nominal advance that is
  // 16.2 px against 86.4 px, so it fits gaps the full label cannot. Only if
  // both fail is the row dropped, and the state is then still carried by the
  // dot. The id is the part an operator can recover by clicking the icon; the
  // state is not.
  items.forEach((it) => {
    const top0 = labelTopPx(it);
    const tiers = [
      { tier: 'full', widthPx: it.idWidthPx + it.abbrevWidthPx },
      { tier: 'abbrev', widthPx: it.abbrevWidthPx },
    ];
    let chosen = null;
    for (let t = 0; t < tiers.length && chosen === null; t += 1) {
      let topPx = top0;
      let box = labelBoxPx(it, topPx, tiers[t].widthPx);
      let attempts = 0;
      while (attempts < LABEL_MAX_ATTEMPTS && collidesAny(reserved, box)) {
        topPx += LABEL_NUDGE_PX;
        attempts += 1;
        box = labelBoxPx(it, topPx, tiers[t].widthPx);
      }
      if (!collidesAny(reserved, box)) {
        chosen = { tier: tiers[t].tier, widthPx: tiers[t].widthPx, box, topPx, forced: false };
      }
    }
    // The selected robot never loses its label: it is the one the operator
    // asked to look at, and orderRobotsForLabels puts it first so that it wins
    // its slot. It can still be forced — pass 1 reserved every gauge in the
    // fleet before this loop ran — and a forced box is flagged, because it is
    // the one box in `reserved` that may overlap another.
    if (chosen === null && it.isSelected) {
      const widthPx = it.idWidthPx + it.abbrevWidthPx;
      chosen = {
        tier: 'full', widthPx, box: labelBoxPx(it, top0, widthPx), topPx: top0, forced: true,
      };
    }
    if (chosen !== null) {
      reserved.push(chosen.box);
      it.plan.label = {
        tier: chosen.tier,
        box: chosen.box,
        topPx: chosen.topPx,
        widthPx: chosen.widthPx,
        idWidthPx: it.idWidthPx,
        idText: it.idText,
        abbrev: it.abbrev,
        forced: chosen.forced,
      };
    }
  });

  return plans;
}

export function drawRobots(ctx, robots, selectedRobotId, scale, now) {
  ctx.save();
  const ordered = orderRobotsForLabels(Object.values(robots), selectedRobotId);
  // The font has to be set BEFORE planning, not just before drawing: the
  // planner's collision window is now ctx.measureText on the strings this loop
  // will draw (D-16(a)), and measureText answers for whatever font is current.
  ctx.font = `${LABEL_FONT_PX / scale}px ${LABEL_FONT_FAMILY}`;
  const plans = planRobotMarks(
    ordered, scale, selectedRobotId, makeLabelMeasurer(ctx, scale),
  );

  ordered.forEach((robot) => {
    const { robot_id, robot_type, fsm_state, pose, battery_level } = robot;
    if (!pose) return;
    // Every PLACEABLE mark below is drawn from this plan, converted back from
    // px with (worldX = px/scale, worldY = -px/scale): the gauge from
    // plan.gaugeRect, the dot from plan.dotBox, the label row from
    // plan.label.box and the planner's own measured widths. Nothing here
    // recomputes an offset of its own, which is what makes "the reserved box
    // contains every drawn mark" a property of the code rather than a
    // coincidence between two constants that drifted apart twice (D-16(a)).
    // The icon triangle and its rings are the exception — they are anchored at
    // the robot and cannot move, so they read the same ICON_* constants the
    // plan's iconBox is built from.
    const plan = plans.get(robot_id);
    if (!plan) return;

    const { x, y, theta } = pose;
    const isSelected = robot_id === selectedRobotId;
    const color = TYPE_COLORS[robot_type] || '#e0e6f0';
    const baseSize = (isSelected ? ICON_SEL_PX : ICON_PX) / scale;
    // A-stale: dim robots whose telemetry has stopped, so a dead robot does not
    // keep drawing as a fully-live icon on the map.
    const staleAlpha = isStale(robot, now) ? 0.3 : 1;

    ctx.save();
    ctx.globalAlpha = staleAlpha;
    ctx.translate(x, y);

    // Selection ring
    if (isSelected) {
      ctx.beginPath();
      ctx.arc(0, 0, baseSize * 1.6, 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.lineWidth = SELECT_RING_PX / scale;
      ctx.globalAlpha = staleAlpha * (0.5 + 0.3 * Math.sin(now / 400));
      ctx.stroke();
      ctx.globalAlpha = staleAlpha;
    }

    // Working glow
    if (fsm_state === 'WORKING') {
      const glow = 6 + 4 * Math.sin(now / 300);
      ctx.shadowColor = color;
      ctx.shadowBlur = glow;
    }

    // Error ring
    if (fsm_state === 'ERROR') {
      ctx.beginPath();
      ctx.arc(0, 0, baseSize * 1.3, 0, Math.PI * 2);
      ctx.strokeStyle = '#ff4757';
      ctx.lineWidth = ERROR_RING_PX / scale;
      ctx.stroke();
    }

    // Recharging: lower opacity
    if (fsm_state === 'RECHARGING') {
      ctx.globalAlpha = staleAlpha * 0.5;
    }

    // Triangular arrow pointing in heading direction
    ctx.rotate(theta);
    ctx.beginPath();
    ctx.moveTo(baseSize, 0); // tip
    ctx.lineTo(-baseSize * 0.6, baseSize * 0.5);
    ctx.lineTo(-baseSize * 0.3, 0);
    ctx.lineTo(-baseSize * 0.6, -baseSize * 0.5);
    ctx.closePath();

    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = isSelected ? '#ffffff' : 'rgba(0,0,0,0.4)';
    ctx.lineWidth = ICON_STROKE_PX / scale;
    ctx.shadowBlur = 0;
    ctx.stroke();

    ctx.restore(); // undo translate + rotate

    // ---- D-01(a): FSM state dot ----
    //
    // FR-DASH-1 (docs/PRD.md:486-494) asks for icons coloured by type WITH a
    // state indicator coloured by FSM state. Only three of the nine states had
    // any map encoding: the WORKING glow, the ERROR ring and the RECHARGING
    // dim above. All three are kept — they are redundant reinforcement of the
    // states an operator needs to catch peripherally — and this dot adds the
    // remaining six.
    //
    // A SEPARATE MARK RATHER THAN RECOLOURING THE ICON, because STATE_COLORS
    // and TYPE_COLORS collide in three places: NAVIGATING and scout are both
    // #00d4ff, RETURNING and excavator are both #ffc107, RECHARGING and hauler
    // are both #00e676. Recolouring the icon would have destroyed the type
    // encoding the same PRD clause requires. "Cyan triangle plus green dot" is
    // unambiguous: scout, recharging.
    //
    // FILLED, not a ring: a 2 px annulus is sub-pixel once the map is zoomed
    // out, a filled disc is not.
    //
    // Drawn AFTER the icon's restore() on purpose. That puts it outside the
    // heading rotation — the dot must hold a fixed screen position relative to
    // the icon rather than orbit it — and outside the RECHARGING alpha halving,
    // so the state stays legible on a deliberately dimmed icon. It is still
    // subject to staleAlpha, because a stale robot's state is stale too.
    ctx.save();
    ctx.globalAlpha = staleAlpha;
    ctx.beginPath();
    ctx.arc(
      (plan.dotBox.x0 + plan.dotBox.x1) / (2 * scale),
      -(plan.dotBox.y0 + plan.dotBox.y1) / (2 * scale),
      STATE_DOT_R_PX / scale,
      0,
      Math.PI * 2,
    );
    ctx.fillStyle = STATE_COLORS[fsm_state] || '#e0e6f0';
    ctx.fill();
    // Outlined so the dot reads against terrain of any brightness, including
    // the near-black PSR floor and a saturated red heatmap cell.
    ctx.strokeStyle = 'rgba(0,0,0,0.6)';
    ctx.lineWidth = STATE_DOT_STROKE_PX / scale;
    ctx.stroke();
    ctx.restore();

    // ---- D-01(b) / D-16(c): the label row, from the plan ----
    //
    // The id keeps its own colour and the 3-character state abbreviation is
    // drawn beside it in STATE_COLORS. That abbreviation is the
    // colour-blind-safe half of the state encoding, and it is what separates
    // BIDDING from ASSIGNED for an operator who cannot rely on the dot's hue.
    //
    // D-16(c): it is no longer gated on the ID having been placed. When the
    // full row does not fit the planner falls back to a `tier: 'abbrev'` row
    // carrying the state alone, which is about a fifth as wide; only when even
    // that will not fit is the row dropped. So the channel that exists for the
    // reader who cannot use hue no longer disappears precisely when robots
    // cluster, which is when it is needed.
    //
    // Two fillText calls because a fillText has exactly one colour. textAlign
    // is 'left' and the pair is centred by hand off the PLANNED widths — not a
    // fresh measureText — so what is drawn is exactly the box the planner
    // reserved.
    if (plan.label) {
      const { tier, idText, abbrev, widthPx, idWidthPx } = plan.label;
      // px -> world. box.y0 is the row's top edge on screen, and textBaseline
      // 'top' draws downward from the anchor after the local scale(1, -1).
      const labelY = -plan.label.box.y0 / scale;
      const halfWidth = widthPx / (2 * scale);

      ctx.save();
      ctx.globalAlpha = staleAlpha;
      ctx.translate(x, labelY);
      ctx.scale(1, -1);
      ctx.font = `${LABEL_FONT_PX / scale}px ${LABEL_FONT_FAMILY}`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';

      if (tier === 'full') {
        ctx.fillStyle = isSelected ? '#ffffff' : 'rgba(224,230,240,0.6)';
        ctx.fillText(idText, -halfWidth, 0);
        ctx.fillStyle = STATE_COLORS[fsm_state] || '#e0e6f0';
        ctx.fillText(abbrev, -halfWidth + idWidthPx / scale, 0);
      } else {
        ctx.fillStyle = STATE_COLORS[fsm_state] || '#e0e6f0';
        ctx.fillText(abbrev, -halfWidth, 0);
      }
      ctx.restore();
    }

    // Wave2-A4: Per-robot battery overlay (horizontal bar under the icon).
    // Drawn in world space but sized in screen pixels via 1/scale.
    //
    // D-01(d): anchored to the ICON, not to the label, and no longer gated on
    // the label having been placed. It used to hang below the (possibly nudged)
    // label and inherit `labelPlaced`, so a robot that lost its label to a
    // collision silently lost its battery reading too. Arithmetic at the
    // DEFAULT framing, not just when zoomed out: DEFAULT_VIEW resolves to
    // 190 m x 170 m, so fitScale is about 4.3 px/m in a 900x800 pane; DEPOT and
    // RECHARGE_STATION are both at (-30, -100) with radii 10 m and 5 m, so
    // every robot parked or charging there sits within ~86 px of a neighbour —
    // inside one label width. FR-DASH-1(c)'s battery indicator disappeared
    // exactly when it mattered most. (Static argument from the constants in
    // worldConfig.js and above; not observed in a browser.)
    //
    // D-16(b): the rect comes from plan.gaugeRect, which the planner reserved
    // and may have stepped down to clear another robot's gauge. Nothing here
    // recomputes it.
    if (plan.gaugeRect) {
      const rect = plan.gaugeRect;
      const barW = (rect.x1 - rect.x0) / scale;
      const barH = (rect.y1 - rect.y0) / scale;
      const barX = rect.x0 / scale;
      // fillRect's positive height extends UPWARD inside the flipped world
      // transform, so the origin is the rect's LOWER screen edge: px y1.
      const barY = -rect.y1 / scale;
      const b = Math.max(0, Math.min(1, battery_level));
      let battColor;
      if (b > 0.5) battColor = '#00e676';
      else if (b > 0.2) battColor = '#ffc107';
      else battColor = '#ff4757';

      ctx.save();
      ctx.globalAlpha = staleAlpha;
      // Background
      ctx.fillStyle = 'rgba(20, 26, 42, 0.75)';
      ctx.fillRect(barX, barY, barW, barH);
      // Fill proportional to battery level
      ctx.fillStyle = battColor;
      ctx.fillRect(barX, barY, barW * b, barH);
      // Thin outline
      ctx.strokeStyle = 'rgba(224,230,240,0.35)';
      ctx.lineWidth = GAUGE_STROKE_PX / scale;
      ctx.strokeRect(barX, barY, barW, barH);
      ctx.restore();
    }
  });

  ctx.restore();
}

// Wave2-A4: Draw per-robot planned paths from nav_msgs/Path subscriptions.
// robotPaths is a map of robotId -> [{x, y}, ...] world coords.
function drawPlannedPaths(ctx, robots, robotPaths, scale) {
  if (!robotPaths || !robots) return;
  ctx.save();
  Object.entries(robotPaths).forEach(([robotId, path]) => {
    if (!Array.isArray(path) || path.length === 0) return;
    const robot = robots[robotId];
    if (!robot || !robot.pose) return;
    const color = TYPE_COLORS[robot.robot_type] || '#e0e6f0';

    ctx.beginPath();
    // Start from the robot's current position for visual continuity
    ctx.moveTo(robot.pose.x, robot.pose.y);
    path.forEach((pt) => {
      if (pt && typeof pt.x === 'number' && typeof pt.y === 'number') {
        ctx.lineTo(pt.x, pt.y);
      }
    });
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 1.2 / scale;
    ctx.setLineDash([5 / scale, 3 / scale]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  });
  ctx.restore();
}

function drawScaleBar(ctx, scale, canvasW, canvasH, dpr) {
  ctx.save();
  // Work in logical pixels with DPR scaling
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const barWorldLength = 50; // meters
  const barPixels = barWorldLength * scale;
  const x = 16;
  const y = canvasH - 20;
  const tickH = 6;

  ctx.strokeStyle = 'rgba(224,230,240,0.4)';
  ctx.fillStyle = 'rgba(224,230,240,0.4)';
  ctx.lineWidth = 1;

  // Horizontal bar
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + barPixels, y);
  ctx.stroke();

  // Left tick
  ctx.beginPath();
  ctx.moveTo(x, y - tickH);
  ctx.lineTo(x, y + tickH);
  ctx.stroke();

  // Right tick
  ctx.beginPath();
  ctx.moveTo(x + barPixels, y - tickH);
  ctx.lineTo(x + barPixels, y + tickH);
  ctx.stroke();

  // Label
  ctx.font = '10px JetBrains Mono, monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText('50 m', x + barPixels / 2, y - 8);

  ctx.restore();
}

// ---------- Wave2-A3: Selected-task highlight ----------

function drawSelectedTaskHighlight(ctx, robots, tasksById, selectedTaskId, scale, now) {
  if (!selectedTaskId || !tasksById) return;
  const task = tasksById[selectedTaskId];
  if (!task) return;

  // Locate the assigned robot if any; if not assigned yet, just draw a target marker.
  const robot = task.assigned_robot ? robots[task.assigned_robot] : null;
  const tx = task.target_x;
  const ty = task.target_y;
  const hasTarget = tx != null && ty != null && !(tx === 0 && ty === 0);

  ctx.save();

  if (robot && robot.pose) {
    const rx = robot.pose.x;
    const ry = robot.pose.y;
    const baseRadius = 14 / scale;
    const pulse = 0.5 + 0.5 * Math.sin(now / 280);
    const ringRadius = baseRadius * (1.0 + 0.6 * pulse);

    // Pulsing ring around the assigned robot
    ctx.beginPath();
    ctx.arc(rx, ry, ringRadius, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(0, 212, 255, ${0.35 + 0.5 * pulse})`;
    ctx.lineWidth = 2 / scale;
    ctx.stroke();

    // Dashed line from robot to task target
    if (hasTarget) {
      ctx.setLineDash([6 / scale, 4 / scale]);
      ctx.strokeStyle = 'rgba(0, 212, 255, 0.65)';
      ctx.lineWidth = 1.5 / scale;
      ctx.beginPath();
      ctx.moveTo(rx, ry);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // Always draw a crosshair on the target position itself for clarity
  if (hasTarget) {
    const armLen = 8 / scale;
    ctx.strokeStyle = 'rgba(0, 212, 255, 0.8)';
    ctx.lineWidth = 1.5 / scale;
    ctx.beginPath();
    ctx.moveTo(tx - armLen, ty);
    ctx.lineTo(tx + armLen, ty);
    ctx.moveTo(tx, ty - armLen);
    ctx.lineTo(tx, ty + armLen);
    ctx.stroke();

    // Outer pulse circle on the target
    const pulse2 = 0.5 + 0.5 * Math.sin(now / 350);
    ctx.beginPath();
    ctx.arc(tx, ty, (6 + 4 * pulse2) / scale, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(0, 212, 255, ${0.25 + 0.5 * pulse2})`;
    ctx.lineWidth = 1.5 / scale;
    ctx.stroke();
  }

  ctx.restore();
}

// ---------- FleetMap Component ----------

function FleetMap({
  robots,
  // D-02: the fused posterior snapshot and its liveness, both prepared by
  // App.jsx. `resourceReadings` — the raw per-reading ResourceMapUpdate list
  // this component used to splat — is deliberately no longer consumed here.
  // ResourceGraph.jsx still uses it for its time series, where per-reading data
  // is the right input.
  resourceMap,
  resourceMapStatus,
  selectedRobotId,
  onSelectRobot,
  heatmapVisible,
  onToggleHeatmap,
  // Wave2-A3: selected-task highlight inputs (optional)
  selectedTaskId,
  tasksById,
  // Wave2-A4: picker mode + planned path inputs
  pickerMode,
  pickerContext,
  robotPaths,
  onPickerResult,
}) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const lastFrameTimeRef = useRef(0);

  // Viewport state stored in refs for animation loop access (no re-render needed)
  const viewRef = useRef({ centerX: 0, centerY: 0, scale: 1 });
  // A-polish: explicit "have we framed the default view yet" flag. The old check
  // inferred this from scale===1 && center===(0,0), which is also a legitimate
  // user-chosen viewport.
  const viewInitializedRef = useRef(false);

  // Drag state
  const dragRef = useRef({ dragging: false, lastX: 0, lastY: 0 });

  // Mouse world coords for display
  const [mouseCoords, setMouseCoords] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  // D-02: the offscreen cell raster and the revision it was built from. A ref,
  // not state, because rebuilding it must not re-render React and the render
  // loop reads it directly.
  const rasterRef = useRef({
    canvas: null,
    ctx: null,
    image: null,
    revision: -1,
    width: 0,
    height: 0,
  });

  // D-02: age of the newest accepted posterior, for the legend. Sampled on a
  // 1 Hz interval rather than in the 30 fps render loop — the render loop is
  // canvas-only and must not push React state, and a snapshot arrives at
  // 0.5 Hz so second resolution is already finer than the source.
  const [mapAgeSec, setMapAgeSec] = useState(null);

  // Store latest props in refs so animation loop sees them without re-creating
  // Wave2-A3: also store selectedTaskId + tasksById for the highlight overlay
  // Wave2-A4: also store pickerMode + robotPaths for picker click + path draw
  const propsRef = useRef({
    robots,
    resourceMap,
    selectedRobotId,
    heatmapVisible,
    selectedTaskId,
    tasksById,
    pickerMode,
    pickerContext,
    robotPaths,
    onPickerResult,
  });
  propsRef.current = {
    robots,
    resourceMap,
    selectedRobotId,
    heatmapVisible,
    selectedTaskId,
    tasksById,
    pickerMode,
    pickerContext,
    robotPaths,
    onPickerResult,
  };

  // ---------- D-02: posterior age ticker ----------
  useEffect(() => {
    const tick = () => {
      const map = propsRef.current.resourceMap;
      setMapAgeSec(map ? (Date.now() - map.receivedAt) / 1000 : null);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // ---------- D-17: the certainty range the cells on screen actually occupy ----
  //
  // ResourceLegend draws certainty on its vertical axis and defaults to the
  // full 0..1 mapping, which is honest but mostly dead: at ALPHA_MIN 0.05 the
  // bottom of that axis composites to a delta of ~4/255 per channel over the
  // map backdrop, while the weakest evidence the shipped fleet can produce —
  // one reading from the 0.5 wt% scout at the edge of its footprint — is
  // certainty 0.5008. Half the swatch describes cells that cannot exist.
  //
  // The bound is NOT derivable inside the legend and must not be hardcoded: it
  // is a function of the sensor's noise_stddev, and ResourceMap.msg carries the
  // posterior and its prior, never the instrument. Measuring it off the
  // snapshot being drawn is strictly better than an RCDL-derived constant
  // because it self-corrects if the fleet changes sensors — and it is measured
  // HERE because this is the only component holding the snapshot.
  //
  // COST. One O(n) pass per accepted snapshot, n <= resource_map_max_marker_cells
  // (20000). The reducer produces a new object at resource_map_publish_rate
  // (0.5 Hz) and the 30 fps draw loop is a rAF loop outside React reading
  // propsRef, so `[resourceMap]` is the right key: this runs about once every
  // two seconds, not once a frame.
  //
  // Returning null (no cells, or a non-finite bound) leaves the legend on its
  // full-mapping default rather than on a half-computed axis.
  const certaintyBand = useMemo(() => {
    const variance = resourceMap && resourceMap.cellVariance;
    if (!variance || variance.length === 0) return null;
    const priorVariance = resourceMap.priorVariance;
    let min = Infinity;
    let max = -Infinity;
    for (let i = 0; i < variance.length; i++) {
      const c = varianceToCertainty(variance[i], priorVariance);
      if (c < min) min = c;
      if (c > max) max = c;
    }
    return Number.isFinite(min) && Number.isFinite(max) ? { min, max } : null;
  }, [resourceMap]);

  // ---------- Canvas sizing ----------
  const updateCanvasSize = useCallback(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = container.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    // A-polish: frame the PSR + depot working area by default instead of the
    // whole 500x500 m world, which left the fleet as a tiny cluster in the
    // corner. Zooming out to the full world is still one wheel gesture away.
    const pad = 1 + PADDING_RATIO * 2;
    const sx = w / (DEFAULT_VIEW.WIDTH * pad);
    const sy = h / (DEFAULT_VIEW.HEIGHT * pad);
    const fitScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, Math.min(sx, sy)));

    // Only frame on the first sizing pass — never stomp the operator's viewport.
    if (!viewInitializedRef.current) {
      viewRef.current = {
        centerX: DEFAULT_VIEW.CENTER_X,
        centerY: DEFAULT_VIEW.CENTER_Y,
        scale: fitScale,
      };
      viewInitializedRef.current = true;
    }
  }, []);

  // ---------- Resize observer ----------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    updateCanvasSize();

    const observer = new ResizeObserver(() => {
      updateCanvasSize();
    });
    observer.observe(container);

    return () => observer.disconnect();
  }, [updateCanvasSize]);

  // ---------- Animation loop ----------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let running = true;

    function render(timestamp) {
      if (!running) return;

      // Throttle to ~30 fps
      if (timestamp - lastFrameTimeRef.current < FRAME_INTERVAL) {
        animFrameRef.current = requestAnimationFrame(render);
        return;
      }
      lastFrameTimeRef.current = timestamp;

      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const canvasW = canvas.width / dpr;
      const canvasH = canvas.height / dpr;

      if (canvasW === 0 || canvasH === 0) {
        animFrameRef.current = requestAnimationFrame(render);
        return;
      }

      const { centerX, centerY, scale } = viewRef.current;
      const {
        robots: robs,
        resourceMap: rMap,
        selectedRobotId: selId,
        heatmapVisible: hmVis,
        // Wave2-A3: highlight inputs
        selectedTaskId: selTaskId,
        tasksById: tById,
        // Wave2-A4: path overlay input
        robotPaths: rPaths,
      } = propsRef.current;
      const now = Date.now();

      // Reset transform and clear
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // (a) Background — lunar terrain texture
      ctx.fillStyle = '#0a0e1a';
      ctx.fillRect(0, 0, canvasW, canvasH);

      // Draw terrain image in world space
      ctx.save();
      worldToCanvas(ctx, centerX, centerY, scale, canvasW, canvasH);
      const terrain = getLunarTerrain();
      ctx.save();
      ctx.translate(WORLD.X_MIN, WORLD.Y_MAX); // upper-left in world
      ctx.scale(WORLD.WIDTH / terrain.width, -WORLD.HEIGHT / terrain.height);
      ctx.drawImage(terrain, 0, 0);
      ctx.restore();
      ctx.restore();

      // (l) Grid labels in screen space (before world transform)
      drawGridLabels(ctx, centerX, centerY, scale, canvasW, canvasH);

      // Apply world transform
      ctx.save();
      worldToCanvas(ctx, centerX, centerY, scale, canvasW, canvasH);

      // (b) Grid
      drawGrid(ctx, scale);

      // (b2) Crater outlines
      drawCraterOutlines(ctx, scale);

      // (c) PSR zones
      drawPSRZones(ctx, scale);

      // (d) Resource heatmap — the orchestrator's fused posterior.
      //
      // NO SILENT FALLBACK. When no snapshot has arrived, nothing is drawn and
      // ResourceLegend says why. The alternative — quietly reverting to the raw
      // per-reading splats — would put a plausible picture on screen that is
      // not the map the orchestrator holds, and an operator would have no way
      // to tell which one they were looking at. Same reasoning as the
      // opaque-blue RViz2 fallback colour in D-08: make the failure visibly
      // wrong rather than invisibly substituted.
      if (hmVis && rMap) {
        const raster = buildPosteriorRaster(rasterRef.current, rMap);
        if (raster) {
          drawPosteriorRaster(ctx, raster, rMap);
        }
      }

      // (e) Ice deposit zones
      drawIceDeposits(ctx, scale);

      // (f) Depot
      drawDepot(ctx, scale);

      // (g) Recharge station
      drawRechargeStation(ctx, scale);

      // (h) Rock obstacles
      drawRocks(ctx, scale);

      // (i) Prospect waypoints
      drawProspectWaypoints(ctx, scale);

      // (i2) Wave2-A4: planned paths — drawn under robots so arrows stay on top
      if (robs && rPaths) {
        drawPlannedPaths(ctx, robs, rPaths, scale);
      }

      // (j) Robots
      if (robs) {
        drawRobots(ctx, robs, selId, scale, now);
      }

      // (j2) Wave2-A3: selected-task highlight overlay
      if (selTaskId && tById && robs) {
        drawSelectedTaskHighlight(ctx, robs, tById, selTaskId, scale, now);
      }

      ctx.restore(); // restore world transform

      // (k) Scale bar in screen space
      drawScaleBar(ctx, scale, canvasW, canvasH, dpr);

      animFrameRef.current = requestAnimationFrame(render);
    }

    animFrameRef.current = requestAnimationFrame(render);

    return () => {
      running = false;
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, []);

  // ---------- Screen <-> World coordinate conversion ----------
  const screenToWorld = useCallback((screenX, screenY) => {
    const canvas = canvasRef.current;
    if (!canvas) return { wx: 0, wy: 0 };
    const dpr = window.devicePixelRatio || 1;
    const canvasW = canvas.width / dpr;
    const canvasH = canvas.height / dpr;
    const { centerX, centerY, scale } = viewRef.current;

    const wx = (screenX - canvasW / 2) / scale + centerX;
    const wy = -(screenY - canvasH / 2) / scale + centerY; // flip Y
    return { wx, wy };
  }, []);

  // ---------- Interaction: Pan ----------
  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return; // left button only
    const rect = canvasRef.current.getBoundingClientRect();
    dragRef.current = {
      dragging: true,
      lastX: e.clientX - rect.left,
      lastY: e.clientY - rect.top,
    };
    setIsDragging(true);
  }, []);

  const handleMouseMove = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    // Update hover coords
    const { wx, wy } = screenToWorld(sx, sy);
    setMouseCoords({ x: wx.toFixed(1), y: wy.toFixed(1) });

    // Pan if dragging
    if (dragRef.current.dragging) {
      const dx = sx - dragRef.current.lastX;
      const dy = sy - dragRef.current.lastY;
      const { scale } = viewRef.current;
      viewRef.current.centerX -= dx / scale;
      viewRef.current.centerY += dy / scale; // flip Y
      dragRef.current.lastX = sx;
      dragRef.current.lastY = sy;
    }
  }, [screenToWorld]);

  const handleMouseUp = useCallback(() => {
    dragRef.current.dragging = false;
    setIsDragging(false);
  }, []);

  const handleMouseLeave = useCallback(() => {
    dragRef.current.dragging = false;
    setIsDragging(false);
    setMouseCoords(null);
  }, []);

  // ---------- Interaction: Zoom ----------
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    // World position under cursor before zoom
    const { wx, wy } = screenToWorld(sx, sy);

    // Apply zoom
    const factor = e.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
    const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, viewRef.current.scale * factor));
    viewRef.current.scale = newScale;

    // Adjust center so world point under cursor stays put
    const dpr = window.devicePixelRatio || 1;
    const canvasW = canvas.width / dpr;
    const canvasH = canvas.height / dpr;
    viewRef.current.centerX = wx - (sx - canvasW / 2) / newScale;
    viewRef.current.centerY = wy + (sy - canvasH / 2) / newScale;
  }, [screenToWorld]);

  // Attach wheel listener with passive:false for preventDefault
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  // ---------- Interaction: Click to select robot ----------
  const handleClick = useCallback((e) => {
    // Ignore if we just panned
    if (dragRef.current.lastDragDistance > 5) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    // Wave2-A4: Picker mode short-circuit — treat this click as a target pick
    // and skip the robot-selection logic entirely.
    const { pickerMode: pMode, onPickerResult: pCb } = propsRef.current;
    if (pMode) {
      const { wx: pwx, wy: pwy } = screenToWorld(sx, sy);
      if (typeof pCb === 'function') {
        pCb({ x: pwx, y: pwy });
      }
      return;
    }

    const { robots: robs } = propsRef.current;
    if (!robs) return;

    const { scale } = viewRef.current;
    const hitRadiusWorld = ROBOT_HIT_RADIUS / scale;

    let closest = null;
    let closestDist = Infinity;

    const { wx, wy } = screenToWorld(sx, sy);

    Object.values(robs).forEach((robot) => {
      if (!robot.pose) return;
      const dx = robot.pose.x - wx;
      const dy = robot.pose.y - wy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < hitRadiusWorld && dist < closestDist) {
        closest = robot.robot_id;
        closestDist = dist;
      }
    });

    onSelectRobot(closest);
  }, [onSelectRobot, screenToWorld]);

  // Track drag distance to distinguish clicks from drags
  const handleMouseDownTrack = useCallback((e) => {
    dragRef.current.startX = e.clientX;
    dragRef.current.startY = e.clientY;
    dragRef.current.lastDragDistance = 0;
    handleMouseDown(e);
  }, [handleMouseDown]);

  const handleMouseMoveTrack = useCallback((e) => {
    if (dragRef.current.dragging && dragRef.current.startX !== undefined) {
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      dragRef.current.lastDragDistance = Math.sqrt(dx * dx + dy * dy);
    }
    handleMouseMove(e);
  }, [handleMouseMove]);

  // Wave2-A4: Root class list — adds picker-mode class for crosshair cursor.
  const rootClass = [
    'fleet-map',
    isDragging ? 'fleet-map--dragging' : '',
    pickerMode ? 'fleet-map--picking' : '',
  ].filter(Boolean).join(' ');

  // Wave2-A4: Banner text for the active picker
  const pickerBanner = pickerMode === 'inject_task'
    ? 'Click map to set task target'
    : pickerMode === 'send_to_location'
      ? `Click map to send ${pickerContext?.robotId || 'robot'}`
      : null;

  return (
    <div
      ref={containerRef}
      className={rootClass}
    >
      <canvas
        ref={canvasRef}
        className="fleet-map__canvas"
        onMouseDown={handleMouseDownTrack}
        onMouseMove={handleMouseMoveTrack}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
      />

      {mouseCoords && (
        <div className="fleet-map__coords">
          X: {mouseCoords.x} m &nbsp; Y: {mouseCoords.y} m
        </div>
      )}

      {/* Wave2-A4: Picker mode banner */}
      {pickerBanner && (
        <div className="fleet-map__picker-banner">
          {pickerBanner}
        </div>
      )}

      <ResourceLegend
        heatmapVisible={heatmapVisible}
        onToggleHeatmap={onToggleHeatmap}
        resourceMapStatus={resourceMapStatus}
        mapAgeSec={mapAgeSec}
        observedCells={resourceMap ? resourceMap.cellIndex.length : 0}
        totalObservations={resourceMap ? resourceMap.totalObservations : 0}
        certaintyBand={certaintyBand}
      />
    </div>
  );
}

export default FleetMap;
