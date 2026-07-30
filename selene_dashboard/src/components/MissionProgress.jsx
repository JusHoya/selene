import React, { useState, useEffect } from 'react';
import { isStale } from '../utils/staleness';
import './MissionProgress.css';

// A-stale: staleness is a function of wall-clock time, so this panel needs its
// own heartbeat. Without it, a fleet that stops publishing altogether never
// re-renders and the counts stay frozen at their last live values.
const TICK_MS = 1000;

function formatSimTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '--';
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatKg(value) {
  if (value == null || Number.isNaN(value)) return '--';
  if (value >= 100) return `${value.toFixed(0)} kg`;
  if (value >= 10)  return `${value.toFixed(1)} kg`;
  return `${value.toFixed(2)} kg`;
}

function formatKm(meters) {
  if (meters == null || Number.isNaN(meters)) return '--';
  const km = meters / 1000;
  if (km >= 10) return `${km.toFixed(1)} km`;
  return `${km.toFixed(2)} km`;
}

function formatWh(value) {
  if (value == null || Number.isNaN(value)) return '--';
  if (value >= 1000) return `${(value / 1000).toFixed(1)} kWh`;
  return `${value.toFixed(1)} Wh`;
}

export default function MissionProgress({ progress, robots }) {
  const robotMap = robots || {};
  const robotEntries = Object.values(robotMap);

  // A-stale: 1 Hz heartbeat so stale/idle counts keep advancing when telemetry
  // has stopped and nothing else is triggering a re-render.
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  // A-stale: a robot whose telemetry has stopped is NOT active — it used to
  // keep counting toward "Active Robots" purely because its last-known
  // fsm_state was something other than IDLE/OFFLINE.
  const now = Date.now();
  const staleRobots = robotEntries.filter((r) => isStale(r, now));
  const idleRobots = robotEntries.filter(
    (r) => !isStale(r, now) && (r.fsm_state === 'IDLE' || r.fsm_state === 'OFFLINE')
  );
  const onTaskRobots = robotEntries.filter(
    (r) => !isStale(r, now) && r.fsm_state !== 'IDLE' && r.fsm_state !== 'OFFLINE'
  );
  const onTask = onTaskRobots.length;
  const totalRobots = robotEntries.length;

  // Progress topic fields (graceful fallback if undefined)
  const p = progress || {};
  const objective = p.objective_description || 'Mission Status';
  const target = p.target_quantity || 0;
  const extracted = p.extracted_quantity;
  const inTransit = p.in_transit_quantity;
  const deposited = p.deposited_quantity;
  const distance = p.fleet_distance_total;
  const energy = p.fleet_energy_total;
  const simTime = p.elapsed_sim_time;

  // A4: The ISRU mass fields (extracted / in_transit / deposited) come from the
  // orchestrator's MaterialInventory, which currently has NO production writers
  // — they are structurally 0.0, not a measurement. Rendering them as
  // "0.00 kg" would look like a live reading of an instrumented pipeline. Show
  // real numbers only once something actually reports a non-zero mass.
  const massInstrumented = (extracted > 0) || (inTransit > 0) || (deposited > 0);

  // Primary progress bar = deposited / target. The target IS published for real;
  // the numerator is not instrumented yet, so the bar is labelled accordingly
  // rather than showing a confident 0%.
  let depositedPct = 0;
  if (target > 0 && deposited != null) {
    depositedPct = Math.min(100, Math.max(0, (deposited / target) * 100));
  }

  return (
    <div className="mission-progress">
      <div className="mission-progress__header" title={objective}>
        {objective}
      </div>

      {target > 0 && (
        <div className="mission-progress__objective">
          <div
            className={
              'mission-progress__objective-bar'
              + (massInstrumented ? '' : ' mission-progress__objective-bar--nodata')
            }
          >
            {massInstrumented && (
              <div
                className="mission-progress__objective-fill"
                style={{ width: `${depositedPct}%` }}
              />
            )}
          </div>
          <div className="mission-progress__objective-label">
            {massInstrumented ? (
              <>
                {formatKg(deposited)} / {formatKg(target)}{' '}
                <span className="mission-progress__objective-pct">
                  ({depositedPct.toFixed(0)}%)
                </span>
              </>
            ) : (
              <>
                Objective {formatKg(target)}{' '}
                <span className="mission-progress__objective-nodata">
                  &mdash; delivered mass not instrumented
                </span>
              </>
            )}
          </div>
        </div>
      )}

      <div className="mission-progress__grid">
        {/* A4: ISRU mass flow. Real tiles only when something reports mass;
            otherwise an unmistakable placeholder instead of three 0.00 kg
            readings that look live. */}
        {massInstrumented ? (
          <>
            {/* Extracted */}
            <div className="mission-progress__stat">
              <span className="mission-progress__stat-label">Extracted</span>
              <span className="mission-progress__stat-value mission-progress__stat-value--cyan">
                {formatKg(extracted)}
              </span>
            </div>

            {/* In Transit */}
            <div className="mission-progress__stat">
              <span className="mission-progress__stat-label">In Transit</span>
              <span className="mission-progress__stat-value mission-progress__stat-value--teal">
                {formatKg(inTransit)}
              </span>
            </div>

            {/* Deposited */}
            <div className="mission-progress__stat mission-progress__stat--wide">
              <span className="mission-progress__stat-label">Deposited</span>
              <span className="mission-progress__stat-value mission-progress__stat-value--green">
                {formatKg(deposited)}
              </span>
            </div>
          </>
        ) : (
          <div className="mission-progress__stat mission-progress__stat--wide mission-progress__stat--uninstrumented">
            <span className="mission-progress__stat-label">ISRU Mass Flow</span>
            <span className="mission-progress__uninstrumented-value">
              NOT INSTRUMENTED
            </span>
            <span className="mission-progress__uninstrumented-note">
              Extracted / In Transit / Deposited have no production writers in
              the orchestrator yet, so no mass is reported. Nothing is inferred
              or estimated here.
            </span>
          </div>
        )}

        {/* Fleet Distance */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Fleet Distance</span>
          <span className="mission-progress__stat-value">
            {formatKm(distance)}
          </span>
        </div>

        {/* Energy Used */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Fleet Energy</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--amber">
            {formatWh(energy)}
          </span>
        </div>

        {/* Sim Time */}
        <div className="mission-progress__stat">
          <span className="mission-progress__stat-label">Sim Time</span>
          <span className="mission-progress__stat-value">
            {formatSimTime(simTime)}
          </span>
        </div>

        {/* A-stale: relabelled. "Active Robots 3/4" read as a fault when a
            robot was merely idle, and counted robots whose telemetry had
            stopped. Idle and no-telemetry are now broken out explicitly. */}
        <div className="mission-progress__stat mission-progress__stat--wide">
          <span className="mission-progress__stat-label">Robots On Task</span>
          <span className="mission-progress__stat-value mission-progress__stat-value--green">
            {onTask}{totalRobots > 0 ? ` of ${totalRobots}` : ''}
          </span>
          {totalRobots > 0 && (
            <span className="mission-progress__stat-sub">
              {idleRobots.length} idle
              {staleRobots.length > 0 && (
                <span className="mission-progress__stat-sub--alert">
                  {' · '}{staleRobots.length} no telemetry
                </span>
              )}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
