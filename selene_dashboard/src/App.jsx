import React, { useState, useEffect, useCallback } from 'react';
import ROSLIB from 'roslib';
import './App.css';

import useRosBridge from './hooks/useRosBridge';
import useFleetState from './hooks/useFleetState';
import { ROBOT_IDS, TOPICS, MSG_TYPES } from './utils/rosTopics';

import Header from './components/Header';
import FleetMap from './components/FleetMap';
import ResourceGraph from './components/ResourceGraph';
import RobotDetail from './components/RobotDetail';
import MissionProgress from './components/MissionProgress';
import FleetCards from './components/FleetCards';
import AlertLog from './components/AlertLog';

function App() {
  const { ros, connected } = useRosBridge();
  const [state, dispatch] = useFleetState();

  const [showResourceGraph, setShowResourceGraph] = useState(false);

  const selectRobot = useCallback((id) => {
    dispatch({ type: 'SET_SELECTED_ROBOT', payload: id });
  }, [dispatch]);

  const toggleHeatmap = useCallback(() => {
    dispatch({ type: 'TOGGLE_HEATMAP' });
  }, [dispatch]);

  const toggleResourceGraph = useCallback(() => {
    setShowResourceGraph((prev) => !prev);
  }, []);

  // Subscribe to ROS topics when connected
  useEffect(() => {
    if (!ros || !connected) return;
    const listeners = [];

    // Per-robot state subscriptions
    ROBOT_IDS.forEach((id) => {
      const stateTopic = new ROSLIB.Topic({
        ros,
        name: TOPICS.ROBOT_STATE(id),
        messageType: MSG_TYPES.ROBOT_STATE,
        throttle_rate: 500,
      });
      stateTopic.subscribe((msg) => {
        dispatch({ type: 'UPDATE_ROBOT', payload: msg });
      });
      listeners.push(stateTopic);
    });

    // Resource map updates
    const mapTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.MAP_UPDATE,
      messageType: MSG_TYPES.RESOURCE_MAP_UPDATE,
    });
    mapTopic.subscribe((msg) => {
      dispatch({
        type: 'ADD_RESOURCE_READING',
        payload: {
          scout_id: msg.scout_id,
          location: { x: msg.location.x, y: msg.location.y },
          ice_concentration: msg.ice_concentration,
          sensor_uncertainty: msg.sensor_uncertainty,
        },
      });
    });
    listeners.push(mapTopic);

    // Fleet alerts
    const alertTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.FLEET_ALERT,
      messageType: MSG_TYPES.FLEET_ALERT,
    });
    alertTopic.subscribe((msg) => {
      dispatch({ type: 'ADD_ALERT', payload: msg });
    });
    listeners.push(alertTopic);

    // Mission progress
    const missionTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.MISSION_PROGRESS,
      messageType: MSG_TYPES.MISSION_PROGRESS,
    });
    missionTopic.subscribe((msg) => {
      dispatch({ type: 'UPDATE_MISSION', payload: msg });
    });
    listeners.push(missionTopic);

    // Task announcements
    const announceTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.TASK_ANNOUNCEMENT,
      messageType: MSG_TYPES.TASK_ANNOUNCEMENT,
    });
    announceTopic.subscribe((msg) => {
      dispatch({ type: 'ADD_TASK_ANNOUNCEMENT', payload: msg });
    });
    listeners.push(announceTopic);

    // Task assignments
    const assignTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.TASK_ASSIGNMENT,
      messageType: MSG_TYPES.TASK_ASSIGNMENT,
    });
    assignTopic.subscribe((msg) => {
      dispatch({ type: 'ADD_TASK_ASSIGNMENT', payload: msg });
    });
    listeners.push(assignTopic);

    return () => {
      listeners.forEach((l) => l.unsubscribe());
    };
  }, [ros, connected, dispatch]);

  const selectedRobot = state.selectedRobotId ? state.robots[state.selectedRobotId] : null;

  return (
    <div className="app">
      <Header
        connected={connected}
        simTime={state.missionProgress?.elapsed_sim_time}
        showResourceGraph={showResourceGraph}
        onToggleResourceGraph={toggleResourceGraph}
      />

      <div className="app__map">
        {showResourceGraph ? (
          <ResourceGraph
            readings={state.resourceReadings}
            onClose={() => setShowResourceGraph(false)}
          />
        ) : (
          <FleetMap
            robots={state.robots}
            resourceReadings={state.resourceReadings}
            selectedRobotId={state.selectedRobotId}
            onSelectRobot={selectRobot}
            heatmapVisible={state.heatmapVisible}
            onToggleHeatmap={toggleHeatmap}
          />
        )}
      </div>

      <div className="app__sidebar">
        <RobotDetail robot={selectedRobot} />
        <MissionProgress
          progress={state.missionProgress}
          robots={state.robots}
          readings={state.resourceReadings}
        />
      </div>

      <div className="app__footer">
        <FleetCards
          robots={state.robots}
          selectedRobotId={state.selectedRobotId}
          onSelectRobot={selectRobot}
        />
        <AlertLog alerts={state.alerts} />
      </div>
    </div>
  );
}

export default App;
