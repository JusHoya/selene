// FSM state -> color
export const STATE_COLORS = {
  IDLE: '#556080',
  BIDDING: '#a855f7',
  ASSIGNED: '#a855f7',
  NAVIGATING: '#00d4ff',
  WORKING: '#00b894',
  RETURNING: '#ffc107',
  RECHARGING: '#00e676',
  ERROR: '#ff4757',
  OFFLINE: '#2a3050',
};

// FSM state -> human label
export const STATE_LABELS = {
  IDLE: 'Idle',
  BIDDING: 'Bidding',
  ASSIGNED: 'Assigned',
  NAVIGATING: 'Navigating',
  WORKING: 'Working',
  RETURNING: 'Returning',
  RECHARGING: 'Recharging',
  ERROR: 'Error',
  OFFLINE: 'Offline',
};

// Robot type -> accent color
export const TYPE_COLORS = {
  scout: '#00d4ff',
  excavator: '#ffc107',
  hauler: '#00e676',
};

// Robot type -> icon label
export const TYPE_LABELS = {
  scout: 'Scout',
  excavator: 'Excavator',
  hauler: 'Hauler',
};

// A10: Visible floor for zero-ice readings.
//
// The old ramp started at rgb(0,0,0), so a genuine 0 wt% reading rendered as
// black. The heatmap composites with 'screen', where black is a no-op, making
// a real "we sampled here and found nothing" reading indistinguishable from
// terrain that was never sampled. Starting the ramp at a dark-but-visible blue
// keeps zero readings on screen.
//
// Value chosen empirically against the running dashboard: a single 0 wt%
// reading at rgb(10,30,90) was still only a faint smudge once 'screen'
// compositing and the sensor-uncertainty alpha were applied.
const ICE_FLOOR_RGB = [20, 55, 150];

// Ice concentration -> color (0-10 wt%)
export function iceConcentrationColor(value, alpha = 0.7) {
  const t = Math.min(Math.max(value || 0, 0) / 10, 1);
  // Dark blue floor -> Blue -> Cyan -> Yellow -> Red
  let r, g, b;
  if (t < 0.25) {
    const s = t / 0.25;
    // Ramp from the visible floor up to pure blue, so the segment boundary at
    // t=0.25 still lands exactly on rgb(0,0,255).
    r = Math.round(ICE_FLOOR_RGB[0] * (1 - s));
    g = Math.round(ICE_FLOOR_RGB[1] * (1 - s));
    b = Math.round(ICE_FLOOR_RGB[2] + (255 - ICE_FLOOR_RGB[2]) * s);
  } else if (t < 0.5) {
    const s = (t - 0.25) / 0.25;
    r = 0; g = Math.round(255 * s); b = 255;
  } else if (t < 0.75) {
    const s = (t - 0.5) / 0.25;
    r = Math.round(255 * s); g = 255; b = Math.round(255 * (1 - s));
  } else {
    const s = (t - 0.75) / 0.25;
    r = 255; g = Math.round(255 * (1 - s)); b = 0;
  }
  return `rgba(${r},${g},${b},${alpha})`;
}

// Battery level -> color
export function batteryColor(level) {
  if (level > 0.5) return '#00e676';
  if (level > 0.2) return '#ffc107';
  return '#ff4757';
}
