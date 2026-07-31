import React, { useMemo, useCallback } from 'react';
import { TYPE_COLORS } from '../utils/colors';
import './TaskQueue.css';

// Status priority order (lower = shown first in the active list).
// D-03: these are the TaskStatus enum NAMES the orchestrator now publishes
// verbatim in TaskQueueState.tasks[].status — they are no longer inferred
// client-side, so AUCTIONING (which the inference could never produce) and
// INTERRUPTED (which used to live for microseconds before being overwritten
// with PENDING) are both real, resting statuses now.
const STATUS_ORDER = {
  IN_PROGRESS: 0,
  ASSIGNED: 1,
  AUCTIONING: 2,
  PENDING: 3,
  INTERRUPTED: 4,
  COMPLETED: 5,
  FAILED: 6,
};

const ACTIVE_STATUSES = new Set([
  'IN_PROGRESS', 'ASSIGNED', 'AUCTIONING', 'PENDING', 'INTERRUPTED',
]);
const FINISHED_STATUSES = new Set(['COMPLETED', 'FAILED']);

// D-05: how many events the history list shows at once. state.taskEvents holds
// up to 200; this is the display window, and the list is scrollable.
const MAX_EVENT_ROWS = 40;

// Unicode glyphs for task types
const TYPE_ICONS = {
  prospect: '◉',   // ◉  fisheye — survey
  survey: '◉',
  excavate: '⛏',   // ⛏  pick
  haul: '⛟',        // ⛟  truck-ish
  // ⚑  flag — the HTN's virtual decision task. It is resolved by the planner
  // and never auctioned (orchestrator_node.py:1576), but it IS a row in the
  // orchestrator's queue, so it appears here now that the table is a
  // projection of that queue rather than of announcements.
  select_site: '⚑',
};

function typeIcon(type) {
  if (!type) return '□'; // ▢
  const key = String(type).toLowerCase();
  return TYPE_ICONS[key] || '□';
}

// robot_id prefix -> accent color (scout_01 -> scout)
function robotColor(robotId) {
  if (!robotId) return 'var(--text-dim)';
  if (robotId.startsWith('scout')) return TYPE_COLORS.scout;
  if (robotId.startsWith('excavator')) return TYPE_COLORS.excavator;
  if (robotId.startsWith('hauler')) return TYPE_COLORS.hauler;
  return 'var(--text-secondary)';
}

function statusBadgeClass(status) {
  switch (status) {
    case 'IN_PROGRESS': return 'task-queue__badge task-queue__badge--in-progress';
    case 'ASSIGNED':    return 'task-queue__badge task-queue__badge--assigned';
    case 'AUCTIONING':  return 'task-queue__badge task-queue__badge--auctioning';
    case 'PENDING':     return 'task-queue__badge task-queue__badge--pending';
    case 'INTERRUPTED': return 'task-queue__badge task-queue__badge--interrupted';
    case 'COMPLETED':   return 'task-queue__badge task-queue__badge--completed';
    case 'FAILED':      return 'task-queue__badge task-queue__badge--failed';
    default:            return 'task-queue__badge task-queue__badge--pending';
  }
}

function statusLabel(status) {
  switch (status) {
    case 'IN_PROGRESS': return 'RUN';
    case 'ASSIGNED':    return 'ASN';
    case 'AUCTIONING':  return 'AUC';
    case 'PENDING':     return 'PEN';
    case 'INTERRUPTED': return 'INT';
    case 'COMPLETED':   return 'OK';
    case 'FAILED':      return 'ERR';
    default:            return '--';
  }
}

function truncate(str, max) {
  if (!str) return '';
  if (str.length <= max) return str;
  return str.slice(0, max - 1) + '…';
}

// Absolute time-of-day for a stamp taken on the PUBLISHER's clock.
//
// Deliberately not "12s ago": every stamp under state.taskEvents comes from the
// orchestrator's wall clock, and subtracting it from the browser's Date.now()
// would render clock skew between the two hosts as a bogus age. An absolute
// time is wrong by the same skew but does not pretend to be a measurement of
// elapsed time.
function clockTime(ms) {
  if (!ms) return '--:--:--';
  return new Date(ms).toLocaleTimeString();
}

// One task row's tooltip: everything that does not fit in six narrow columns.
function rowTitle(task) {
  const parts = [`${task.id} — ${task.type || 'unknown'}`];
  if (task.assigned_robot) parts.push(`on ${task.assigned_robot}`);
  else if (task.preferred_robot) parts.push(`prefers ${task.preferred_robot}`);
  if (task.status_reason) parts.push(`reason: ${task.status_reason}`);
  // FR-DASH-5: 0.0 means unconstrained (fill to the robot's RCDL capacity), so
  // it is shown as a word rather than as "0 kg", which reads like "no material".
  if (task.type === 'excavate' || task.type === 'haul') {
    parts.push(task.quantity_kg > 0
      ? `quantity ${task.quantity_kg} kg`
      : 'quantity: fill to capacity');
  }
  if (task.auction_rounds > 1) parts.push(`auction round ${task.auction_rounds}`);
  return parts.join(' — ');
}

