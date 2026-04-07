/**
 * Procedural lunar terrain generator for the FleetMap canvas.
 *
 * Produces an offscreen canvas with a top-down lunar surface texture:
 *   - Multi-octave value noise for regolith roughness
 *   - Procedural craters with sunlit rims and shadowed interiors
 *   - Highland / mare brightness variation
 *   - Fine grain texture for realism
 *
 * The image is generated once and cached; the render loop draws it
 * as the background layer every frame.
 */

import { WORLD, ROCKS } from './worldConfig';

// ---------------------------------------------------------------------------
// Hash-based value noise (no dependencies)
// ---------------------------------------------------------------------------

function hash(x, y) {
  let n = (x | 0) * 374761393 + (y | 0) * 668265263;
  n = ((n ^ (n >>> 13)) * 1274126177) >>> 0;
  return n / 4294967296;
}

function smoothNoise(x, y) {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  // Hermite smoothstep
  const sx = fx * fx * (3 - 2 * fx);
  const sy = fy * fy * (3 - 2 * fy);

  const n00 = hash(ix, iy);
  const n10 = hash(ix + 1, iy);
  const n01 = hash(ix, iy + 1);
  const n11 = hash(ix + 1, iy + 1);

  return (
    n00 * (1 - sx) * (1 - sy) +
    n10 * sx * (1 - sy) +
    n01 * (1 - sx) * sy +
    n11 * sx * sy
  );
}

function fbm(x, y, octaves) {
  let value = 0;
  let amplitude = 0.5;
  let frequency = 1;
  for (let i = 0; i < octaves; i++) {
    value += amplitude * smoothNoise(x * frequency, y * frequency);
    amplitude *= 0.5;
    frequency *= 2;
  }
  return value;
}

// ---------------------------------------------------------------------------
// Seeded crater catalog — deterministic from hash so layout never shifts
// ---------------------------------------------------------------------------

function buildCraterCatalog() {
  const craters = [];

  // Use the worldConfig ROCKS as small crater locations
  ROCKS.forEach((rock) => {
    craters.push({ x: rock.x, y: rock.y, r: rock.r * 3 + 1 });
  });

  // Procedural medium/small craters scattered across the map
  const seed = 42;
  for (let i = 0; i < 180; i++) {
    const h1 = hash(i * 7 + seed, i * 13 + seed);
    const h2 = hash(i * 17 + seed, i * 3 + seed);
    const h3 = hash(i * 23 + seed, i * 29 + seed);

    const x = WORLD.X_MIN + h1 * WORLD.WIDTH;
    const y = WORLD.Y_MIN + h2 * WORLD.HEIGHT;
    const r = 1.5 + h3 * 8;

    craters.push({ x, y, r });
  }

  // PSR crater — large impact feature centered on the Permanently Shadowed Region
  // (matches world_params.yaml psr_alpha center [-100, -150], radius 60)
  craters.push({ x: -100, y: -150, r: 58 });

  // Secondary ejecta craters around the PSR rim
  craters.push({ x: -65, y: -125, r: 8 });
  craters.push({ x: -135, y: -140, r: 7 });
  craters.push({ x: -110, y: -195, r: 9 });
  craters.push({ x: -150, y: -170, r: 6 });
  craters.push({ x: -75, y: -190, r: 5 });

  // Distant large craters for visual variety across the map
  craters.push({ x: 80, y: -70, r: 22 });
  craters.push({ x: -180, y: 100, r: 18 });
  craters.push({ x: 160, y: 170, r: 15 });
  craters.push({ x: -30, y: 200, r: 12 });
  craters.push({ x: 200, y: -180, r: 20 });

  return craters;
}

const CRATER_CATALOG = buildCraterCatalog();

// Sun direction (unit vector — light from upper-right)
const SUN_DX = 0.7071;
const SUN_DY = 0.7071;

// ---------------------------------------------------------------------------
// Terrain image generation
// ---------------------------------------------------------------------------

/**
 * Generate a lunar terrain image as an offscreen canvas.
 *
 * @param {number} texW  - pixel width of the output texture
 * @param {number} texH  - pixel height of the output texture
 * @returns {HTMLCanvasElement}  offscreen canvas with the terrain
 */
