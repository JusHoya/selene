import React from 'react';
import './Header.css';

// D-06: `elapsedSec` was `simTime`, and the label below said "SIM TIME".
// MissionProgress.elapsed_sim_time is the ORCHESTRATOR's wall clock since its
// node started — use_sim_time is unset repo-wide and /clock is not bridged, so
// no part of this system runs on simulation time. The wire field keeps its name
// (renaming a published field breaks PRD MSG-7); the two places the dashboard
// showed it to an operator no longer repeat the claim.
export default function Header({
  connected, error, elapsedSec, showResourceGraph, onToggleResourceGraph,
}) {
  const formatTime = (seconds) => {
    if (!seconds && seconds !== 0) return '--:--:--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  return (
    <header className="header" style={{ gridArea: 'header' }}>
      <div className="header__brand">
        <span className="header__logo">SELENE</span>
        <span className="header__subtitle">MISSION CONTROL</span>
      </div>

      <div className="header__center">
        <div className={`header__status ${connected ? 'header__status--connected' : 'header__status--disconnected'}`}>
          <span className="header__status-dot" />
          <span className="header__status-text">
            {connected ? 'CONNECTED' : error ? 'ERROR' : 'DISCONNECTED'}
          </span>
        </div>

        {onToggleResourceGraph && (
          <button
            className={
              'header__view-toggle' +
              (showResourceGraph ? ' header__view-toggle--active' : '')
            }
            onClick={onToggleResourceGraph}
          >
            <span className="header__view-toggle-dot" />
            {showResourceGraph ? 'KNOWLEDGE MAP' : 'FLEET MAP'}
          </button>
        )}
      </div>

      <div className="header__right">
        <div
          className="header__time"
          title={
            'Orchestrator wall clock since the node started. NOT Gazebo '
            + 'simulation time: use_sim_time is unset repo-wide and /clock is '
            + 'not bridged.'
          }
        >
          <span className="header__time-label">ELAPSED</span>
          <span className="header__time-value mono">{formatTime(elapsedSec)}</span>
        </div>
      </div>
    </header>
  );
}
