import { useReducer } from 'react';

const MAX_HISTORY = 20;
const MAX_ALERTS = 50;
const MAX_READINGS = 500;

const initialState = {
  robots: {},
  resourceReadings: [],
  alerts: [],
  missionProgress: null,
  taskAuctions: [],  // recent auction activity
  tasksById: {},     // task_id -> unified task lifecycle record
  selectedRobotId: null,
  selectedTaskId: null,
  heatmapVisible: true,
  // Wave2-A4: Picker mode for map-click target picking
  pickerMode: null,        // null | 'inject_task' | 'send_to_location'
  pickerContext: null,     // optional metadata, e.g. {robotId: 'scout_01'}
  pickerResult: null,      // {x, y} after click
  // Wave2-A4: Per-robot planned path (list of {x,y} world coords)
  robotPaths: {},          // robotId -> [{x,y}, ...]
};

// --- Task lifecycle helpers ---

// Pull a scalar (x/y) out of whatever shape the ROS message arrives in.
// TaskAnnouncement uses `target_location: {x,y,z}`, but other senders may
// flatten to target_x / target_y, so tolerate both.
function extractTargetXY(payload) {
  if (!payload) return { x: 0, y: 0 };
  if (payload.target_location) {
    return {
      x: payload.target_location.x || 0,
      y: payload.target_location.y || 0,
    };
  }
  return {
    x: payload.target_x || 0,
    y: payload.target_y || 0,
  };
}

function upsertTask(tasksById, taskId, patch) {
  const existing = tasksById[taskId] || {};
  return {
    ...tasksById,
    [taskId]: { ...existing, ...patch, id: taskId },
  };
}

