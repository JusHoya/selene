import React, { useRef, useState, useEffect, useCallback, useMemo } from 'react';
import { iceConcentrationColor } from '../utils/colors';
import './ResourceGraph.css';

// ---------- Constants ----------
const FRAME_INTERVAL = 1000 / 30; // 30 fps
const MIN_NODE_RADIUS = 4;
const MAX_NODE_RADIUS = 30;
const PROXIMITY_THRESHOLD = 30; // meters — readings within this distance get an edge

// A-polish: LEGIBILITY cap on drawn edges.
//
// Every pair of readings within PROXIMITY_THRESHOLD got an edge, which is
// ~16,750 edges at the 500-reading cap. That washes the view into a white
// hairball you cannot read anything out of. This is NOT a performance fix: in a
// browser session on 2026-07-29 this view measured 131 FPS mean (p95 12.2 ms,
// max 42.4 ms) with the full edge set at "Readings: 500 / Connections: 16751",
// so the full graph rendered fine and was merely unreadable. That measurement
// was taken by the reviewer against a synthetic feed, not by this change's
// author, and has not been repeated since the cap was added. Only the
// strongest-similarity edges are kept; the stats overlay reports both numbers
// so the view is not passed off as the complete graph.
const MAX_DRAWN_EDGES = 900;
const REPULSION_STRENGTH = 800;
const SPRING_STRENGTH = 0.005;
const IDEAL_EDGE_LENGTH = 80;
const CENTER_GRAVITY = 0.003;
const DAMPING = 0.92;
const MIN_SCALE = 0.2;
const MAX_SCALE = 5;
const ZOOM_FACTOR = 1.1;

// ---------- Helpers ----------

/** Map ice_concentration (0–10) to a node radius in pixels */
function nodeRadius(concentration) {
  const t = Math.min(concentration / 10, 1);
  return MIN_NODE_RADIUS + t * (MAX_NODE_RADIUS - MIN_NODE_RADIUS);
}

// Opacity of a reading node — a CONSTANT, deliberately, as of 2026-07-31.
//
// WHAT WAS HERE:
//     /** Map sensor_uncertainty (0–1) to alpha */
//     Math.max(0.15, Math.min(1.0, 1.0 - uncertainty * 0.8))
// and it had both of D-02's defects, in the view one header click from the
// fleet map, untouched while D-02 was closed against FleetMap.
//
// 1. THE AXIS WAS INERT. `sensor_uncertainty` arrives from
//    ResourceMapUpdate (App.jsx:154). ProspectSkill averages the sigmas its
//    HAL sensor reports (prospect.py:136-143) and agent_node drops any
//    reading whose sigma is non-finite or <= 0 (agent_node.py:1349-1369), so
//    what reaches this function is the RCDL's noise_stddev — and
//    `noise_stddev: 0.5` in selene_hal/config/scout.yaml:16 is the ONLY one
//    declared on a scalar_field sensor anywhere in the tree. Every node
//    therefore drew at 1 - 0.5*0.8 = 0.6, forever. That is exactly the
//    "opacity axis carries no information" defect D-02 was opened for.
// 2. THE UNITS WERE WRONG. The docstring called the input a 0–1 fraction; it
//    is a standard deviation in wt%, unbounded above. A fleet with
//    `noise_stddev: 2.0` would have clamped every node to alpha 0.15 and made
//    the whole graph nearly invisible — the same fraction-vs-unit confusion
//    as D-06 break 1 (hopper kilograms published into a 0–1 field).
//
// REMOVED RATHER THAN REPOINTED AT THE POSTERIOR. This view is deliberately
// the per-READING picture: individual samples, their spatial proximity and
// their agreement. The fused posterior — where a real per-cell confidence
// exists — is the fleet map's raster (D-02), and pulling state.resourceMap in
// here to look each reading up would make this a second, worse heatmap. A
// raw reading carries no confidence to encode, so the honest thing is not to
// pretend there is an axis.
//
// 0.6 is EXACTLY what the old expression produced under the shipped RCDL, so
// nothing on this screen changes today. If a fleet ever ships scouts with
// differing noise_stddev, restore a modulation in the correct units (sigma in
// wt%, not a fraction) rather than reinstating the line above.
const NODE_ALPHA = 0.6;

