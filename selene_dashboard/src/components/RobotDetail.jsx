import React from 'react';
import { STATE_COLORS, STATE_LABELS, TYPE_COLORS, TYPE_LABELS, batteryColor } from '../utils/colors';
import BatteryGauge from './BatteryGauge';
import './RobotDetail.css';

function formatRelativeTime(timestamp) {
  const diff = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function radToDeg(rad) {
  return ((rad * 180) / Math.PI).toFixed(1);
}

export default function RobotDetail({ robot }) {
  if (!robot) {
    return (
      <div className="robot-detail">
        <div className="robot-detail__placeholder">
          Select a robot on the map or fleet cards below
        </div>
      </div>
    );
  }

  const {
    robot_id,
    robot_type,
    fsm_state,
    pose,
    velocity,
    battery_level,
    current_task_id,
    task_progress,
    capabilities,
    stateHistory,
  } = robot;

  const typeColor = TYPE_COLORS[robot_type] || '#556080';
  const typeLabel = TYPE_LABELS[robot_type] || robot_type;
  const stateColor = STATE_COLORS[fsm_state] || '#556080';
  const stateLabel = STATE_LABELS[fsm_state] || fsm_state;
  const isCharging = fsm_state === 'RECHARGING';
  const speed = Math.abs(velocity?.linear?.x || 0).toFixed(2);
  const heading = radToDeg(pose?.theta || 0);
  const progressPct = Math.round((task_progress || 0) * 100);
  const batteryPct = Math.round((battery_level || 0) * 100);
  const historySlice = (stateHistory || []).slice(0, 10);

  return (
    <div className="robot-detail animate-slide-in">
      {/* Section 1: Identity */}
      <div className="robot-detail__section">
        <div className="robot-detail__identity">
          <div className="robot-detail__id-group">
            <span className="robot-detail__id">{robot_id}</span>
            <span className="robot-detail__type">
              <span
                className="robot-detail__type-dot"
                style={{ background: typeColor }}
              />
              {typeLabel}
            </span>
          </div>
          <span
            className="robot-detail__state-badge"
            style={{ background: stateColor }}
          >
            {stateLabel}
          </span>
        </div>
      </div>

      {/* Section 2: Battery */}
      <div className="robot-detail__section">
        <div className="robot-detail__section-label">Battery</div>
        <div className="robot-detail__battery">
          <BatteryGauge level={battery_level} charging={isCharging} size={80} />
          <div className="robot-detail__battery-info">
            <span
              className="robot-detail__battery-percent"
              style={{ color: batteryColor(battery_level) }}
            >
              {batteryPct}%
            </span>
            {isCharging && (
              <span className="robot-detail__battery-charging">
                <span className="robot-detail__battery-charging-dot" />
                Charging
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Section 3: Position & Motion */}
      <div className="robot-detail__section">
        <div className="robot-detail__section-label">Position &amp; Motion</div>
        <div className="robot-detail__stats">
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">X</span>
            <span className="robot-detail__stat-value">
              {(pose?.x ?? 0).toFixed(1)} m
            </span>
          </div>
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">Y</span>
            <span className="robot-detail__stat-value">
              {(pose?.y ?? 0).toFixed(1)} m
            </span>
          </div>
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">Heading</span>
            <span className="robot-detail__stat-value">{heading}&deg;</span>
          </div>
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">Speed</span>
            <span className="robot-detail__stat-value">{speed} m/s</span>
          </div>
        </div>
      </div>

      {/* Section 4: Current Task */}
      <div className="robot-detail__section">
        <div className="robot-detail__section-label">Current Task</div>
        <div className="robot-detail__task-id">
          Task: <span>{current_task_id || '--'}</span>
        </div>
        <div className="robot-detail__progress-bar">
          <div
            className="robot-detail__progress-fill"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <div className="robot-detail__progress-label">{progressPct}%</div>
      </div>

      {/* Section 5: Capabilities */}
      {capabilities && capabilities.length > 0 && (
        <div className="robot-detail__section">
          <div className="robot-detail__section-label">Capabilities</div>
          <div className="robot-detail__capabilities">
            {capabilities.map((cap) => (
              <span
                key={cap}
                className="robot-detail__capability-chip"
                style={{ borderColor: typeColor, color: typeColor }}
              >
                {cap}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Section 6: State History */}
      <div className="robot-detail__section">
        <div className="robot-detail__section-label">State History</div>
        {historySlice.length === 0 ? (
          <div className="robot-detail__history-empty">No transitions yet</div>
        ) : (
          <ul className="robot-detail__history-list">
            {historySlice.map((entry, i) => (
              <li key={`${entry.timestamp}-${i}`} className="robot-detail__history-item">
                <span className="robot-detail__history-time">
                  {formatRelativeTime(entry.timestamp)}
                </span>
                <span
                  className="robot-detail__history-from"
                  style={{ color: STATE_COLORS[entry.from] || '#556080' }}
                >
                  {(STATE_LABELS[entry.from] || entry.from)}
                </span>
                <span className="robot-detail__history-arrow">&rarr;</span>
                <span
                  className="robot-detail__history-to"
                  style={{ color: STATE_COLORS[entry.to] || '#556080' }}
                >
                  {(STATE_LABELS[entry.to] || entry.to)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