export function generateLunarTerrain(texW = 2048, texH = 2048) {
  const canvas = document.createElement('canvas');
  canvas.width = texW;
  canvas.height = texH;
  const ctx = canvas.getContext('2d');
  const imageData = ctx.createImageData(texW, texH);
  const data = imageData.data;

  const xRange = WORLD.X_MAX - WORLD.X_MIN;
  const yRange = WORLD.Y_MAX - WORLD.Y_MIN;

  // Pre-compute a height field so we can derive slope-based shading
  const heightMap = new Float32Array(texW * texH);

  for (let py = 0; py < texH; py++) {
    for (let px = 0; px < texW; px++) {
      const wx = WORLD.X_MIN + (px / texW) * xRange;
      const wy = WORLD.Y_MIN + ((texH - 1 - py) / texH) * yRange;

      // Multi-scale height
      let h =
        0.5 +
        0.30 * fbm(wx * 0.008, wy * 0.008, 6) +
        0.15 * fbm(wx * 0.003 + 50, wy * 0.003 + 50, 3) +
        0.08 * (smoothNoise(wx * 0.05, wy * 0.05) - 0.5) +
        0.04 * (smoothNoise(wx * 0.15, wy * 0.15) - 0.5);

      // Crater depth/rim contribution
      for (let ci = 0; ci < CRATER_CATALOG.length; ci++) {
        const cr = CRATER_CATALOG[ci];
        const dx = wx - cr.x;
        const dy = wy - cr.y;
        const distSq = dx * dx + dy * dy;
        const R = cr.r;
        const rimSq = (R * 2.5) * (R * 2.5);
        if (distSq > rimSq) continue;

        const dist = Math.sqrt(distSq);
        const t = dist / R;

        if (t < 0.70) {
          // Flat floor with gentle bowl
          h -= 0.25 * (1 - (t / 0.70) * (t / 0.70)) * Math.min(R / 4, 1);
        } else if (t < 1.0) {
          // Inner wall — steep rise from floor to rim
          const wallT = (t - 0.70) / 0.30;
          const blend = wallT * wallT;
          h += (-0.25 * (1 - blend) + 0.20 * blend) * Math.min(R / 4, 1);
        } else if (t < 1.4) {
          // Rim crest and outer slope
          const outerT = (t - 1.0) / 0.4;
          h += 0.20 * (1 - outerT) * (1 - outerT) * Math.min(R / 4, 1);
        }
      }

      heightMap[py * texW + px] = h;
    }
  }

  // Shade from height map using slope in sun direction
  for (let py = 0; py < texH; py++) {
    for (let px = 0; px < texW; px++) {
      const idx4 = (py * texW + px) * 4;
      const h = heightMap[py * texW + px];

      // Compute slope (height gradient) in sun direction
      const hR = px < texW - 1 ? heightMap[py * texW + px + 1] : h;
      const hL = px > 0 ? heightMap[py * texW + px - 1] : h;
      const hU = py > 0 ? heightMap[(py - 1) * texW + px] : h;
      const hD = py < texH - 1 ? heightMap[(py + 1) * texW + px] : h;

      const dhdx = (hR - hL) * 0.5;
      const dhdy = (hD - hU) * 0.5; // screen-space Y is inverted

      // Slope in sun direction — positive = facing sun = bright
      const slope = dhdx * SUN_DX + dhdy * (-SUN_DY);

      // Base albedo from height (highlands slightly brighter)
      const albedo = 0.18 + 0.10 * h;

      // Lighting: ambient + strong diffuse from slope
      const ambient = 0.30;
      const diffuse = 0.70 * Math.max(0, 0.5 + slope * 35.0);
      let brightness = albedo * (ambient + diffuse);

      // Fine grain noise for texture (use world coords)
      const wx = WORLD.X_MIN + (px / texW) * xRange;
      const wy = WORLD.Y_MIN + ((texH - 1 - py) / texH) * yRange;
      brightness += 0.012 * (smoothNoise(wx * 0.3, wy * 0.3) - 0.5);
      brightness += 0.006 * (smoothNoise(wx * 0.8, wy * 0.8) - 0.5);

      brightness = Math.max(0.01, Math.min(0.50, brightness));

      // Blue-gray tint to match dashboard palette
      const r = Math.floor(brightness * 210);
      const g = Math.floor(brightness * 220);
      const b = Math.floor(brightness * 255);

      data[idx4] = r;
      data[idx4 + 1] = g;
      data[idx4 + 2] = b;
      data[idx4 + 3] = 255;
    }
  }

  ctx.putImageData(imageData, 0, 0);
  return canvas;
}

// ---------------------------------------------------------------------------
// Crater outlines overlay (drawn in world-space on the main canvas)
// ---------------------------------------------------------------------------

/**
 * Draw crater rim outlines on the main FleetMap canvas.
 * Renders after terrain, before robots / POI markers.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} scale  current viewport scale (px per meter)
 */
export function drawCraterOutlines(ctx, scale) {
  ctx.save();

  CRATER_CATALOG.forEach((cr) => {
    // Only draw outlines for craters large enough to see
    if (cr.r * scale < 1.5) return;

    ctx.beginPath();
    ctx.arc(cr.x, cr.y, cr.r, 0, Math.PI * 2);

    // Larger craters get brighter outlines
    const alpha = cr.r > 10 ? 0.12 : cr.r > 5 ? 0.08 : 0.05;
    ctx.strokeStyle = `rgba(160, 175, 200, ${alpha})`;
    ctx.lineWidth = Math.max(0.5 / scale, 0.3);
    ctx.stroke();
  });

  ctx.restore();
}
