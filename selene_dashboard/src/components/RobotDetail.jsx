import React, { useState, useEffect, useRef, useMemo } from 'react';
import { STATE_COLORS, STATE_LABELS, TYPE_COLORS, TYPE_LABELS, batteryColor } from '../utils/colors';
import { SERVICES, SERVICE_TYPES } from '../utils/rosTopics';
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

export default function RobotDetail({ robot, state, dispatch, callService }) {
  // Wave2-A4: Recent override action history (in-memory, last 5)
  const [recentActions, setRecentActions] = useState([]);

  // Wave2-A4: Rolling window of battery samples for time-to-empty estimate
  const batteryHistoryRef = useRef([]);
  const [batteryTick, setBatteryTick] = useState(0);

  useEffect(() => {
    if (!robot || typeof robot.battery_level !== 'number') return;
    const now = Date.now();
    batteryHistoryRef.current.push({ t: now, b: robot.battery_level });
    // Keep only samples from the last 30s
    const cutoff = now - 30000;
    batteryHistoryRef.current = batteryHistoryRef.current.filter((s) => s.t >= cutoff);
    // Bump tick so downstream useMemo recomputes
    setBatteryTick((prev) => prev + 1);
  }, [robot?.battery_level]);

  // Wave2-A4: Send override helper — records outcome to recentActions
  const recordAction = (cmd, result, message) => {
    setRecentActions((prev) => {
      const next = [
        ...prev,
        {
          time: new Date().toLocaleTimeString(),
          cmd,
          result,
          message: message || '',
        },
      ];
      return next.slice(-5);
    });
  };

  const callOverride = async (command, target = { x: 0, y: 0, z: 0 }) => {
    if (!robot || !callService) return;
    // Confirmation — window.confirm is fine for Sprint 0; a modal can come later
    const ok = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm(`${command.replace(/_/g, ' ')} for ${robot.robot_id}?`)
      : true;
    if (!ok) return;
    try {
      const result = await callService(
        SERVICES.OVERRIDE_ROBOT,
        SERVICE_TYPES.OVERRIDE_ROBOT,
        { robot_id: robot.robot_id, command, target },
      );
      if (result && result.success) {
        recordAction(command, 'ok', result.message || '');
      } else {
        recordAction(command, 'fail', (result && result.message) || '');
      }
    } catch (err) {
      recordAction(command, 'fail', err?.message || 'call failed');
    }
  };

  const handleCancelTask = () => callOverride('cancel_task');
  const handleForceRecharge = () => callOverride('force_recharge');
  const handleSendToLocation = () => {
    if (!robot || !dispatch) return;
    dispatch({
      type: 'SET_PICKER_MODE',
      payload: { mode: 'send_to_location', robotId: robot.robot_id },
    });
  };

  // Wave2-A4: Watch for a picker result for this specific robot
  useEffect(() => {
    if (!robot || !dispatch) return;
    const pickerRobot = state?.pickerContext?.robotId;
    if (
      state?.pickerResult
      && state?.pickerMode === 'send_to_location'
      && pickerRobot === robot.robot_id
    ) {
      const { x, y } = state.pickerResult;
      dispatch({ type: 'CLEAR_PICKER_MODE' });
      callOverride('send_to_location', { x, y, z: 0 });
    }
  }, [state?.pickerResult, state?.pickerMode, robot?.robot_id]);

  // Wave2-A4: Time-to-empty estimate from a 30s rolling window of battery samples.
  // Uses batteryTick so it recomputes on each new sample without us having to
  // bust the useMemo cache manually.
  const timeToEmpty = useMemo(() => {
    const hist = batteryHistoryRef.current;
    if (!robot || hist.length < 2) return null;
    const first = hist[0];
    const last = hist[hist.length - 1];
    const dt = (last.t - first.t) / 1000;
    const dB = first.b - last.b;
    if (dB <= 0 || dt <= 0) return null;
    const dropPerSec = dB / dt;
    if (dropPerSec <= 0) return null;
    const secsRemaining = robot.battery_level / dropPerSec;
    if (!Number.isFinite(secsRemaining) || secsRemaining <= 0) return null;
    if (secsRemaining > 86400) return '>24h';
    const totalMin = Math.floor(secsRemaining / 60);
    if (totalMin < 1) return '<1m';
    if (totalMin < 60) return `${totalMin}m`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return `${h}h ${m}m`;
  }, [robot?.battery_level, batteryTick]);

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

  // Wave2-A4: Disable override buttons when we have no service client
  const overrideDisabled = !callService;
  // Wave2-A4: Indicate that this robot is awaiting a target-pick on the map
  const awaitingPick = state?.pickerMode === 'send_to_location'
    && state?.pickerContext?.robotId === robot_id;

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
            {/* Wave2-A4: Time-to-empty estimate (30s rolling window) */}
            {timeToEmpty && !isCharging && (
              <span className="robot-detail__battery-eta">
                <span className="robot-detail__battery-eta-label">Empty in</span>
                <span className="robot-detail__battery-eta-value">{timeToEmpty}</span>
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

      {/* Wave2-A4: Section — Operator Override */}
      <div className="robot-detail__section robot-detail__overrides">
        <div className="robot-detail__section-label">Operator Override</div>
        <div className="robot-detail__override-buttons">
          <button
            type="button"
            className={
              'robot-detail__override-btn'
              + (awaitingPick ? ' robot-detail__override-btn--active' : '')
            }
            onClick={handleSendToLocation}
            disabled={overrideDisabled}
          >
            {awaitingPick ? 'Pick on Map\u2026' : 'Send to Location'}
          </button>
          <button
            type="button"
            className="robot-detail__override-btn"
            onClick={handleCancelTask}
            disabled={overrideDisabled}
          >
            Cancel Task
          </button>
          <button
            type="button"
            className="robot-detail__override-btn"
            onClick={handleForceRecharge}
            disabled={overrideDisabled}
          >
            Force Recharge
          </button>
        </div>
        {recentActions.length > 0 && (
          <div className="robot-detail__recent-actions">
            <div className="robot-detail__subsection-label">Recent Actions</div>
            <ul className="robot-detail__recent-actions-list">
              {recentActions.slice().reverse().map((a, i) => (
                <li
                  key={`${a.time}-${i}`}
                  className="robot-detail__recent-action"
                >
                  <span className="robot-detail__recent-action-time">{a.time}</span>
                  <span className="robot-detail__recent-action-cmd">{a.cmd}</span>
                  <span
                    className={`robot-detail__recent-action-result robot-detail__recent-action-result--${a.result}`}
                  >
                    {a.result}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

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