function TaskRow({ task, selected, onClick }) {
  const isInProgress = task.status === 'IN_PROGRESS';
  const progressPct = Math.round((task.progress || 0) * 100);
  const robotColorVal = robotColor(task.assigned_robot);
  const rowClass =
    'task-queue__row' + (selected ? ' task-queue__row--selected' : '');

  return (
    <li
      className={rowClass}
      onClick={() => onClick(task.id)}
      title={rowTitle(task)}
    >
      <span className={statusBadgeClass(task.status)}>
        {statusLabel(task.status)}
      </span>
      <span className="task-queue__id-cell">
        <span className="task-queue__id">{truncate(task.id, 22)}</span>
        {/* D-03: the reason the status last changed. This is the line that
            separates a cancelled task from a finished one — both used to look
            identical here because the client inferred COMPLETED from the id
            disappearing off the robot. */}
        {task.status_reason ? (
          <span className="task-queue__reason">
            {truncate(task.status_reason, 26)}
          </span>
        ) : null}
      </span>
      <span className="task-queue__type" aria-label={task.type || ''}>
        {typeIcon(task.type)}
      </span>
      {task.assigned_robot ? (
        <span className="task-queue__robot">
          <span
            className="task-queue__robot-dot"
            style={{ background: robotColorVal }}
          />
          {truncate(task.assigned_robot, 10)}
        </span>
      ) : task.preferred_robot ? (
        /* D-04: an operator preference is NOT an assignment — the task is still
           auctioned and this robot only wins if it bids. Rendered distinctly so
           the two are not read as the same thing. */
        <span className="task-queue__robot task-queue__robot-preferred">
          {'≈ ' + truncate(task.preferred_robot, 8)}
        </span>
      ) : (
        <span className="task-queue__robot task-queue__robot-unassigned">
          &mdash;
        </span>
      )}
      <span className="task-queue__priority">
        {task.priority != null ? task.priority.toFixed(0) : '-'}
      </span>
      {isInProgress ? (
        <div className="task-queue__progress" aria-label={`${progressPct}%`}>
          <div
            className="task-queue__progress-fill"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      ) : (
        <span className="task-queue__progress-empty">&mdash;</span>
      )}
    </li>
  );
}

// D-05: one line of the task history. FR-DASH-6(d) (docs/PRD.md:543) requires
// override actions to be "logged and visible in the task history"; before this
// existed they went to a FleetAlert and to a five-entry list that was wiped
// whenever the operator selected a different robot.
function TaskEventRow({ event }) {
  const isOperator = event.kind === 'operator';
  // TaskEvent.accepted is documented as meaningful ONLY for kind == 'operator'
  // and always false for a status transition, so the outcome chip is rendered
  // for operator events only rather than labelling every status change
  // "rejected".
  const outcomeClass = 'task-queue__event-outcome task-queue__event-outcome--'
    + (event.accepted ? 'ok' : 'rejected');
  // An operator event may name a robot with no task ('force_recharge' on an
  // idle robot) — that case is exactly why TaskEvent exists separately from
  // TaskStatus, so fall back to the robot rather than showing a blank row.
  const subject = event.task_id || event.robot_id || '';
  const hasTarget = isOperator
    && (event.target_x !== 0 || event.target_y !== 0);

  return (
    <li className="task-queue__event" title={event.detail || event.action}>
      <span className="task-queue__event-time">{clockTime(event.stamp_ms)}</span>
      <span
        className={
          'task-queue__event-kind'
          + (isOperator ? ' task-queue__event-kind--operator' : '')
        }
      >
        {isOperator ? 'OPR' : 'STA'}
      </span>
      <span className="task-queue__event-action">
        {event.action || '--'}
        {/* The point the operator picked, for the two commands that carry one.
            Zero for everything else, so a (0,0) target is not rendered as a
            deliberate choice of the origin. */}
        {hasTarget && (
          <span className="task-queue__event-target">
            {` (${event.target_x.toFixed(1)}, ${event.target_y.toFixed(1)})`}
          </span>
        )}
      </span>
      <span
        className="task-queue__event-subject"
        style={{ color: robotColor(event.robot_id) }}
      >
        {truncate(subject, 20)}
      </span>
      {isOperator && (
        <span className={outcomeClass}>
          {event.accepted ? 'accepted' : 'rejected'}
        </span>
      )}
      {event.detail ? (
        <span className="task-queue__event-detail">
          {truncate(event.detail, 60)}
        </span>
      ) : null}
    </li>
  );
}