/** Euclidean distance between two world-space points */
function worldDist(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Build edge list from readings based on spatial proximity.
 * Returns { edges, totalCandidates } where `edges` is capped to the strongest
 * MAX_DRAWN_EDGES by similarity (ties broken by shorter separation) and
 * `totalCandidates` is how many pairs actually qualified.
 */
export function computeEdges(readings, maxEdges = MAX_DRAWN_EDGES) {
  const candidates = [];
  for (let i = 0; i < readings.length; i++) {
    for (let j = i + 1; j < readings.length; j++) {
      const dist = worldDist(readings[i].location, readings[j].location);
      if (dist <= PROXIMITY_THRESHOLD) {
        // Similarity: 1.0 when concentrations are identical, 0.0 when 10 apart
        const concDiff = Math.abs(
          readings[i].ice_concentration - readings[j].ice_concentration
        );
        const similarity = Math.max(0, 1 - concDiff / 10);
        candidates.push({ i, j, similarity, worldDist: dist });
      }
    }
  }
  const totalCandidates = candidates.length;
  if (totalCandidates <= maxEdges) {
    return { edges: candidates, totalCandidates };
  }
  candidates.sort((a, b) => {
    if (b.similarity !== a.similarity) return b.similarity - a.similarity;
    return a.worldDist - b.worldDist;
  });
  return { edges: candidates.slice(0, maxEdges), totalCandidates };
}

/**
 * Rebuild the simulation node table from `readings`, BY IDENTITY.
 *
 * Exported so the invariant below can be exercised headlessly — there is no way
 * to assert it through the rendered component, because it is a property of a
 * ref the loop reads, not of anything in the DOM.
 *
 * THE INVARIANT, and it is CONSTRUCTED here rather than maintained elsewhere:
 *   for every i,  result[i].reading === readings[i]
 *
 * WHAT THIS REPLACES, and why counting was not good enough. The previous version
 * kept a `readingsCountRef` and reasoned about the DELTA in array length:
 *
 *     const newReadings = readings.slice(0, readings.length - prevCount);
 *     nodesRef.current = [...added, ...existing];        // growth path
 *     readings.forEach((r, i) => { nodes[i].reading = r; });  // unchanged path
 *
 * Both branches are wrong in a way no rendering test could see:
 *
 *   (a) AT THE CAP. `resourceReadings` is capped at MAX_READINGS = 500 and
 *       prepends, so once it is full the LENGTH STOPS CHANGING while the
 *       contents keep shifting by one on every arrival. The delta is 0, so the
 *       "unchanged" branch ran and re-pointed node[i].reading by INDEX — every
 *       node silently adopted a different reading while keeping its settled
 *       position, size and colour. Tooltips, radii and hues stopped
 *       corresponding to anything, permanently and silently. It needs 500
 *       readings and the shipped survey produces about ten, so this was latent
 *       — which is precisely how this repository's previous "wired but never
 *       called" defects survived review.
 *   (b) AT THE 499->500 TRANSITION with two readings landing in one commit, the
 *       delta is 1 while two were prepended, so nodes[k].reading !== readings[k]
 *       until the next arrival happened to re-sync it.
 *   (c) IN THE NEGATIVE DIRECTION. If the array ever shrank to a non-zero
 *       length, `slice(0, negative)` returns [] and the stale nodes were kept
 *       while the count shrank. Unreachable today (the only shrink is RESET,
 *       which goes to exactly 0) and deliberately not relied upon.
 *
 * `clientSeq` is minted by the reducer (hooks/useFleetState.js) and is the only
 * stable name a reading has. A reading without one gets a fresh node every call
 * rather than matching some other node's undefined key — that direction loses
 * position stability, which is cosmetic, instead of mis-binding data, which is
 * the defect above.
 *
 * `rand` is injectable so a test can pin placement deterministically.
 */
export function reconcileNodes(prevNodes, readings, centerX, centerY, rand = Math.random) {
  const byKey = new Map();
  (prevNodes || []).forEach((n) => {
    const key = n && n.reading ? n.reading.clientSeq : undefined;
    if (typeof key === 'number') byKey.set(key, n);
  });
  // Snapshot of the STARTING condition, not of the loop's progress: a cold start
  // scatters the whole first batch on a ring, and every later arrival is placed
  // near the existing cloud so it does not fly in from the far side of the view.
  const cold = byKey.size === 0;

  return readings.map((r, idx) => {
    const kept = typeof r.clientSeq === 'number' ? byKey.get(r.clientSeq) : undefined;
    if (kept) {
      // Position, velocity and therefore the settled layout survive. Only the
      // payload pointer is refreshed, so a re-published reading updates in place.
      kept.reading = r;
      return kept;
    }
    if (cold) {
      const angle = (idx / Math.max(readings.length, 1)) * Math.PI * 2;
      const spread = 120 + rand() * 80;
      return {
        x: centerX + Math.cos(angle) * spread + (rand() - 0.5) * 40,
        y: centerY + Math.sin(angle) * spread + (rand() - 0.5) * 40,
        vx: 0,
        vy: 0,
        reading: r,
      };
    }
    return {
      x: centerX + (rand() - 0.5) * 80,
      y: centerY + (rand() - 0.5) * 80,
      vx: 0,
      vy: 0,
      reading: r,
    };
  });
}

// ---------- Canvas Drawing ----------

// `time` was a parameter here and in drawCentralGlow's `w`/`h`: declared,
// passed on every frame, read by neither. Removed rather than left, because
// this repository tracks that species of dead declaration and a reader has no
// way to tell an unused parameter from a forgotten animation.
function drawBackground(ctx, w, h) {
  // Subtle radial gradient from center
  const grad = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.6);
  grad.addColorStop(0, 'rgba(0, 20, 40, 0.15)');
  grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  // Faint grid dots
  ctx.fillStyle = 'rgba(255, 255, 255, 0.02)';
  const spacing = 40;
  for (let x = spacing; x < w; x += spacing) {
    for (let y = spacing; y < h; y += spacing) {
      ctx.fillRect(x - 0.5, y - 0.5, 1, 1);
    }
  }
}

