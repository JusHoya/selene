import React, { useState, useEffect, useRef, useMemo } from 'react';
import { STATE_COLORS, STATE_LABELS, TYPE_COLORS, TYPE_LABELS, batteryColor } from '../utils/colors';
import { SERVICES, SERVICE_TYPES } from '../utils/rosTopics';
import { isStale, staleAgeSeconds } from '../utils/staleness';
// D-31: shared with FleetMap, FleetCards and MissionProgress.
import { hasPositionFix, poseValidityReported } from '../utils/poseFix';
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

// D-05: how many override records this panel shows. The list is now derived
// from state.taskEvents, which the reducer keeps across robot selections and
// across a page reload, so this is a display window rather than the entire
// memory of what the operator did.
const MAX_RECENT_ACTIONS = 5;

// D-05: absolute time-of-day for a TaskEvent stamp.
//
// TaskEvent.stamp is the ORCHESTRATOR's wall clock. Rendering it as "12s ago"
// would silently turn any clock skew between the orchestrator host and the
// operator's browser into a fabricated elapsed time, so it is rendered
// absolutely — wrong by the same skew, but not claiming to have measured
// anything. formatRelativeTime below is still used for stateHistory, whose
// timestamps this browser took itself.
function formatClockTime(ms) {
  if (!ms) return '--:--:--';
  return new Date(ms).toLocaleTimeString();
}

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
  const taskEvents = state?.taskEvents;

  // D-05: override history is no longer local component state.
  //
  // It used to be a five-entry useState, and App.jsx keys this component on
  // robot_id (App.jsx:289, which stays — the battery rolling window and the
  // pending-confirmation panel need it), so selecting another robot unmounted
  // the component and destroyed the list. Every record of what the operator had
  // done to that robot vanished on a click, and none of it survived a reload.
  //
  // The authoritative record now arrives in TaskQueueState.events and lives in
  // the reducer, which is where it survives both. `pendingActions` below covers
  // only the service round-trip window, before the orchestrator's own event
  // comes back.
  const [pendingActions, setPendingActions] = useState([]);
  const nextLocalIdRef = useRef(0);

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

  // D-05: settle one optimistic entry with what the service call returned.
  const settleLocalAction = (localId, result, message) => {
    setPendingActions((prev) => prev.map((a) => (
      a.localId === localId ? { ...a, result, message: message || '' } : a
    )));
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

    // D-05: the optimistic entry, and the seq floor that retires it.
    //
    // seqFloor is the highest TaskEvent seq we hold at the instant of the call.
    // The orchestrator appends a TaskEvent for every operator command it
    // handles — accepted or rejected — so the first operator event for this
    // robot and this action with a HIGHER seq is this call coming back, and the
    // optimistic row is dropped in favour of the authoritative one. seq is used
    // rather than a timestamp because it needs no clock agreement between the
    // two machines.
    //
    // Imprecise in exactly one window: if no snapshot has arrived yet the floor
    // is -1, so an OLDER event for the same command, replayed out of the
    // orchestrator's ring, can retire the row early. The authoritative row for
    // the real command then arrives within one publish period anyway, so the
    // cost is a row that stops saying "local" half a second early.
    const localId = nextLocalIdRef.current + 1;
    nextLocalIdRef.current = localId;
    const held = taskEvents || [];
    const seqFloor = held.length > 0 ? held[held.length - 1].seq : -1;
    setPendingActions((prev) => [
      ...prev,
      {
        localId,
        seqFloor,
        cmd: command,
        time: new Date().toLocaleTimeString(),
        result: 'sending',
        message: '',
      },
    ].slice(-MAX_RECENT_ACTIONS));

    // A8: callService is null when rosbridge is disconnected — surface that as
    // a visible failed action rather than doing nothing. Note that this one is
    // never reconciled away: the orchestrator never saw the command, so no
    // TaskEvent will ever arrive for it, and the local record is the only
    // record there is.
    if (!callService) {
      settleLocalAction(localId, 'fail', 'rosbridge not connected');
      return;
    }
    try {
      const result = await callService(
        SERVICES.OVERRIDE_ROBOT,
        SERVICE_TYPES.OVERRIDE_ROBOT,
        { robot_id: robot.robot_id, command, target },
      );
      if (result && result.success) {
        settleLocalAction(localId, 'ok', result.message || '');
      } else {
        settleLocalAction(
          localId, 'fail', (result && result.message) || 'rejected by orchestrator',
        );
      }
    } catch (err) {
      settleLocalAction(localId, 'fail', err?.message || 'call failed');
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

  // D-05: the authoritative override history for this robot, newest first.
  //
  // Derived, not stored — so it is identical whether the operator has been
  // watching this robot for an hour or has just selected it, and whether or not
  // the page has been reloaded since the command was issued. The orchestrator
  // replays its whole event ring in every TaskQueueState snapshot, so a browser
  // that loads mid-mission gets the recent overrides for free.
  const operatorActions = useMemo(() => {
    const events = taskEvents || [];
    const rows = [];
    for (let i = events.length - 1; i >= 0; i -= 1) {
      if (rows.length >= MAX_RECENT_ACTIONS) break;
      const e = events[i];
      if (e.kind !== 'operator' || e.robot_id !== robotId) continue;
      rows.push({
        key: `event-${e.seq}`,
        time: formatClockTime(e.stamp_ms),
        cmd: e.action,
        // TaskEvent.accepted is the orchestrator's own verdict, including on
        // commands it REJECTED — which the old local list could only record
        // when the rejection came back through this component's own call.
        result: e.accepted ? 'ok' : 'fail',
        message: e.detail,
        local: false,
      });
    }
    return rows;
  }, [taskEvents, robotId]);

  // D-05: retire an optimistic entry once its authoritative event arrives.
  useEffect(() => {
    const events = taskEvents || [];
    setPendingActions((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.filter((p) => !events.some(
        (e) => e.kind === 'operator'
          && e.robot_id === robotId
          && e.action === p.cmd
          && e.seq > p.seqFloor
      ));
      // Returning `prev` unchanged is what keeps this effect from looping: the
      // state identity only changes when something was actually retired.
      return next.length === prev.length ? prev : next;
    });
  }, [taskEvents, robotId]);

  // Optimistic rows first (they are the newest by construction), then the
  // authoritative ones.
  const recentActions = useMemo(() => {
    const local = pendingActions
      .slice()
      .reverse()
      .map((a) => ({
        key: `local-${a.localId}`,
        time: a.time,
        cmd: a.cmd,
        result: a.result,
        message: a.message,
        local: true,
      }));
    return [...local, ...operatorActions].slice(0, MAX_RECENT_ACTIONS);
  }, [pendingActions, operatorActions]);

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
    battery_capacity_wh,
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

  // D-31: is `pose` a measurement? This panel is the only place in the
  // dashboard that prints the robot's position as a NUMBER, which is the most
  // credible form the fabricated (0, 0) could take — "X 0.0 m / Y 0.0 m" to one
  // decimal reads as an instrument reading, not as a default. The map can drop
  // an icon; a numeric field has to say what it is not showing.
  const positionFix = hasPositionFix(robot);
  // ...and is `positionFix` itself measured? False means the publisher carried
  // no pose_valid field at all, so a fix is being ASSUMED under the legacy rule
  // in utils/poseFix.js. The assumption is stated on screen rather than left to
  // whoever reads the source later.
  const fixReported = poseValidityReported(robot);

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

      {/* D-31: explicit no-position-fix banner, deliberately shaped like the
          no-telemetry banner above and deliberately distinct from it. The two
          are different faults and can occur separately: a robot with no fix is
          talking normally (that is how we know it has no fix), and a stale
          robot's last pose may have been perfectly good. Amber, not red — see
          the note in FleetMap.css. */}
      {!positionFix && (
        <div className="robot-detail__nofix-banner">
          <span className="robot-detail__nofix-banner-title">No position fix</span>
          <span className="robot-detail__nofix-banner-detail">
            This robot reports <code>pose_valid=false</code>: its odometry has
            not produced a reading yet, so it is not drawn on the map and no
            coordinates are shown. State and battery below are unaffected.
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
            {/* D-06: the robot's own RCDL battery capacity, reported by the
                agent on RobotState.battery_capacity_wh. Rendered only when
                positive: 0 means the agent predates the field, which is
                "unknown", not "a robot with no battery". This is the number
                FleetMonitor now converts battery_level deltas to watt-hours
                with, in place of a single hardcoded 50 Wh for every robot. */}
            {typeof battery_capacity_wh === 'number'
              && Number.isFinite(battery_capacity_wh)
              && battery_capacity_wh > 0 && (
              <span className="robot-detail__battery-capacity">
                {battery_capacity_wh.toFixed(0)} Wh capacity
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
          {/* D-31: X, Y and Heading all come out of the SAME OdometryReading,
              so all three are withheld together. Withholding only the pair
              would leave a heading that is really the sensor's default 0.0 rad
              standing next to two dashes, which reads as "we know which way it
              is pointing but not where it is" — a claim nothing supports. */}
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">X</span>
            <span
              className={'robot-detail__stat-value'
                + (positionFix ? '' : ' robot-detail__stat-value--nofix')}
            >
              {positionFix ? `${(pose?.x ?? 0).toFixed(1)} m` : 'NO FIX'}
            </span>
          </div>
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">Y</span>
            <span
              className={'robot-detail__stat-value'
                + (positionFix ? '' : ' robot-detail__stat-value--nofix')}
            >
              {positionFix ? `${(pose?.y ?? 0).toFixed(1)} m` : 'NO FIX'}
            </span>
          </div>
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">Heading</span>
            <span
              className={'robot-detail__stat-value'
                + (positionFix ? '' : ' robot-detail__stat-value--nofix')}
            >
              {positionFix ? `${heading}°` : 'NO FIX'}
            </span>
          </div>
          {/* Speed is NOT withheld, and that is a judgement rather than an
              oversight. It comes from RobotState.velocity — the encoder twist,
              which the orchestrator now reads as "the only motion evidence it
              can see" (D-30) — and not from the odometry pose. A robot with no
              position fix can still truthfully report that its wheels are
              turning, and that is exactly the case D-24/D-25 made expensive:
              wheels at 100% slip while the position estimate said otherwise. */}
          <div className="robot-detail__stat">
            <span className="robot-detail__stat-label">Speed</span>
            <span className="robot-detail__stat-value">{speed} m/s</span>
          </div>
        </div>
        {/* D-31: the legacy-publisher case, stated instead of assumed. The
            coordinates above are being shown because no pose_valid arrived to
            qualify them, not because one arrived saying they are good. See the
            three-state decode in utils/poseFix.js — over rosbridge an absent
            key is `undefined`, which is distinguishable from an explicit
            false, unlike in ROS 2 itself. */}
        {!fixReported && (
          <div
            className="robot-detail__fix-unreported"
            title={
              'This robot’s RobotState carries no pose_valid field, so the '
              + 'dashboard cannot tell a real odometry reading from the '
              + 'sensor’s (0, 0) default. Rebuild all six packages against '
              + 'the current selene_msgs (D-31).'
            }
          >
            Position unverified &mdash; publisher sends no <code>pose_valid</code>
          </div>
        )}
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
              {recentActions.map((a) => (
                <li
                  key={a.key}
                  className="robot-detail__recent-action"
                >
                  <div className="robot-detail__recent-action-head">
                    <span className="robot-detail__recent-action-time">{a.time}</span>
                    <span className="robot-detail__recent-action-cmd">
                      {a.cmd}
                      {/* D-05: an entry this browser is still waiting on, or one
                          the orchestrator never received. Marked so it is not
                          read as part of the orchestrator's own record. */}
                      {a.local && (
                        <span className="robot-detail__recent-action-local">
                          local
                        </span>
                      )}
                    </span>
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
