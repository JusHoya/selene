import { useReducer } from 'react';

const MAX_HISTORY = 20;
const MAX_ALERTS = 50;
const MAX_READINGS = 500;

const initialState = {
  robots: {},
  resourceReadings: [],
  alerts: [],
  missionProgress: null,
  selectedRobotId: null,
  heatmapVisible: true,
};

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

      return {
        ...state,
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

    case 'UPDATE_MISSION':
      return { ...state, missionProgress: action.payload };

    case 'SET_SELECTED_ROBOT':
      return { ...state, selectedRobotId: action.payload };

    case 'TOGGLE_HEATMAP':
      return { ...state, heatmapVisible: !state.heatmapVisible };

    default:
      return state;
  }
}

export default function useFleetState() {
  return useReducer(fleetReducer, initialState);
}
