import React from 'react';
import { TYPE_COLORS } from '../utils/colors';
import './AlertLog.css';

const SEVERITY_COLORS = {
  INFO: 'var(--text-muted)',
  WARN: 'var(--accent-amber)',
  ERROR: 'var(--accent-red)',
  CRITICAL: 'var(--accent-red)',
};

function formatRelativeTime(timestamp) {
  const diff = Math.floor((Date.now() - timestamp) / 1000);
  if (diff < 5) return 'now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function robotSourceColor(sourceId) {
  if (!sourceId) return 'var(--text-secondary)';
  if (sourceId.startsWith('scout')) return TYPE_COLORS.scout;
  if (sourceId.startsWith('excavator')) return TYPE_COLORS.excavator;
  if (sourceId.startsWith('hauler')) return TYPE_COLORS.hauler;
  return 'var(--text-secondary)';
}

function AlertEntry({ alert }) {
  const { severity, source_robot_id, message, timestamp } = alert;
  const dotColor = SEVERITY_COLORS[severity] || SEVERITY_COLORS.INFO;
  const isCritical = severity === 'CRITICAL';

  let dotClass = 'alert-entry__dot';
  if (isCritical) dotClass += ' alert-entry__dot--critical';

  return (
    <div className="alert-entry animate-fade-in">
      <span
        className={dotClass}
        style={{ background: dotColor }}
      />
      <span className="alert-entry__time">
        {formatRelativeTime(timestamp)}
      </span>
      <span
        className="alert-entry__source"
        style={{ color: robotSourceColor(source_robot_id) }}
      >
        {source_robot_id || 'system'}
      </span>
      <span className="alert-entry__message">{message}</span>
    </div>
  );
}

export default function AlertLog({ alerts }) {
  const alertList = alerts || [];

  return (
    <div className="alert-log">
      <div className="alert-log__title">Alerts</div>
      {alertList.length === 0 ? (
        <div className="alert-log__empty">No alerts</div>
      ) : (
        <div className="alert-log__list">
          {alertList.map((alert) => (
            <AlertEntry key={alert.alert_id || alert.timestamp} alert={alert} />
          ))}
        </div>
      )}
    </div>
  );
}