function TaskQueue({ state, dispatch }) {
  // Depend on the reducer's object directly. `state?.tasksById || {}` would mint
  // a fresh {} on every render whenever tasksById is absent, which makes the
  // useMemo below recompute every render; the `|| {}` fallback moves inside.
  const tasksById = state?.tasksById;
  const taskEvents = state?.taskEvents;
  const eventsDropped = state?.taskEventsDropped || 0;
  const queueReceived = !!state?.taskQueueReceived;
  const selectedTaskId = state?.selectedTaskId || null;

  const { activeTasks, finishedTasks } = useMemo(() => {
    const all = Object.values(tasksById || {});
    const active = [];
    const finished = [];
    for (const t of all) {
      const st = t.status || 'PENDING';
      if (FINISHED_STATUSES.has(st)) finished.push(t);
      else if (ACTIVE_STATUSES.has(st)) active.push(t);
      else active.push(t);
    }
    // D-03: ordering keys are now the orchestrator's own status_changed stamp
    // rather than the client's first-sighting time, so a browser opened
    // mid-mission orders the queue the same way one that has been up since
    // launch does.
    active.sort((a, b) => {
      const sa = STATUS_ORDER[a.status] ?? 99;
      const sb = STATUS_ORDER[b.status] ?? 99;
      if (sa !== sb) return sa - sb;
      // Within same status: higher priority first, then most recently changed
      const pa = a.priority || 0;
      const pb = b.priority || 0;
      if (pa !== pb) return pb - pa;
      return (b.status_changed_ms || 0) - (a.status_changed_ms || 0);
    });
    finished.sort((a, b) => (b.status_changed_ms || 0) - (a.status_changed_ms || 0));
    return { activeTasks: active, finishedTasks: finished };
  }, [tasksById]);

  // Newest first for display; state.taskEvents is stored ascending by seq.
  const eventRows = useMemo(() => {
    const all = taskEvents || [];
    return all.slice(-MAX_EVENT_ROWS).reverse();
  }, [taskEvents]);

  const handleSelect = useCallback(
    (taskId) => {
      if (!dispatch) return;
      dispatch({
        type: 'SELECT_TASK',
        payload: { taskId: selectedTaskId === taskId ? null : taskId },
      });
    },
    [dispatch, selectedTaskId]
  );

  const totalActive = activeTasks.length;
  const totalFinished = finishedTasks.length;

  return (
    <div className="task-queue">
      <div className="task-queue__header">
        <span className="task-queue__title">Task Queue</span>
        <span className="task-queue__count">
          {totalActive} active
          {totalFinished > 0 ? ` / ${totalFinished} done` : ''}
        </span>
      </div>

      {totalActive === 0 && totalFinished === 0 ? (
        <div className="task-queue__empty">
          {/* D-03: distinguishes "the orchestrator says the queue is empty"
              from "no snapshot has arrived", which used to look identical —
              the panel showed "No tasks yet" whether the backend was idle or
              absent. */}
          {queueReceived ? 'No tasks yet' : 'Awaiting /orchestrator/task_queue'}
        </div>
      ) : (
        <>
          <div className="task-queue__col-header">
            <span>Stat</span>
            <span>ID</span>
            <span>T</span>
            <span>Robot</span>
            <span>Pri</span>
            <span>Prog</span>
          </div>

          {totalActive === 0 ? (
            <div className="task-queue__empty">No active tasks</div>
          ) : (
            <ul className="task-queue__list">
              {activeTasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  selected={task.id === selectedTaskId}
                  onClick={handleSelect}
                />
              ))}
            </ul>
          )}

          {totalFinished > 0 && (
            <details className="task-queue__finished">
              <summary className="task-queue__finished-summary">
                {totalFinished} finished task{totalFinished === 1 ? '' : 's'}
              </summary>
              <ul className="task-queue__finished-list">
                {finishedTasks.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    selected={task.id === selectedTaskId}
                    onClick={handleSelect}
                  />
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      {/* D-05: task history — status transitions and operator commands
          interleaved, including REJECTED commands, which are often the more
          interesting record ("robot in ERROR, override rejected"). */}
      {eventRows.length > 0 && (
        <details className="task-queue__history">
          <summary className="task-queue__history-summary">
            Task history ({eventRows.length}
            {eventsDropped > 0 ? ` shown, ${eventsDropped} evicted` : ''})
          </summary>
          {eventsDropped > 0 && (
            <div className="task-queue__history-truncated">
              {eventsDropped} earlier event{eventsDropped === 1 ? '' : 's'} were
              evicted from the orchestrator&apos;s ring before this browser saw
              them &mdash; this list is not the complete history.
            </div>
          )}
          <ul className="task-queue__history-list">
            {eventRows.map((event) => (
              <TaskEventRow key={event.seq} event={event} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default TaskQueue;
