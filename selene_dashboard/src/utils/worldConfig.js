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

// Depot and recharge station.
//
// THE DEPOT MOVED ON 2026-07-31, and this copy has to move with it. It is a
// COPY: the authority is depot_x / depot_y in
// selene_orchestrator/config/orchestrator_params.yaml, which is what a hauler
// actually receives on TaskAssignment.depot_location, and the `depot` marker in
// selene_sim/worlds/lunar_psr.sdf, which is what physically exists there.
// selene_sim/test/test_mission_traversability.py asserts those two agree; this
// file is a third place and nothing machine-checks it, so it is the one that
// goes stale. If a delivery ever renders somewhere other than the diamond,
// suspect this line first.
//
// WHY IT MOVED: every ice deposit is inside the PSR crater and the crater rim
// is 34-39 degrees of uphill on all 24 azimuths sampled at 15 deg spacing, so
// nothing that drives down to the ice can climb back out. A depot outside the
// crater made every haul impossible; one on the crater floor makes the ISRU
// cycle physically completable. The RECHARGE STATION is deliberately still
// outside, because solar recharge needs sunlight and a permanently shadowed
// region has none — which means it is behind that same wall. That is an open
// problem, recorded in docs/phase5_deviation_register.md, not a solved one.
export const DEPOT = { x: -100, y: -150, radius: 10 };
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

// A-polish: Default map framing.
//
// The world is 500x500 m but all activity happens in the PSR + depot corner, so
// framing the whole world leaves the fleet as a tiny cluster. This is a VIEW
// hint only — it is derived from the coordinates above and does not change any
// of them (they must keep matching selene_sim/config/world_params.yaml).
export const DEFAULT_VIEW = (() => {
  const margin = 25; // meters of breathing room around the working area
  const xs = [];
  const ys = [];
  PSR_ZONES.forEach((z) => {
    xs.push(z.center[0] - z.radius, z.center[0] + z.radius);
    ys.push(z.center[1] - z.radius, z.center[1] + z.radius);
  });
  [DEPOT, RECHARGE_STATION].forEach((p) => {
    xs.push(p.x - p.radius, p.x + p.radius);
    ys.push(p.y - p.radius, p.y + p.radius);
  });
  PROSPECT_WAYPOINTS.forEach(([x, y]) => {
    xs.push(x);
    ys.push(y);
  });
  const xMin = Math.max(WORLD.X_MIN, Math.min(...xs) - margin);
  const xMax = Math.min(WORLD.X_MAX, Math.max(...xs) + margin);
  const yMin = Math.max(WORLD.Y_MIN, Math.min(...ys) - margin);
  const yMax = Math.min(WORLD.Y_MAX, Math.max(...ys) + margin);
  return {
    X_MIN: xMin,
    X_MAX: xMax,
    Y_MIN: yMin,
    Y_MAX: yMax,
    WIDTH: xMax - xMin,
    HEIGHT: yMax - yMin,
    CENTER_X: (xMin + xMax) / 2,
    CENTER_Y: (yMin + yMax) / 2,
  };
})();
