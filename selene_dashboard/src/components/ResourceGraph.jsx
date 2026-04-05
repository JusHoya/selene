import React, { useRef, useState, useEffect, useCallback } from 'react';
import { iceConcentrationColor } from '../utils/colors';
import './ResourceGraph.css';

// ---------- Constants ----------
const FRAME_INTERVAL = 1000 / 30; // 30 fps
const MIN_NODE_RADIUS = 4;
const MAX_NODE_RADIUS = 30;
const PROXIMITY_THRESHOLD = 30; // meters — readings within this distance get an edge
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

/** Map sensor_uncertainty (0–1) to alpha (inverted: low uncertainty = high alpha) */
function uncertaintyAlpha(uncertainty) {
  return Math.max(0.15, Math.min(1.0, 1.0 - uncertainty * 0.8));
}

/** Euclidean distance between two world-space points */
function worldDist(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/** Build edge list from readings based on spatial proximity */
function computeEdges(readings) {
  const edges = [];
  for (let i = 0; i < readings.length; i++) {
    for (let j = i + 1; j < readings.length; j++) {
      const dist = worldDist(readings[i].location, readings[j].location);
      if (dist <= PROXIMITY_THRESHOLD) {
        // Similarity: 1.0 when concentrations are identical, 0.0 when 10 apart
        const concDiff = Math.abs(
          readings[i].ice_concentration - readings[j].ice_concentration
        );
        const similarity = Math.max(0, 1 - concDiff / 10);
        edges.push({ i, j, similarity, worldDist: dist });
      }
    }
  }
  return edges;
}

/** Initialize simulation nodes from readings, scattered around canvas center */
function initNodes(readings, centerX, centerY) {
  return readings.map((r, idx) => {
    // Scatter around center based on original world position, normalized
    const angle = (idx / Math.max(readings.length, 1)) * Math.PI * 2;
    const spread = 120 + Math.random() * 80;
    return {
      x: centerX + Math.cos(angle) * spread + (Math.random() - 0.5) * 40,
      y: centerY + Math.sin(angle) * spread + (Math.random() - 0.5) * 40,
      vx: 0,
      vy: 0,
      reading: r,
    };
  });
}

// ---------- Canvas Drawing ----------

function drawBackground(ctx, w, h, time) {
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

function drawEdges(ctx, nodes, edges, time, offsetX, offsetY, scale, selectedIdx) {
  ctx.save();
  edges.forEach((edge) => {
    const a = nodes[edge.i];
    const b = nodes[edge.j];
    const ax = (a.x + offsetX) * scale;
    const ay = (a.y + offsetY) * scale;
    const bx = (b.x + offsetX) * scale;
    const by = (b.y + offsetY) * scale;

    const isConnectedToSelected =
      selectedIdx !== null && (edge.i === selectedIdx || edge.j === selectedIdx);

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

function drawCentralGlow(ctx, nodes, w, h, offsetX, offsetY, scale) {
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

function drawNodes(ctx, nodes, time, offsetX, offsetY, scale, hoveredIdx, selectedIdx) {
  ctx.save();
  nodes.forEach((node, idx) => {
    const { reading } = node;
    const x = (node.x + offsetX) * scale;
    const y = (node.y + offsetY) * scale;
    const r = nodeRadius(reading.ice_concentration) * scale;
    const alpha = uncertaintyAlpha(reading.sensor_uncertainty);
    const isHovered = idx === hoveredIdx;
    const isSelected = idx === selectedIdx;
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

function drawLegendOnCanvas(ctx, w, h) {
  // Draw a small node-size reference in bottom-right
  // (The HTML legend overlays this area, so this is a fallback)
  // Intentionally minimal — legend is handled in CSS overlay
}

// ---------- Component ----------

function ResourceGraph({ readings, onClose }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const lastFrameRef = useRef(0);

  // Simulation state held in refs for the animation loop
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);
  const readingsCountRef = useRef(0);

  // View transform
  const viewRef = useRef({ offsetX: 0, offsetY: 0, scale: 1 });
  const dragRef = useRef({ dragging: false, lastX: 0, lastY: 0, startX: 0, startY: 0, distance: 0 });

  // Interactive state
  const [hoveredIdx, setHoveredIdx] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [tooltip, setTooltip] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  const hoveredRef = useRef(null);
  const selectedRef = useRef(null);
  hoveredRef.current = hoveredIdx;
  selectedRef.current = selectedIdx;

  // ---------- Initialize / update simulation when readings change ----------
  useEffect(() => {
    if (!readings || readings.length === 0) {
      nodesRef.current = [];
      edgesRef.current = [];
      readingsCountRef.current = 0;
      return;
    }

    // Only re-initialize when readings count changes
    if (readings.length !== readingsCountRef.current) {
      const canvas = canvasRef.current;
      const w = canvas ? canvas.clientWidth : 800;
      const h = canvas ? canvas.clientHeight : 600;
      nodesRef.current = initNodes(readings, w / 2, h / 2);
      edgesRef.current = computeEdges(readings);
      readingsCountRef.current = readings.length;
    } else {
      // Update reading data in existing nodes (concentration/uncertainty may change)
      readings.forEach((r, i) => {
        if (nodesRef.current[i]) {
          nodesRef.current[i].reading = r;
        }
      });
      edgesRef.current = computeEdges(readings);
    }
  }, [readings]);

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
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    updateCanvasSize();
    const observer = new ResizeObserver(() => updateCanvasSize());
    observer.observe(container);
    return () => observer.disconnect();
  }, [updateCanvasSize]);

  // ---------- Force simulation + render loop ----------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let running = true;

    function simulate(timestamp) {
      if (!running) return;

      // Throttle to ~30fps
      if (timestamp - lastFrameRef.current < FRAME_INTERVAL) {
        animFrameRef.current = requestAnimationFrame(simulate);
        return;
      }
      lastFrameRef.current = timestamp;

      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;

      if (w === 0 || h === 0) {
        animFrameRef.current = requestAnimationFrame(simulate);
        return;
      }

      const nodes = nodesRef.current;
      const edges = edgesRef.current;
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

        // Attraction along edges
        edges.forEach((edge) => {
          const ni = nodes[edge.i];
          const nj = nodes[edge.j];
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
      drawBackground(ctx, w, h, now);

      // Central glow
      drawCentralGlow(ctx, nodes, w, h, offsetX, offsetY, scale);

      // Edges
      drawEdges(ctx, nodes, edges, now, offsetX, offsetY, scale, selectedRef.current);

      // Nodes
      drawNodes(ctx, nodes, now, offsetX, offsetY, scale, hoveredRef.current, selectedRef.current);

      animFrameRef.current = requestAnimationFrame(simulate);
    }

    animFrameRef.current = requestAnimationFrame(simulate);

    return () => {
      running = false;
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, []);

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

  // ---------- Mouse interactions ----------
  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    dragRef.current = {
      dragging: true,
      lastX: sx,
      lastY: sy,
      startX: sx,
      startY: sy,
      distance: 0,
    };
    setIsDragging(true);
  }, []);

  const handleMouseMove = useCallback(
    (e) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
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
        setHoveredIdx(null);
        return;
      }

      // Hover hit test
      const idx = hitTest(sx, sy);
      setHoveredIdx(idx);

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
    [hitTest]
  );

  const handleMouseUp = useCallback(() => {
    dragRef.current.dragging = false;
    setIsDragging(false);
  }, []);

  const handleMouseLeave = useCallback(() => {
    dragRef.current.dragging = false;
    setIsDragging(false);
    setHoveredIdx(null);
    setTooltip(null);
  }, []);

  const handleClick = useCallback(
    (e) => {
      // Ignore if we panned
      if (dragRef.current.distance > 5) return;

      const rect = canvasRef.current.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const idx = hitTest(sx, sy);
      setSelectedIdx((prev) => (prev === idx ? null : idx));
    },
    [hitTest]
  );

  // ---------- Zoom ----------
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const canvas = canvasRef.current;
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
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  // ---------- Stats ----------
  const stats = readings && readings.length > 0
    ? {
        count: readings.length,
        avgConcentration: (
          readings.reduce((s, r) => s + r.ice_concentration, 0) / readings.length
        ).toFixed(2),
        peakConcentration: Math.max(...readings.map((r) => r.ice_concentration)).toFixed(2),
        edgeCount: edgesRef.current.length,
      }
    : null;

  // ---------- Empty state ----------
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
          <button className="resource-graph__empty-close" onClick={onClose}>
            Back to Fleet Map
          </button>
        </div>
      </div>
    );
  }

  // ---------- Render ----------
  return (
    <div ref={containerRef} className="resource-graph">
      <canvas
        ref={canvasRef}
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
            <span className="resource-graph__tooltip-label">Uncertainty</span>
            <span className="resource-graph__tooltip-value">
              {(tooltip.uncertainty * 100).toFixed(0)}%
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

      {/* Stats */}
      {stats && (
        <div className="resource-graph__stats">
          <div className="resource-graph__stats-row">
            Readings:{' '}
            <span className="resource-graph__stats-value">{stats.count}</span>
          </div>
          <div className="resource-graph__stats-row">
            Connections:{' '}
            <span className="resource-graph__stats-value">{stats.edgeCount}</span>
          </div>
          <div className="resource-graph__stats-row">
            Peak:{' '}
            <span className="resource-graph__stats-value">
              {stats.peakConcentration} wt%
            </span>
          </div>
          <div className="resource-graph__stats-row">
            Avg:{' '}
            <span className="resource-graph__stats-value">
              {stats.avgConcentration} wt%
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default ResourceGraph;
