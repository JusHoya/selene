import React, { useState, useEffect } from 'react';
import { isStale } from '../utils/staleness';
import './MissionProgress.css';

// A-stale: staleness is a function of wall-clock time, so this panel needs its
// own heartbeat. Without it, a fleet that stops publishing altogether never
// re-renders and the counts stay frozen at their last live values.
const TICK_MS = 1000;

// D-06: kg. The tolerance the conservation chip uses, matching
// MaterialInventory.check_conservation(tolerance=0.01) on the orchestrator side
// so the two cannot disagree about what "closed" means.
const CONSERVATION_TOLERANCE_KG = 0.01;

// D-06: renamed from formatSimTime. It formats two different durations now
// (elapsed_sim_time and fleet_uptime_sec) and neither of them is simulation
// time — see the "Elapsed (wall)" tile below.
function formatDuration(seconds) {
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
  const atSite = p.at_site_quantity;
  const inTransit = p.in_transit_quantity;
  const deposited = p.deposited_quantity;
  const unaccounted = p.unaccounted_quantity;
  const distance = p.fleet_distance_total;
  const energy = p.fleet_energy_total;
  const elapsed = p.elapsed_sim_time;
  const uptime = p.fleet_uptime_sec;
  const eventsApplied = p.material_events_applied;

  // D-06: the mass chain has production writers now — sim publishes a fill
  // FRACTION, the HAL derives mass_kg from the RCDL capacity_kg, the skills
  // measure a sensor delta and the agent publishes MaterialEvent, which the
  // orchestrator applies to MaterialInventory. material_events_applied counts
  // the events that actually reached the ledger, so it answers "has the
  // pipeline reported anything yet" directly.
  //
  // It replaces `(extracted > 0) || (inTransit > 0) || (deposited > 0)`, which
  // could not tell an UNINSTRUMENTED mission from a correctly instrumented one
  // that is still drilling its first hopper — for the first minute of every
  // run, a working pipeline was labelled "not instrumented".
  const massInstrumented = eventsApplied > 0;

  // Primary progress bar = deposited / target. Both ends are real measurements
  // now: the target is HTNPlanner._target_kg and the numerator is the ledger's
  // total of unloaded mass.
  let depositedPct = 0;
  if (target > 0 && deposited != null) {
    depositedPct = Math.min(100, Math.max(0, (deposited / target) * 100));
  }

  // D-06 / FR-ISRU-2 ("no material is lost or duplicated"), computed client-side
  // from fields already on the wire — no extra message field.
  //
  // Two independent clauses, and the second is the one that means something:
  //  * the identity extracted == at_site + in_transit + deposited closes
  //    STRUCTURALLY once at_site is tracked, so it can realistically only trip
  //    on float drift;
  //  * unaccounted_quantity is mass a hauler's load cell reported loading that
  //    no excavator's hopper reported extracting. That is a genuine
  //    cross-instrument disagreement and zero is its only healthy value.
  const identityResidual = massInstrumented
    ? Math.abs((extracted || 0) - ((atSite || 0) + (inTransit || 0) + (deposited || 0)))
    : 0;
  const conservationBroken = massInstrumented
    && ((unaccounted || 0) > CONSERVATION_TOLERANCE_KG
      || identityResidual > CONSERVATION_TOLERANCE_KG);

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
                  &mdash; awaiting first extraction
                </span>
              </>
            )}
          </div>
        </div>
      )}

      {/* D-06: conservation chip. Only meaningful once the ledger has applied
          at least one event, so it is not rendered before that. */}
      {massInstrumented && (
        <div
          className={
            'mission-progress__conservation'
            + (conservationBroken ? ' mission-progress__conservation--broken' : '')
          }
          title={
            conservationBroken
              ? `unaccounted ${formatKg(unaccounted)}, identity residual `
                + `${identityResidual.toFixed(3)} kg over `
                + `${eventsApplied} ledger events`
              : `extracted == at site + in transit + deposited, and no hauler `
                + `reported loading mass no excavator reported extracting `
                + `(${eventsApplied} ledger events)`
          }
        >
          <span className="mission-progress__conservation-label">
            {conservationBroken ? 'MASS UNACCOUNTED' : 'Mass conserved'}
          </span>
          <span className="mission-progress__conservation-value">
            {conservationBroken
              ? `${formatKg(unaccounted)} unaccounted`
              : `${eventsApplied} events`}
          </span>
        </div>
      )}

      <div className="mission-progress__grid">
        {/* D-06: ISRU mass flow, four tiles that are now fed by measured sensor
            deltas. The placeholder below is kept for the window before the
            first MaterialEvent reaches the ledger — three 0.00 kg readings
            would look like a live measurement of an idle pipeline. */}
        {massInstrumented ? (
          <>
            {/* Extracted */}
            <div className="mission-progress__stat">
              <span className="mission-progress__stat-label">Extracted</span>
              <span className="mission-progress__stat-value mission-progress__stat-value--cyan">
                {formatKg(extracted)}
              </span>
            </div>

            {/* At Site — extracted but not yet loaded onto a hauler. Without
                this term the conservation identity fails whenever an excavator
                is ahead of a hauler, which is the pipeline's normal state. */}
            <div className="mission-progress__stat">
              <span className="mission-progress__stat-label">At Site</span>
              <span className="mission-progress__stat-value mission-progress__stat-value--amber">
                {formatKg(atSite)}
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
            <div className="mission-progress__stat">
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
              AWAITING FIRST EXTRACTION
            </span>
            <span className="mission-progress__uninstrumented-note">
              No MaterialEvent has reached the orchestrator&apos;s ledger yet, so
              no mass is reported. Nothing here is inferred or estimated.
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

        {/* D-06: relabelled from "Sim Time". MissionProgress.elapsed_sim_time is
            orchestrator WALL CLOCK since the node started; use_sim_time is unset
            repo-wide and /clock is not bridged, so nothing in this system runs
            on simulation time. The field keeps its name on the wire (renaming a
            published field breaks PRD MSG-7); the label stops repeating the
            claim. */}
        <div className="mission-progress__stat">
          <span
            className="mission-progress__stat-label"
            title={
              'Orchestrator wall clock since the node started. NOT Gazebo '
              + 'simulation time: use_sim_time is unset repo-wide and /clock is '
              + 'not bridged.'
            }
          >
            Elapsed (wall)
          </span>
          <span className="mission-progress__stat-value">
            {formatDuration(elapsed)}
          </span>
        </div>

        {/* D-06 / FR-DASH-7(c): fleet uptime, measured from the FIRST ROBOT
            HEARTBEAT rather than from orchestrator startup — the orchestrator is
            up for several seconds before any robot exists, so the two differ. */}
        <div className="mission-progress__stat">
          <span
            className="mission-progress__stat-label"
            title="Since the first robot heartbeat reached the orchestrator."
          >
            Fleet Uptime
          </span>
          <span className="mission-progress__stat-value">
            {formatDuration(uptime)}
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
