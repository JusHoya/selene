import React, { useState, useEffect, useRef, useMemo } from 'react';
import { STATE_COLORS, STATE_LABELS, TYPE_COLORS, TYPE_LABELS, batteryColor } from '../utils/colors';
import { SERVICES, SERVICE_TYPES } from '../utils/rosTopics';
import { isStale, staleAgeSeconds } from '../utils/staleness';
import BatteryGauge from './BatteryGauge';
import './RobotDetail.css';

// A-stale: 1 Hz heartbeat. Needed because a robot that has stopped publishing
// generates no re-renders, which is exactly the case we must surface.
const TICK_MS = 1000;

// A-window-confirm: human-readable labels for the confirmation panel.
const COMMAND_LABELS = {
  cancel_task: 'Cancel current task',
  force_recharge: 'Force return to recharge',
  send_to_location: 'Send to picked location',
};

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
  // Pulled out before the hooks so effect dependency lists can be exhaustive
  // (the `robot` object identity changes on every telemetry tick).
  const robotId = robot?.robot_id;
  const pickerResult = state?.pickerResult;
  const pickerMode = state?.pickerMode;
  const pickerRobotId = state?.pickerContext?.robotId;

  // Wave2-A4: Recent override action history (in-memory, last 5)
  const [recentActions, setRecentActions] = useState([]);

  // A-window-confirm: pending override awaiting in-app confirmation.
  // { command, target } | null
  const [pendingOverride, setPendingOverride] = useState(null);

  // Wave2-A4: Rolling window of battery samples for time-to-empty estimate
  const batteryHistoryRef = useRef([]);
  const [batteryTick, setBatteryTick] = useState(0);

  // A-stale: wall-clock heartbeat for the no-telemetry banner.
  const [, setClockTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setClockTick((n) => n + 1), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!robot || typeof robot.battery_level !== 'number') return;
    const now = Date.now();
    batteryHistoryRef.current.push({ t: now, b: robot.battery_level });
    // Keep only samples from the last 30s
    const cutoff = now - 30000;
    batteryHistoryRef.current = batteryHistoryRef.current.filter((s) => s.t >= cutoff);
    // Bump tick so downstream useMemo recomputes
    setBatteryTick((prev) => prev + 1);
    // Narrowing to battery_level is deliberate. RobotState arrives at 2 Hz, so
    // the `robot` object gets a new identity on every tick; depending on it
    // would push a duplicate sample into the 30 s rolling window on every
    // telemetry frame even when the level has not moved, skewing the
    // time-to-empty slope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // A-window-confirm: actually send the override. The confirmation step lives
  // in the in-app panel below (see pendingOverride) — window.confirm used to be
  // called here on EVERY override, including the map-click send_to_location
  // path. It blocked the renderer: on 2026-07-29 a reviewer's automated map
  // click timed out after 30 s while page script and requestAnimationFrame kept
  // running, and stubbing window.confirm to auto-accept made the same click
  // complete immediately. It also popped a native "localhost:3000 says:" dialog
  // in the middle of the dark UI. That 30 s figure is the reviewer's
  // pre-change observation; the fixed path has not itself been re-measured.
  const runOverride = async (command, target = { x: 0, y: 0, z: 0 }) => {
    if (!robot) return;
    // A8: callService is null when rosbridge is disconnected — surface that as
    // a visible failed action rather than doing nothing.
    if (!callService) {
      recordAction(command, 'fail', 'rosbridge not connected');
      return;
    }
    try {
      const result = await callService(
        SERVICES.OVERRIDE_ROBOT,
        SERVICE_TYPES.OVERRIDE_ROBOT,
        { robot_id: robot.robot_id, command, target },
      );
      if (result && result.success) {
        recordAction(command, 'ok', result.message || '');
      } else {
        recordAction(command, 'fail', (result && result.message) || 'rejected by orchestrator');
      }
    } catch (err) {
      recordAction(command, 'fail', err?.message || 'call failed');
    }
  };

  // A-window-confirm: stage the override; nothing is sent until Confirm.
  const requestOverride = (command, target = { x: 0, y: 0, z: 0 }) => {
    if (!robot) return;
    setPendingOverride({ command, target });
  };

  const handleCancelTask = () => requestOverride('cancel_task');
  const handleForceRecharge = () => requestOverride('force_recharge');
  const handleSendToLocation = () => {
    if (!robot || !dispatch) return;
    setPendingOverride(null);
    dispatch({
      type: 'SET_PICKER_MODE',
      payload: { mode: 'send_to_location', robotId: robot.robot_id },
    });
  };

  const confirmPending = () => {
    const pending = pendingOverride;
    setPendingOverride(null);
    if (pending) runOverride(pending.command, pending.target);
  };

  // Wave2-A4: Watch for a picker result for this specific robot.
  // A-window-confirm: the picked point now stages a confirmation showing the
  // actual coordinates, instead of firing the service straight from the effect.
  useEffect(() => {
    if (!robotId || !dispatch) return;
    if (
      pickerResult
      && pickerMode === 'send_to_location'
      && pickerRobotId === robotId
    ) {
      const { x, y } = pickerResult;
      dispatch({ type: 'CLEAR_PICKER_MODE' });
      setPendingOverride({ command: 'send_to_location', target: { x, y, z: 0 } });
    }
  }, [pickerResult, pickerMode, pickerRobotId, robotId, dispatch]);

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
    // Same reasoning as the sampling effect above: batteryTick is the intended
    // recompute trigger, and depending on the whole `robot` object would
    // recompute at 2 Hz for no benefit. Only battery_level is read here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // Wave2-A4 / A8: no service client means rosbridge is not connected.
  const overrideDisabled = !callService;
  // Wave2-A4: Indicate that this robot is awaiting a target-pick on the map
  const awaitingPick = pickerMode === 'send_to_location'
    && pickerRobotId === robot_id;

  // A-stale: telemetry has stopped for this robot. Everything below (position,
  // battery, speed, task progress) is then a LAST-KNOWN value, not live.
  const telemetryStale = isStale(robot);
  const staleSeconds = staleAgeSeconds(robot);

  return (
    <div className={'robot-detail animate-slide-in' + (telemetryStale ? ' robot-detail--stale' : '')}>
      {/* A-stale: explicit no-telemetry banner. Without this, a robot whose
          telemetry had stopped still showed live-looking values here. */}
      {telemetryStale && (
        <div className="robot-detail__stale-banner">
          <span className="robot-detail__stale-banner-title">No telemetry</span>
          <span className="robot-detail__stale-banner-detail">
            Last update {staleSeconds}s ago &mdash; values below are last known,
            not live
          </span>
        </div>
      )}

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

        {/* A8: make "not connected" visible instead of silently-disabled buttons */}
        {overrideDisabled && (
          <div className="robot-detail__override-offline">
            rosbridge not connected &mdash; overrides unavailable
          </div>
        )}

        {/* A-window-confirm: in-app confirmation, same pattern as TaskInjector.
            Still a genuine guard: nothing is sent until Confirm is pressed. */}
        {pendingOverride && (
          <div className="robot-detail__confirm">
            <p>
              {COMMAND_LABELS[pendingOverride.command] || pendingOverride.command}
              {' for '}
              <strong>{robot_id}</strong>
              {pendingOverride.command === 'send_to_location'
                ? ` at (${pendingOverride.target.x.toFixed(1)}, ${pendingOverride.target.y.toFixed(1)})`
                : ''}
              ?
            </p>
            <div className="robot-detail__confirm-buttons">
              <button type="button" onClick={confirmPending}>
                Confirm
              </button>
              <button type="button" onClick={() => setPendingOverride(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {recentActions.length > 0 && (
          <div className="robot-detail__recent-actions">
            <div className="robot-detail__subsection-label">Recent Actions</div>
            <ul className="robot-detail__recent-actions-list">
              {recentActions.slice().reverse().map((a, i) => (
                <li
                  key={`${a.time}-${i}`}
                  className="robot-detail__recent-action"
                >
                  <div className="robot-detail__recent-action-head">
                    <span className="robot-detail__recent-action-time">{a.time}</span>
                    <span className="robot-detail__recent-action-cmd">{a.cmd}</span>
                    <span
                      className={`robot-detail__recent-action-result robot-detail__recent-action-result--${a.result}`}
                    >
                      {a.result}
                    </span>
                  </div>
                  {/* A8: render the message the service actually returned —
                      it was recorded but never displayed. */}
                  {a.message && (
                    <div
                      className={`robot-detail__recent-action-message robot-detail__recent-action-message--${a.result}`}
                      title={a.message}
                    >
                      {a.message}
                    </div>
                  )}
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
