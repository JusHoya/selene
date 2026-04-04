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

// Ice concentration -> color (0-10 wt%)
export function iceConcentrationColor(value, alpha = 0.7) {
  const t = Math.min(value / 10, 1);
  // Transparent -> Blue -> Cyan -> Yellow -> Red
  let r, g, b;
  if (t < 0.25) {
    r = 0; g = 0; b = Math.round(255 * (t / 0.25));
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