function drawEdges(ctx, nodes, edges, time, offsetX, offsetY, scale, selectedSeq) {
  ctx.save();
  edges.forEach((edge) => {
    const a = nodes[edge.i];
    const b = nodes[edge.j];
    // `edges` and `nodes` are two views of one array and are now written
    // together, in one effect, after both are rebuilt — so a missing entry
    // should be impossible. The guard stays because the CONSEQUENCE of being
    // wrong about that is not a bad frame, it is a permanently frozen canvas:
    // an uncaught throw here used to skip the trailing requestAnimationFrame
    // and nothing in the component could ever restart the loop. This is a
    // genuine transient skip, not a widened tolerance — a dropped edge for one
    // frame is invisible; a dead loop is the operator's whole complaint.
    if (!a || !b) return;
    const ax = (a.x + offsetX) * scale;
    const ay = (a.y + offsetY) * scale;
    const bx = (b.x + offsetX) * scale;
    const by = (b.y + offsetY) * scale;

    // Compared by IDENTITY, not by index. `selectedSeq` names a reading; the
    // index it happens to sit at changes on every arrival, because
    // resourceReadings prepends.
    const isConnectedToSelected =
      selectedSeq !== null
      && (a.reading.clientSeq === selectedSeq || b.reading.clientSeq === selectedSeq);

    // Base alpha from similarity
    let alpha = 0.05 + edge.similarity * 0.2;

    // Pulse animation — subtle oscillation
    const pulse = 0.5 + 0.5 * Math.sin(time / 1200 + edge.i * 0.3 + edge.j * 0.7);
    alpha += pulse * 0.05;

    if (isConnectedToSelected) {
      alpha = Math.min(alpha * 3, 0.8);
    }

    const thickness = (0.5 + edge.similarity * 2.0) * scale;

    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.strokeStyle = isConnectedToSelected
      ? `rgba(0, 212, 255, ${alpha})`
      : `rgba(180, 220, 255, ${alpha})`;
    ctx.lineWidth = thickness;
    ctx.stroke();
  });
  ctx.restore();
}

function drawCentralGlow(ctx, nodes, offsetX, offsetY, scale) {
  if (nodes.length === 0) return;

  // Find the highest-concentration cluster center (weighted centroid)
  let totalWeight = 0;
  let cx = 0;
  let cy = 0;
  nodes.forEach((node) => {
    const weight = node.reading.ice_concentration * node.reading.ice_concentration;
    cx += ((node.x + offsetX) * scale) * weight;
    cy += ((node.y + offsetY) * scale) * weight;
    totalWeight += weight;
  });
  if (totalWeight === 0) return;
  cx /= totalWeight;
  cy /= totalWeight;

  // Find peak concentration for glow intensity
  const peak = Math.max(...nodes.map((n) => n.reading.ice_concentration));
  const intensity = Math.min(peak / 10, 1);

  const glowRadius = 100 + intensity * 150;
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius);
  grad.addColorStop(0, `rgba(0, 212, 255, ${0.08 * intensity})`);
  grad.addColorStop(0.5, `rgba(0, 180, 220, ${0.03 * intensity})`);
  grad.addColorStop(1, 'rgba(0, 0, 0, 0)');

  ctx.save();
  ctx.fillStyle = grad;
  ctx.fillRect(cx - glowRadius, cy - glowRadius, glowRadius * 2, glowRadius * 2);
  ctx.restore();
}

