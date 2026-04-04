import React from 'react';
import './MissionProgress.css';

const TOTAL_WAYPOINTS = 5;

function formatSimTime(seconds) {
  if (!seconds && seconds !== 0) return '--';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${String(s).padStart(2, '0')}s`;
}

export default function MissionProgress({ progress, robots, readings }) {
  const robotMap = robots || {};
  const readingsList = readings || [];
  const robotEntries = Object.values(robotMap);

  // Waypoints: unique reading locations count, capped at total
  const waypointsCompleted = Math.min(readingsList.length, TOTAL_WAYPOINTS);
  const waypointsPct = (waypointsCompleted / TOTAL_WAYPOINTS) * 100;

  // Ice readings count
  const iceReadings = readingsList.length;

  // Active robots: not IDLE and not OFFLINE
  const activeRobots = robotEntries.filter(
    (r) => r.fsm_state !== 'IDLE' && r.fsm_state !== 'OFFLINE'
  ).length;
  const totalRobots = robotEntries.length;

  // Energy used: estimate from battery data
  const energyUsed = robotEntries.length > 0
    ? robotEntries.reduce((sum, r) => sum + (1 - (r.battery_level || 0)), 0)
    : null;
  const energyDisplay = energyUsed !== null
    ? `${(energyUsed * 100).toFixed(0)}%`
    : '--';

  // Fleet distance: not directly available
  const fleetDistance = '--';

  // Sim time
  const simTime = progress?.elapsed_sim_time;

  return (
    <div className="mission-progress">
      <div className="mission-progress__header">Mission Status</div>
      <div className="mission-progress__grid">
        {/* Waypoints */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Waypoints</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--cyan">
            {waypointsCompleted} / {TOTAL_WAYPOINTS}
          </span>
          <div className="mission-progress__mini-bar">
            <div
              className="mission-progress__mini-fill"
              style={{ width: `${waypointsPct}%` }}
            />
          </div>
        </div>

        {/* Ice Readings */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Ice Readings</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--teal">
            {iceReadings}
          </span>
        </div>

        {/* Fleet Distance */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Fleet Distance</span>
          <span className="mission-progress__stat-value">
            {fleetDistance}
          </span>
        </div>

        {/* Energy Used */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Energy Used</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--amber">
            {energyDisplay}
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
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Active Robots</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--green">
            {activeRobots}{totalRobots > 0 ? ` / ${totalRobots}` : ''}
          </span>
        </div>
      </div>
    </div>
  );
}
