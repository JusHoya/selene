// World bounds (meters)
export const WORLD = {
  X_MIN: -250,
  X_MAX: 250,
  Y_MIN: -250,
  Y_MAX: 250,
  WIDTH: 500,
  HEIGHT: 500,
};

// Permanently Shadowed Region
export const PSR_ZONES = [
  { name: 'psr_alpha', center: [-100, -150], radius: 60 },
];

// Depot and recharge station
export const DEPOT = { x: -30, y: -100, radius: 10 };
export const RECHARGE_STATION = { x: -30, y: -100, radius: 5 };

// Ice deposits (ground truth for reference overlay)
export const ICE_DEPOSITS = [
  { id: 'alpha', center: [-80, -140], radius: 25, peak: 8.0, sigma: 12 },
  { id: 'beta', center: [-110, -170], radius: 15, peak: 4.0, sigma: 8 },
  { id: 'gamma', center: [-90, -130], radius: 10, peak: 2.5, sigma: 5 },
  { id: 'delta', center: [-120, -155], radius: 20, peak: 6.0, sigma: 10 },
];

// Rock obstacles (from nav_params.yaml)
export const ROCKS = [
  { x: -55, y: -110, r: 1.0 }, { x: -72, y: -98, r: 1.0 },
  { x: -140, y: -120, r: 1.0 }, { x: -125, y: -195, r: 1.0 },
  { x: -60, y: -175, r: 1.0 }, { x: -88, y: -92, r: 1.0 },
  { x: -48, y: -145, r: 1.5 }, { x: -150, y: -155, r: 1.5 },
  { x: -105, y: -205, r: 1.5 }, { x: -95, y: -95, r: 1.5 },
  { x: -68, y: -190, r: 1.5 }, { x: 30, y: -20, r: 1.0 },
  { x: -180, y: 60, r: 1.0 }, { x: 120, y: -80, r: 1.0 },
  { x: -40, y: 100, r: 1.0 }, { x: 80, y: 130, r: 1.0 },
  { x: -150, y: -30, r: 1.5 }, { x: 160, y: 50, r: 1.5 },
  { x: -20, y: -200, r: 1.5 }, { x: 100, y: -150, r: 1.0 },
  { x: -90, y: 180, r: 1.5 }, { x: 200, y: -100, r: 1.0 },
  { x: -10, y: -40, r: 1.5 }, { x: -15, y: -45, r: 1.5 },
  { x: 180, y: -50, r: 1.5 }, { x: -50, y: 200, r: 1.5 },
];

// Prospect waypoints (matching agent_node config)
export const PROSPECT_WAYPOINTS = [
  [-60, -120], [-80, -140], [-100, -150], [-110, -170], [-90, -130],
];
