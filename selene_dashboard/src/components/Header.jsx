import React from 'react';
import './Header.css';

export default function Header({ connected, error, simTime }) {
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
      </div>

      <div className="header__right">
        <div className="header__time">
          <span className="header__time-label">SIM TIME</span>
          <span className="header__time-value mono">{formatTime(simTime)}</span>
        </div>
      </div>
    </header>
  );
}