function drawNodes(ctx, nodes, time, offsetX, offsetY, scale, hoveredSeq, selectedSeq) {
  ctx.save();
  nodes.forEach((node, idx) => {
    const { reading } = node;
    const x = (node.x + offsetX) * scale;
    const y = (node.y + offsetY) * scale;
    const r = nodeRadius(reading.ice_concentration) * scale;
    const alpha = NODE_ALPHA;
    // By identity — see the note in drawEdges. A null seq matches nothing,
    // which is also the correct behaviour once a selected reading has aged out
    // past the 500-cap: the ring disappears rather than jumping to a stranger.
    const isHovered = hoveredSeq !== null && reading.clientSeq === hoveredSeq;
    const isSelected = selectedSeq !== null && reading.clientSeq === selectedSeq;
    const isHighConcentration = reading.ice_concentration > 5;

    // Glow for high-concentration nodes
    if (isHighConcentration) {
      const glowIntensity = (reading.ice_concentration - 5) / 5; // 0–1
      const pulse = 0.7 + 0.3 * Math.sin(time / 600 + idx * 1.1);
      const glowSize = r * (2.5 + pulse * 1.0);

      ctx.save();
      const grad = ctx.createRadialGradient(x, y, r * 0.3, x, y, glowSize);
      const glowColor = iceConcentrationColor(reading.ice_concentration, 0.25 * glowIntensity * pulse);
      grad.addColorStop(0, glowColor);
      grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(x, y, glowSize, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // Main node circle
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = iceConcentrationColor(reading.ice_concentration, alpha);
    ctx.fill();

    // Inner highlight — brighter center for depth
    const innerGrad = ctx.createRadialGradient(x - r * 0.2, y - r * 0.2, 0, x, y, r);
    innerGrad.addColorStop(0, `rgba(255, 255, 255, ${0.15 * alpha})`);
    innerGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = innerGrad;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();

    // Selection / hover ring
    if (isSelected || isHovered) {
      ctx.beginPath();
      ctx.arc(x, y, r + 3 * scale, 0, Math.PI * 2);
      ctx.strokeStyle = isSelected
        ? 'rgba(255, 255, 255, 0.9)'
        : 'rgba(255, 255, 255, 0.5)';
      ctx.lineWidth = (isSelected ? 2 : 1.5) * scale;
      ctx.stroke();
    }
  });
  ctx.restore();
}

// ---------- Component ----------

function ResourceGraph({ readings, droppedReadings = 0, onClose }) {
  // THE CANVAS AND ITS CONTAINER ARE STATE, NOT REFS, AND THAT IS THE WHOLE
  // POINT OF THIS COMPONENT'S REPAIR.
  //
  // WHAT WAS BROKEN. These were `useRef(null)` and the three effects below keyed
  // off `[updateCanvasSize]`, `[]` and `[handleWheel]` respectively — none of
  // which can ever change again after the first commit. The empty-state early
  // return at the bottom of this function renders NO <canvas> and attaches NO
  // container ref, and `readings` is `[]` on every page load (the reducer's
  // initial state). So on the commit the operator actually hits, all three
  // effects ran, read a null ref, and returned. When readings finally arrived
  // and the canvas mounted, NOTHING RE-RAN: the render loop was never scheduled,
  // updateCanvasSize never ran, and the canvas kept its default 300x150 backing
  // store while the header, legend and stats panel updated with real numbers
  // over a black rectangle. That is the operator's report, exactly.
  //
  // The same defect fired a second way. A rosbridge reconnect dispatches RESET,
  // resourceReadings goes back to [], this component unmounts its canvas, and
  // when readings resume React mounts a NEW canvas element while the loop keeps
  // drawing into the DETACHED one it captured on the first commit.
  //
  // FleetMap.jsx has the identical loop and no empty-state early return, which
  // is exactly why the fleet map works and this view did not.
  //
  // WHY ELEMENT IDENTITY AND NOT `readings.length > 0` IN THE DEPS. Adding a
  // readings guard fixes the empty-mount case and leaves the canvas-REPLACEMENT
  // case broken, because it keys the loop on something merely correlated with
  // the invariant. The invariant is "the loop is attached to the canvas that is
  // in the DOM". React calls a callback ref with the element on attach and with
  // null on detach, so these two state values ARE that invariant, and every
  // effect that touches the canvas now lists the element it touches.
  const [containerEl, setContainerEl] = useState(null);
  const [canvasEl, setCanvasEl] = useState(null);

  const animFrameRef = useRef(null);
  const lastFrameRef = useRef(0);

  // Simulation state held in refs for the animation loop
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);
  // One-shot guard so a recurring throw inside the loop cannot flood the console
  // at 30 Hz. Deliberately never reset: a second, different fault after the
  // first would be silent, and that is the accepted cost of not shipping a
  // console flood. The first message names the loop and carries the stack.
  const loopErrorLoggedRef = useRef(false);

  // View transform
  const viewRef = useRef({ offsetX: 0, offsetY: 0, scale: 1 });
  // `startX`/`startY` were written on every mousedown and read by nothing; the
  // pan-vs-click decision uses the accumulated `distance` instead. Removed
  // rather than left as two more declared-and-never-read fields.
  const dragRef = useRef({ dragging: false, lastX: 0, lastY: 0, distance: 0 });

  // Interactive state, keyed by the reading's stable clientSeq rather than by
  // its position in `readings`. THE ARRAY PREPENDS: with positional indices the
  // white selection ring, the cyan "connected to selected" edges and the hover
  // ring all silently moved to a different reading every time any scout finished
  // a waypoint, with no operator action.
  const [hoveredSeq, setHoveredSeq] = useState(null);
  const [selectedSeq, setSelectedSeq] = useState(null);
  const [tooltip, setTooltip] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  const hoveredRef = useRef(null);
  const selectedRef = useRef(null);
  hoveredRef.current = hoveredSeq;
  selectedRef.current = selectedSeq;

  // ---------- Compute edges synchronously so stats are always current ----------
  // The memo stays: the stats block below needs edges.length and
  // totalCandidates during RENDER. What is gone is the assignment of
  // `edgesRef.current` here — see the effect immediately below.
  const { edges, totalCandidates } = useMemo(
    () => (readings && readings.length > 0
      ? computeEdges(readings)
      : { edges: [], totalCandidates: 0 }),
    [readings]
  );

  // ---------- Rebuild the two refs the loop reads, TOGETHER ----------
  //
  // `edgesRef.current = edges` used to be a bare assignment during RENDER while
  // `nodesRef.current` was grown in this passive effect, which runs AFTER the
  // commit. Any frame landing in that window saw an edge list indexing a node
  // that did not exist yet and threw a TypeError inside the rAF callback — and
  // because the re-schedule was the last statement of the loop body, ONE throw
  // killed the loop permanently with nothing left to restart it. Driving the
  // real reducer and the real computeEdges over the shipped ten-waypoint survey,
  // 9 of the 10 arrivals published an edge set indexing a node the effect had
  // not built yet; only the first arrival was safe.
  //
  // Writing both refs in one passive effect, nodes first, removes the window
  // rather than tolerating it. The defensive guards in drawEdges and in the
  // attraction loop are the second layer, not the fix.
  useEffect(() => {
    if (!readings || readings.length === 0) {
      nodesRef.current = [];
      edgesRef.current = [];
      return;
    }

    // Fallbacks are for the commit BEFORE the callback ref has reported the
    // element (React attaches refs during commit, but the state update that
    // carries the element is a separate render). reconcileNodes is idempotent,
    // so the follow-up run with the real canvas keeps every position it just
    // chose — the fallback only affects where a cold start scatters.
    const w = canvasEl ? canvasEl.clientWidth || 800 : 800;
    const h = canvasEl ? canvasEl.clientHeight || 600 : 600;

    const prev = nodesRef.current;
    let cx = w / 2;
    let cy = h / 2;
    if (prev.length > 0) {
      cx = prev.reduce((s, n) => s + n.x, 0) / prev.length;
      cy = prev.reduce((s, n) => s + n.y, 0) / prev.length;
    }

    nodesRef.current = reconcileNodes(prev, readings, cx, cy);
    edgesRef.current = edges;
  }, [readings, edges, canvasEl]);

  // ---------- Canvas sizing ----------
  const updateCanvasSize = useCallback(() => {
    if (!containerEl || !canvasEl) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = containerEl.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    canvasEl.width = w * dpr;
    canvasEl.height = h * dpr;
    canvasEl.style.width = w + 'px';
    canvasEl.style.height = h + 'px';
  }, [containerEl, canvasEl]);

  useEffect(() => {
    if (!containerEl) return undefined;

    updateCanvasSize();
    const observer = new ResizeObserver(() => updateCanvasSize());
    observer.observe(containerEl);
    return () => observer.disconnect();
  }, [containerEl, updateCanvasSize]);

  // ---------- Force simulation + render loop ----------
  useEffect(() => {
    if (!canvasEl) return undefined;
    const canvas = canvasEl;

    let running = true;

    // The body of one frame, minus the re-schedule. Split out from `simulate`
    // so the re-schedule below can live in a `finally` and therefore cannot be
    // skipped by ANY path through this code — including a throw.
    function step(timestamp) {
      // Throttle to ~30fps
      if (timestamp - lastFrameRef.current < FRAME_INTERVAL) return;
      lastFrameRef.current = timestamp;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;

      if (w === 0 || h === 0) return;

      const nodes = nodesRef.current;
      const edgeList = edgesRef.current;
      const centerX = w / 2;
      const centerY = h / 2;
      const now = Date.now();

      // --- Force simulation step ---
      if (nodes.length > 0) {
        // Repulsion (all pairs)
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            let dx = nodes[j].x - nodes[i].x;
            let dy = nodes[j].y - nodes[i].y;
            let dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 1) dist = 1;
            const force = REPULSION_STRENGTH / (dist * dist);
            const fx = (force * dx) / dist;
            const fy = (force * dy) / dist;
            nodes[i].vx -= fx;
            nodes[i].vy -= fy;
            nodes[j].vx += fx;
            nodes[j].vy += fy;
          }
        }

        // Attraction along edges. Same transient-skip guard, and the same
        // reasoning, as drawEdges: see the comment there.
        edgeList.forEach((edge) => {
          const ni = nodes[edge.i];
          const nj = nodes[edge.j];
          if (!ni || !nj) return;
          let dx = nj.x - ni.x;
          let dy = nj.y - ni.y;
          let dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 1) dist = 1;
          const force = (dist - IDEAL_EDGE_LENGTH) * SPRING_STRENGTH;
          const fx = (force * dx) / dist;
          const fy = (force * dy) / dist;
          ni.vx += fx;
          ni.vy += fy;
          nj.vx -= fx;
          nj.vy -= fy;
        });

        // Center gravity (proportional to concentration)
        nodes.forEach((node) => {
          const gravity =
            CENTER_GRAVITY * (node.reading.ice_concentration / 10.0);
          node.vx += (centerX - node.x) * gravity;
          node.vy += (centerY - node.y) * gravity;
        });

        // Apply velocities with damping
        nodes.forEach((node) => {
          node.vx *= DAMPING;
          node.vy *= DAMPING;
          node.x += node.vx;
          node.y += node.vy;
        });
      }

      // --- Render ---
      const { offsetX, offsetY, scale } = viewRef.current;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      // Background
      drawBackground(ctx, w, h);

      // Central glow
      drawCentralGlow(ctx, nodes, offsetX, offsetY, scale);

      // Edges
      drawEdges(ctx, nodes, edgeList, now, offsetX, offsetY, scale, selectedRef.current);

      // Nodes
      drawNodes(ctx, nodes, now, offsetX, offsetY, scale, hoveredRef.current, selectedRef.current);
    }

    // MAKING A FAULT NON-FATAL AND LOUD, rather than making it impossible.
    // The cause is removed above (both refs are now written together, nodes
    // first) — this is the second layer, and it is here because the FAILURE MODE
    // is disproportionate: a single uncaught throw used to skip the trailing
    // requestAnimationFrame, and nothing in this component could restart it, so
    // one transient TypeError froze the operator's picture for the rest of the
    // session with no recovery short of a remount. `finally` means no path
    // through this function can drop the re-schedule.
    function simulate(timestamp) {
      if (!running) return;
      try {
        step(timestamp);
      } catch (err) {
        if (!loopErrorLoggedRef.current) {
          loopErrorLoggedRef.current = true;
          // eslint-disable-next-line no-console
          console.error('ResourceGraph render loop threw; recovering', err);
        }
      } finally {
        if (running) {
          animFrameRef.current = requestAnimationFrame(simulate);
        }
      }
    }

    // Reset the frame clock on every (re)start. Without this a restart on a new
    // canvas is throttled against a timestamp left over from the previous
    // element's last frame, so the first real frame can be skipped.
    lastFrameRef.current = 0;
    animFrameRef.current = requestAnimationFrame(simulate);

    return () => {
      running = false;
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [canvasEl]);

  // ---------- Hit testing ----------
  const hitTest = useCallback((sx, sy) => {
    const nodes = nodesRef.current;
    const { offsetX, offsetY, scale } = viewRef.current;
    let closest = null;
    let closestDist = Infinity;

    nodes.forEach((node, idx) => {
      const nx = (node.x + offsetX) * scale;
      const ny = (node.y + offsetY) * scale;
      const r = nodeRadius(node.reading.ice_concentration) * scale;
      const dx = sx - nx;
      const dy = sy - ny;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < r + 6 && dist < closestDist) {
        closest = idx;
        closestDist = dist;
      }
    });

    return closest;
  }, []);

  // Resolve a hit-test index to the stable identity of the reading it landed on.
  // Returns null when the index is null OR when the node has no clientSeq, which
  // is the honest answer for a reading the reducer did not mint (there is no
  // such reading today; the branch exists so a future producer cannot silently
  // make every unkeyed node select as one).
  const seqAt = useCallback((idx) => {
    if (idx === null) return null;
    const node = nodesRef.current[idx];
    const key = node && node.reading ? node.reading.clientSeq : undefined;
    return typeof key === 'number' ? key : null;
  }, []);

  // ---------- Mouse interactions ----------
  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return;
    if (!canvasEl) return;
    const rect = canvasEl.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    dragRef.current = {
      dragging: true,
      lastX: sx,
      lastY: sy,
      distance: 0,
    };
    setIsDragging(true);
  }, [canvasEl]);

  const handleMouseMove = useCallback(
    (e) => {
      if (!canvasEl) return;
      const rect = canvasEl.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;

      // Pan
      if (dragRef.current.dragging) {
        const dx = sx - dragRef.current.lastX;
        const dy = sy - dragRef.current.lastY;
        const { scale } = viewRef.current;
        viewRef.current.offsetX += dx / scale;
        viewRef.current.offsetY += dy / scale;
        dragRef.current.lastX = sx;
        dragRef.current.lastY = sy;
        dragRef.current.distance += Math.abs(dx) + Math.abs(dy);
        // Hide tooltip while dragging
        setTooltip(null);
        setHoveredSeq(null);
        return;
      }

      // Hover hit test
      const idx = hitTest(sx, sy);
      setHoveredSeq(seqAt(idx));

      if (idx !== null) {
        const node = nodesRef.current[idx];
        const r = node.reading;
        setTooltip({
          x: sx + 16,
          y: sy - 10,
          concentration: r.ice_concentration,
          uncertainty: r.sensor_uncertainty,
          location: r.location,
          scoutId: r.scout_id,
        });
      } else {
        setTooltip(null);
      }
    },
    [canvasEl, hitTest, seqAt]
  );

  const handleMouseUp = useCallback(() => {
    dragRef.current.dragging = false;
    setIsDragging(false);
  }, []);

  const handleMouseLeave = useCallback(() => {
    dragRef.current.dragging = false;
    setIsDragging(false);
    setHoveredSeq(null);
    setTooltip(null);
  }, []);

  const handleClick = useCallback(
    (e) => {
      // Ignore if we panned
      if (dragRef.current.distance > 5) return;
      if (!canvasEl) return;

      const rect = canvasEl.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const seq = seqAt(hitTest(sx, sy));
      setSelectedSeq((prev) => (prev === seq ? null : seq));
    },
    [canvasEl, hitTest, seqAt]
  );

  // ---------- Zoom ----------
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const canvas = canvasEl;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    const oldScale = viewRef.current.scale;
    const factor = e.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
    const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, oldScale * factor));

    // Adjust offset so zoom centers on cursor
    viewRef.current.offsetX = sx / newScale - (sx / oldScale - viewRef.current.offsetX);
    viewRef.current.offsetY = sy / newScale - (sy / oldScale - viewRef.current.offsetY);
    viewRef.current.scale = newScale;
  }, [canvasEl]);

  useEffect(() => {
    if (!canvasEl) return undefined;
    canvasEl.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvasEl.removeEventListener('wheel', handleWheel);
  }, [canvasEl, handleWheel]);

  // ---------- Stats ----------
  const stats = readings && readings.length > 0
    ? {
        count: readings.length,
        avgConcentration: (
          readings.reduce((s, r) => s + r.ice_concentration, 0) / readings.length
        ).toFixed(2),
        peakConcentration: Math.max(...readings.map((r) => r.ice_concentration)).toFixed(2),
        edgeCount: edges.length,
        // A-polish: report the honest total alongside what is actually drawn.
        totalEdgeCount: totalCandidates,
        edgesCapped: totalCandidates > edges.length,
      }
    : null;

  // ---------- Empty state ----------
  //
  // THIS EARLY RETURN IS THE ONE THAT USED TO KILL THE VIEW, and it is kept
  // deliberately. It is not the defect — the defect was that the effects below
  // it could not observe the canvas appearing and disappearing. Now they key on
  // element identity, so unmounting the canvas here tears the loop down cleanly
  // and remounting it starts a new one attached to the new element. Read the
  // long note at the top of this component before changing this back.
  if (!readings || readings.length === 0) {
    return (
      <div className="resource-graph">
        <div className="resource-graph__empty">
          <div className="resource-graph__empty-text">
            No resource data yet
          </div>
          <div className="resource-graph__empty-sub">
            Scouts will populate this as they prospect
          </div>
          {/* "Nothing published yet" and "everything published is being
              rejected" look identical without this, and the second one is a
              defect somewhere upstream that the operator would otherwise wait
              out forever. */}
          {droppedReadings > 0 && (
            <div className="resource-graph__empty-sub">
              {droppedReadings} malformed reading{droppedReadings === 1 ? '' : 's'} rejected
            </div>
          )}
          <button className="resource-graph__empty-close" onClick={onClose}>
            Back to Fleet Map
          </button>
        </div>
      </div>
    );
  }

  // ---------- Render ----------
  return (
    <div ref={setContainerEl} className="resource-graph">
      <canvas
        ref={setCanvasEl}
        className={
          'resource-graph__canvas' +
          (isDragging ? ' resource-graph__canvas--dragging' : '')
        }
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
      />

      {/* Header */}
      <div className="resource-graph__header">
        <span className="resource-graph__title">Resource Knowledge Map</span>
        <button className="resource-graph__close" onClick={onClose}>
          Back to Fleet Map
        </button>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="resource-graph__tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="resource-graph__tooltip-row">
            <span className="resource-graph__tooltip-label">Concentration</span>
            <span className="resource-graph__tooltip-value resource-graph__tooltip-value--highlight">
              {tooltip.concentration.toFixed(2)} wt%
            </span>
          </div>
          <div className="resource-graph__tooltip-row">
            {/* A sigma in wt%, not a percentage. This read
                `(uncertainty * 100).toFixed(0)}%` and showed the shipped
                scout's 0.5 wt% noise floor as "50%", which an operator would
                read as a half-scale error bar on a 0-10 wt% quantity rather
                than the +/-0.5 wt% it is. Same unit confusion as the alpha
                axis this file used to drive off the same field. */}
            <span className="resource-graph__tooltip-label">Sensor sigma</span>
            <span className="resource-graph__tooltip-value">
              &plusmn;{tooltip.uncertainty.toFixed(2)} wt%
            </span>
          </div>
          <div className="resource-graph__tooltip-row">
            <span className="resource-graph__tooltip-label">Position</span>
            <span className="resource-graph__tooltip-value">
              ({tooltip.location.x.toFixed(1)}, {tooltip.location.y.toFixed(1)})
            </span>
          </div>
          <div className="resource-graph__tooltip-row">
            <span className="resource-graph__tooltip-label">Scout</span>
            <span className="resource-graph__tooltip-value">
              {tooltip.scoutId}
            </span>
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="resource-graph__legend">
        <div className="resource-graph__legend-title">Node Size Scale</div>
        <div className="resource-graph__legend-items">
          {[1, 3, 5, 8, 10].map((val) => {
            const r = nodeRadius(val);
            return (
              <div
                key={val}
                className="resource-graph__legend-node"
                style={{
                  width: r * 2,
                  height: r * 2,
                  background: iceConcentrationColor(val, 0.8),
                  boxShadow: val > 5
                    ? `0 0 ${val}px ${iceConcentrationColor(val, 0.4)}`
                    : 'none',
                }}
                title={`${val} wt%`}
              />
            );
          })}
        </div>
        <div className="resource-graph__legend-labels">
          <span>1 wt%</span>
          <span>10 wt%</span>
        </div>
      </div>

      {/* Stats — A-polish: opaque panel + larger type so it stays readable
          over the node field on a projector. */}
      {stats && (
        <div className="resource-graph__stats">
          <div className="resource-graph__stats-row">
            <span className="resource-graph__stats-label">Readings</span>
            <span className="resource-graph__stats-value">{stats.count}</span>
          </div>
          <div className="resource-graph__stats-row">
            <span className="resource-graph__stats-label">Connections</span>
            <span className="resource-graph__stats-value">
              {stats.edgesCapped
                ? `${stats.edgeCount} of ${stats.totalEdgeCount}`
                : stats.edgeCount}
            </span>
          </div>
          <div className="resource-graph__stats-row">
            <span className="resource-graph__stats-label">Peak</span>
            <span className="resource-graph__stats-value">
              {stats.peakConcentration} wt%
            </span>
          </div>
          <div className="resource-graph__stats-row">
            <span className="resource-graph__stats-label">Avg</span>
            <span className="resource-graph__stats-value">
              {stats.avgConcentration} wt%
            </span>
          </div>
          {droppedReadings > 0 && (
            <div className="resource-graph__stats-row">
              <span className="resource-graph__stats-label">Rejected</span>
              <span className="resource-graph__stats-value">{droppedReadings}</span>
            </div>
          )}
          {stats.edgesCapped && (
            <div className="resource-graph__stats-note">
              Showing the {stats.edgeCount} strongest-similarity links only
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ResourceGraph;
