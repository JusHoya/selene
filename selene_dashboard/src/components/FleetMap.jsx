import React, { useRef, useState, useEffect, useCallback } from 'react';
import {
  WORLD,
  PSR_ZONES,
  DEPOT,
  RECHARGE_STATION,
  ICE_DEPOSITS,
  ROCKS,
  PROSPECT_WAYPOINTS,
} from '../utils/worldConfig';
import { TYPE_COLORS, iceConcentrationColor } from '../utils/colors';
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
    // Filled semi-transparent area
    ctx.beginPath();
    ctx.arc(cx, cy, zone.radius, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(10, 15, 40, 0.5)';
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

function drawResourceHeatmap(ctx, readings, scale) {
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  readings.forEach((r) => {
    const { x, y } = r.location;
    const conc = r.ice_concentration;
    const unc = r.sensor_uncertainty || 0.5;
    const radiusMeters = 15;
    const alpha = Math.max(0.05, Math.min(0.7, 0.7 * (1 - unc)));

    const grad = ctx.createRadialGradient(x, y, 0, x, y, radiusMeters);
    grad.addColorStop(0, iceConcentrationColor(conc, alpha));
    grad.addColorStop(1, iceConcentrationColor(conc, 0));

    ctx.beginPath();
    ctx.arc(x, y, radiusMeters, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();
  });
  ctx.globalCompositeOperation = 'source-over';
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

  // Label — placed above the depot visually
  ctx.save();
  ctx.translate(x, y + s + 4 / scale);
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

  // Label — placed above the station visually
  ctx.save();
  ctx.translate(x, y + radius + 4 / scale);
  ctx.scale(1, -1);
  ctx.font = `bold ${9 / scale}px JetBrains Mono, monospace`;
  ctx.fillStyle = '#00e676';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
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

function drawRobots(ctx, robots, selectedRobotId, scale, now) {
  ctx.save();
  const entries = Object.values(robots);

  entries.forEach((robot) => {
    const { robot_id, robot_type, fsm_state, pose } = robot;
    if (!pose) return;

    const { x, y, theta } = pose;
    const isSelected = robot_id === selectedRobotId;
    const color = TYPE_COLORS[robot_type] || '#e0e6f0';
    const baseSize = (isSelected ? 16 : 12) / scale;

    ctx.save();
    ctx.translate(x, y);

    // Selection ring
    if (isSelected) {
      ctx.beginPath();
      ctx.arc(0, 0, baseSize * 1.6, 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5 / scale;
      ctx.globalAlpha = 0.5 + 0.3 * Math.sin(now / 400);
      ctx.stroke();
      ctx.globalAlpha = 1;
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
      ctx.lineWidth = 2 / scale;
      ctx.stroke();
    }

    // Recharging: lower opacity
    if (fsm_state === 'RECHARGING') {
      ctx.globalAlpha = 0.5;
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
    ctx.lineWidth = 0.8 / scale;
    ctx.shadowBlur = 0;
    ctx.stroke();

    ctx.restore(); // undo translate + rotate

    // Label below robot — flip Y for text
    ctx.save();
    ctx.translate(x, y - baseSize - 3 / scale);
    ctx.scale(1, -1);
    ctx.font = `${9 / scale}px JetBrains Mono, monospace`;
    ctx.fillStyle = isSelected ? '#ffffff' : 'rgba(224,230,240,0.6)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(robot_id, 0, 0);
    ctx.restore();
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

// ---------- FleetMap Component ----------

function FleetMap({
  robots,
  resourceReadings,
  selectedRobotId,
  onSelectRobot,
  heatmapVisible,
  onToggleHeatmap,
}) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const lastFrameTimeRef = useRef(0);

  // Viewport state stored in refs for animation loop access (no re-render needed)
  const viewRef = useRef({ centerX: 0, centerY: 0, scale: 1 });

  // Drag state
  const dragRef = useRef({ dragging: false, lastX: 0, lastY: 0 });

  // Mouse world coords for display
  const [mouseCoords, setMouseCoords] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  // Store latest props in refs so animation loop sees them without re-creating
  const propsRef = useRef({ robots, resourceReadings, selectedRobotId, heatmapVisible });
  propsRef.current = { robots, resourceReadings, selectedRobotId, heatmapVisible };

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

    // Compute default scale to fit world with padding
    const pad = 1 + PADDING_RATIO * 2;
    const sx = w / (WORLD.WIDTH * pad);
    const sy = h / (WORLD.HEIGHT * pad);
    const fitScale = Math.min(sx, sy);

    // Only reset viewport if scale hasn't been set yet (initial load)
    if (viewRef.current.scale === 1 && viewRef.current.centerX === 0 && viewRef.current.centerY === 0) {
      viewRef.current = { centerX: 0, centerY: 0, scale: fitScale };
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
      const { robots: robs, resourceReadings: readings, selectedRobotId: selId, heatmapVisible: hmVis } = propsRef.current;
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

      // (d) Resource heatmap
      if (hmVis && readings && readings.length > 0) {
        drawResourceHeatmap(ctx, readings, scale);
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

      // (j) Robots
      if (robs) {
        drawRobots(ctx, robs, selId, scale, now);
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

  return (
    <div
      ref={containerRef}
      className={'fleet-map' + (isDragging ? ' fleet-map--dragging' : '')}
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

      <ResourceLegend
        heatmapVisible={heatmapVisible}
        onToggleHeatmap={onToggleHeatmap}
      />
    </div>
  );
}

export default FleetMap;
