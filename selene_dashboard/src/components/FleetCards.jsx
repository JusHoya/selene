import React from 'react';
import { STATE_COLORS, STATE_LABELS, TYPE_COLORS, batteryColor } from '../utils/colors';
import './FleetCards.css';

const STALE_THRESHOLD_MS = 5000;

function FleetCard({ robot, selected, onSelect }) {
  const {
    robot_id,
    robot_type,
    fsm_state,
    battery_level,
    task_progress,
    lastUpdate,
  } = robot;

  const isStale = lastUpdate && (Date.now() - lastUpdate) > STALE_THRESHOLD_MS;
  const batteryPercent = Math.round((battery_level ?? 0) * 100);
  const typeColor = TYPE_COLORS[robot_type] || '#8892a8';
  const stateColor = STATE_COLORS[fsm_state] || '#556080';
  const stateLabel = STATE_LABELS[fsm_state] || fsm_state || 'Unknown';
  const taskPercent = Math.round((task_progress ?? 0) * 100);
  const showTask = task_progress > 0;

  let className = 'fleet-card';
  if (selected) className += ' fleet-card--selected';
  if (isStale) className += ' fleet-card--stale';

  return (
    <div
      className={className}
      style={{ borderLeftColor: typeColor }}
      onClick={() => onSelect(robot_id)}
    >
      <div className="fleet-card__header">
        <span
          className="fleet-card__type-dot"
          style={{ background: typeColor }}
        />
        <span className="fleet-card__id">{robot_id}</span>
      </div>

      <span
        className="fleet-card__state"
        style={{ background: stateColor }}
      >
        {stateLabel}
      </span>

      <div className="fleet-card__battery">
        <div className="fleet-card__battery-track">
          <div
            className="fleet-card__battery-fill"
            style={{
              width: `${batteryPercent}%`,
              background: batteryColor(battery_level ?? 0),
            }}
          />
        </div>
        <span className="fleet-card__battery-text">{batteryPercent}%</span>
      </div>

      {showTask && (
        <div className="fleet-card__task">
          Task: <span className="fleet-card__task-value">{taskPercent}%</span>
        </div>
      )}
    </div>
  );
}

export default function FleetCards({ robots, selectedRobotId, onSelectRobot }) {
  const robotList = robots ? Object.values(robots) : [];

  if (robotList.length === 0) {
    return (
      <div className="fleet-cards">
        <div className="fleet-cards__empty">Waiting for fleet data...</div>
      </div>
    );
  }

  return (
    <div className="fleet-cards">
      {robotList.map((robot) => (
        <FleetCard
          key={robot.robot_id}
          robot={robot}
          selected={robot.robot_id === selectedRobotId}
          onSelect={onSelectRobot}
        />
      ))}
    </div>
  );
}