function fleetReducer(state, action) {
  switch (action.type) {
    case 'UPDATE_ROBOT': {
      const msg = action.payload;
      const id = msg.robot_id;
      const prev = state.robots[id];
      const stateHistory = prev?.stateHistory || [];

      // Track FSM transitions
      if (prev && prev.fsm_state !== msg.fsm_state) {
        stateHistory.unshift({
          from: prev.fsm_state,
          to: msg.fsm_state,
          timestamp: Date.now(),
        });
        if (stateHistory.length > MAX_HISTORY) stateHistory.pop();
      }

      // --- Task lifecycle inference from current_task_id ---
      let tasksById = state.tasksById;
      const prevTaskId = prev?.current_task_id || '';
      const nextTaskId = msg.current_task_id || '';
      const nextProgress = msg.task_progress;

      // Robot just picked up a (non-override) task: mark it IN_PROGRESS
      if (nextTaskId && nextTaskId !== prevTaskId && !nextTaskId.startsWith('override_')) {
        tasksById = upsertTask(tasksById, nextTaskId, {
          status: 'IN_PROGRESS',
          assigned_robot: msg.robot_id,
          started_at: Date.now(),
          progress: nextProgress || 0,
        });
      }

      // Progress update on the active task
      if (nextTaskId && nextTaskId === prevTaskId && !nextTaskId.startsWith('override_')) {
        const entry = tasksById[nextTaskId];
        if (entry && entry.progress !== nextProgress) {
          tasksById = upsertTask(tasksById, nextTaskId, {
            progress: nextProgress || 0,
          });
        }
      }

      // Robot dropped its task: mark the previous one COMPLETED
      if (prevTaskId && prevTaskId !== nextTaskId && !prevTaskId.startsWith('override_')) {
        const entry = tasksById[prevTaskId];
        if (entry && entry.status === 'IN_PROGRESS') {
          tasksById = upsertTask(tasksById, prevTaskId, {
            status: 'COMPLETED',
            progress: 1.0,
            completed_at: Date.now(),
          });
        }
      }

      return {
        ...state,
        tasksById,
        robots: {
          ...state.robots,
          [id]: {
            robot_id: msg.robot_id,
            robot_type: msg.robot_type,
            fsm_state: msg.fsm_state,
            pose: msg.pose || { x: 0, y: 0, theta: 0 },
            velocity: msg.velocity || { linear: { x: 0 }, angular: { z: 0 } },
            battery_level: msg.battery_level,
            current_task_id: msg.current_task_id,
            task_progress: msg.task_progress,
            capabilities: msg.capabilities || [],
            lastUpdate: Date.now(),
            stateHistory,
          },
        },
      };
    }

    case 'ADD_RESOURCE_READING': {
      const readings = [action.payload, ...state.resourceReadings];
      if (readings.length > MAX_READINGS) readings.pop();
      return { ...state, resourceReadings: readings };
    }

    case 'ADD_ALERT': {
      const alerts = [{ ...action.payload, timestamp: Date.now() }, ...state.alerts];
      if (alerts.length > MAX_ALERTS) alerts.pop();
      return { ...state, alerts };
    }

    case 'ADD_TASK_ANNOUNCEMENT': {
      const msg = action.payload;
      const auctions = [
        { ...msg, eventType: 'announcement', timestamp: Date.now() },
        ...state.taskAuctions,
      ].slice(0, 50);

      // --- Unified lifecycle: upsert PENDING ---
      let tasksById = state.tasksById;
      if (msg && msg.task_id) {
        const { x, y } = extractTargetXY(msg);
        const existing = tasksById[msg.task_id];
        tasksById = upsertTask(tasksById, msg.task_id, {
          type: msg.task_type || existing?.type || '',
          target_x: x,
          target_y: y,
          priority: msg.priority != null ? msg.priority : (existing?.priority || 0),
          required_capabilities: msg.required_capabilities || existing?.required_capabilities || [],
          // Only downgrade to PENDING if we don't already have a more advanced status
          status: existing?.status && existing.status !== 'PENDING' ? existing.status : 'PENDING',
          announced_at: existing?.announced_at || Date.now(),
        });
      }
      return { ...state, taskAuctions: auctions, tasksById };
    }

    case 'ADD_TASK_ASSIGNMENT': {
      const msg = action.payload;
      const auctions = [
        { ...msg, eventType: 'assignment', timestamp: Date.now() },
        ...state.taskAuctions,
      ].slice(0, 50);

      // --- Unified lifecycle: upsert ASSIGNED ---
      let tasksById = state.tasksById;
      if (msg && msg.task_id) {
        const { x, y } = extractTargetXY(msg);
        const existing = tasksById[msg.task_id];
        tasksById = upsertTask(tasksById, msg.task_id, {
          type: msg.task_type || existing?.type || '',
          target_x: existing?.target_x != null ? existing.target_x : x,
          target_y: existing?.target_y != null ? existing.target_y : y,
          assigned_robot: msg.robot_id || existing?.assigned_robot || '',
          // Don't downgrade IN_PROGRESS / COMPLETED
          status: existing?.status === 'IN_PROGRESS' || existing?.status === 'COMPLETED'
            ? existing.status
            : 'ASSIGNED',
          assigned_at: Date.now(),
        });
      }
      return { ...state, taskAuctions: auctions, tasksById };
    }

    case 'SELECT_TASK':
      return { ...state, selectedTaskId: action.payload?.taskId ?? null };

    case 'UPDATE_MISSION':
      return { ...state, missionProgress: action.payload };

    case 'SET_SELECTED_ROBOT':
      return { ...state, selectedRobotId: action.payload };

    case 'TOGGLE_HEATMAP':
      return { ...state, heatmapVisible: !state.heatmapVisible };

    // Wave2-A4: Picker mode reducer cases
    case 'SET_PICKER_MODE': {
      const payload = action.payload || {};
      return {
        ...state,
        pickerMode: payload.mode || null,
        pickerContext: payload,
        pickerResult: null,
      };
    }

    // Wave2-A4: record the world-coord result of a map click in picker mode
    case 'SET_PICKER_RESULT':
      return { ...state, pickerResult: action.payload };

    // Wave2-A4: clear picker mode entirely (e.g. after consumer handles result)
    case 'CLEAR_PICKER_MODE':
      return {
        ...state,
        pickerMode: null,
        pickerContext: null,
        pickerResult: null,
      };

    // Wave2-A4: planned path updates from per-robot nav_msgs/Path subscriptions
    case 'UPDATE_ROBOT_PATH': {
      const payload = action.payload || {};
      const robotId = payload.robotId;
      const path = payload.path || [];
      if (!robotId) return state;
      return {
        ...state,
        robotPaths: {
          ...state.robotPaths,
          [robotId]: path,
        },
      };
    }

    default:
      return state;
  }
}

export default function useFleetState() {
  return useReducer(fleetReducer, initialState);
}
