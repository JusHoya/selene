import React from 'react';
import './MissionProgress.css';

function formatSimTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '--';
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatKg(value) {
  if (value == null || Number.isNaN(value)) return '--';
  if (value >= 100) return `${value.toFixed(0)} kg`;
  if (value >= 10)  return `${value.toFixed(1)} kg`;
  return `${value.toFixed(2)} kg`;
}

function formatKm(meters) {
  if (meters == null || Number.isNaN(meters)) return '--';
  const km = meters / 1000;
  if (km >= 10) return `${km.toFixed(1)} km`;
  return `${km.toFixed(2)} km`;
}

function formatWh(value) {
  if (value == null || Number.isNaN(value)) return '--';
  if (value >= 1000) return `${(value / 1000).toFixed(1)} kWh`;
  return `${value.toFixed(1)} Wh`;
}

export default function MissionProgress({ progress, robots }) {
  const robotMap = robots || {};
  const robotEntries = Object.values(robotMap);

  // Active robots: not IDLE and not OFFLINE
  const activeRobots = robotEntries.filter(
    (r) => r.fsm_state !== 'IDLE' && r.fsm_state !== 'OFFLINE'
  ).length;
  const totalRobots = robotEntries.length;

  // Progress topic fields (graceful fallback if undefined)
  const p = progress || {};
  const objective = p.objective_description || 'Mission Status';
  const target = p.target_quantity || 0;
  const extracted = p.extracted_quantity;
  const inTransit = p.in_transit_quantity;
  const deposited = p.deposited_quantity;
  const distance = p.fleet_distance_total;
  const energy = p.fleet_energy_total;
  const simTime = p.elapsed_sim_time;

  // Primary progress bar = deposited / target
  let depositedPct = 0;
  if (target > 0 && deposited != null) {
    depositedPct = Math.min(100, Math.max(0, (deposited / target) * 100));
  }

  return (
    <div className="mission-progress">
      <div className="mission-progress__header" title={objective}>
        {objective}
      </div>

      {target > 0 && (
        <div className="mission-progress__objective">
          <div className="mission-progress__objective-bar">
            <div
              className="mission-progress__objective-fill"
              style={{ width: `${depositedPct}%` }}
            />
          </div>
          <div className="mission-progress__objective-label">
            {formatKg(deposited)} / {formatKg(target)}{' '}
            <span className="mission-progress__objective-pct">
              ({depositedPct.toFixed(0)}%)
            </span>
          </div>
        </div>
      )}

      <div className="mission-progress__grid">
        {/* Extracted */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Extracted</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--cyan">
            {formatKg(extracted)}
          </span>
        </div>

        {/* In Transit */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">In Transit</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--teal">
            {formatKg(inTransit)}
          </span>
        </div>

        {/* Deposited */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Deposited</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--green">
            {formatKg(deposited)}
          </span>
        </div>

        {/* Fleet Distance */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Fleet Distance</span>
          <span className="mission-progress__stat-value">
            {formatKm(distance)}
          </span>
        </div>

        {/* Energy Used */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Fleet Energy</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--amber">
            {formatWh(energy)}
          </span>
        </div>

        {/* Sim Time */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Sim Time</span>
          <span className="mission-progress__stat-value">
            {formatSimTime(simTime)}
          </span>
        </div>

        {/* Active Robots */}
        <div className="mission-progress__stat mission-progress__stat--wide">
          <span className="mission-progress__stat-label">Active Robots</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--green">
            {activeRobots}{totalRobots > 0 ? ` / ${totalRobots}` : ''}
          </span>
        </div>
      </div>
    </div>
  );
}
