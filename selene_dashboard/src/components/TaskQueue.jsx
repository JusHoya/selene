import React, { useMemo, useCallback } from 'react';
import { TYPE_COLORS } from '../utils/colors';
import './TaskQueue.css';

// Status priority order (lower = shown first in the active list)
const STATUS_ORDER = {
  IN_PROGRESS: 0,
  ASSIGNED: 1,
  PENDING: 2,
  INTERRUPTED: 3,
  COMPLETED: 4,
  FAILED: 5,
};

const ACTIVE_STATUSES = new Set(['IN_PROGRESS', 'ASSIGNED', 'PENDING', 'INTERRUPTED']);
const FINISHED_STATUSES = new Set(['COMPLETED', 'FAILED']);

// Unicode glyphs for task types
const TYPE_ICONS = {
  prospect: '\u25C9',   // ◉  fisheye — survey
  survey: '\u25C9',
  excavate: '\u26CF',   // ⛏  pick
  haul: '\u26DF',        // ⛟  truck-ish
};

function typeIcon(type) {
  if (!type) return '\u25A1'; // ▢
  const key = String(type).toLowerCase();
  return TYPE_ICONS[key] || '\u25A1';
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
  return str.slice(0, max - 1) + '\u2026';
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
      title={`${task.id} \u2014 ${task.type || 'unknown'}${
        task.assigned_robot ? ' \u2014 ' + task.assigned_robot : ''
      }`}
    >
      <span className={statusBadgeClass(task.status)}>
        {statusLabel(task.status)}
      </span>
      <span className="task-queue__id">{truncate(task.id, 22)}</span>
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

function TaskQueue({ state, dispatch }) {
  const tasksById = state?.tasksById || {};
  const selectedTaskId = state?.selectedTaskId || null;

  const { activeTasks, finishedTasks } = useMemo(() => {
    const all = Object.values(tasksById);
    const active = [];
    const finished = [];
    for (const t of all) {
      const st = t.status || 'PENDING';
      if (FINISHED_STATUSES.has(st)) finished.push(t);
      else if (ACTIVE_STATUSES.has(st)) active.push(t);
      else active.push(t);
    }
    active.sort((a, b) => {
      const sa = STATUS_ORDER[a.status] ?? 99;
      const sb = STATUS_ORDER[b.status] ?? 99;
      if (sa !== sb) return sa - sb;
      // Within same status: higher priority first, then newer first
      const pa = a.priority || 0;
      const pb = b.priority || 0;
      if (pa !== pb) return pb - pa;
      return (b.announced_at || 0) - (a.announced_at || 0);
    });
    finished.sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0));
    return { activeTasks: active, finishedTasks: finished };
  }, [tasksById]);

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
        <div className="task-queue__empty">No tasks yet</div>
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
    </div>
  );
}

export default TaskQueue;
