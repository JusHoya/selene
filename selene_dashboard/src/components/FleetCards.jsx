import React from 'react';
import { STATE_COLORS, STATE_LABELS, TYPE_COLORS, batteryColor } from '../utils/colors';
// A-stale: shared threshold so cards, map, RobotDetail and MissionProgress all
// agree on what "stale" means.
import { isStale as robotIsStale } from '../utils/staleness';
// D-31: shared with FleetMap, RobotDetail and MissionProgress.
import { hasPositionFix } from '../utils/poseFix';
import './FleetCards.css';

function FleetCard({ robot, selected, onSelect }) {
  const {
    robot_id,
    robot_type,
    fsm_state,
    battery_level,
    task_progress,
  } = robot;

  const isStale = robotIsStale(robot);
  // D-31: this card is the operator's evidence that the robot EXISTS when the
  // map is not drawing it. The card is never suppressed — losing the icon and
  // the card together would be indistinguishable from a robot that had gone
  // away — so it carries the reason instead.
  const noPositionFix = !hasPositionFix(robot);
  const batteryPercent = Math.round((battery_level ?? 0) * 100);
  const typeColor = TYPE_COLORS[robot_type] || '#8892a8';
  const stateColor = STATE_COLORS[fsm_state] || '#556080';
  const stateLabel = STATE_LABELS[fsm_state] || fsm_state || 'Unknown';
  const taskPercent = Math.round((task_progress ?? 0) * 100);
  const showTask = task_progress > 0;

  let className = 'fleet-card';
  if (selected) className += ' fleet-card--selected';
  if (isStale) className += ' fleet-card--stale';
  if (noPositionFix) className += ' fleet-card--nofix';

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

      <div className="fleet-card__badges">
        <span
          className="fleet-card__state"
          style={{ background: stateColor }}
        >
          {stateLabel}
        </span>
        {/* D-31: sits beside the FSM state rather than replacing it, because
            the robot's state is still being reported truthfully — it is only
            its position that is unknown. */}
        {noPositionFix && (
          <span
            className="fleet-card__nofix"
            title="No position fix — not drawn on the map (RobotState.pose_valid is false)"
          >
            NO FIX
          </span>
        )}
      </div>

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
