import React, { useState, useEffect, useRef, useCallback } from 'react';
import ROSLIB from 'roslib';
import './App.css';

import useRosBridge from './hooks/useRosBridge';
import useFleetState from './hooks/useFleetState';
// Wave2-A4: ROSLIB service client wrapper hook
import useRosService from './hooks/useRosService';
// A15: dynamic fleet discovery (replaces the hardcoded ROBOT_IDS list)
import useFleetDiscovery from './hooks/useFleetDiscovery';
import { TOPICS, MSG_TYPES } from './utils/rosTopics';

import Header from './components/Header';
import FleetMap from './components/FleetMap';
import ResourceGraph from './components/ResourceGraph';
import RobotDetail from './components/RobotDetail';
import MissionProgress from './components/MissionProgress';
import FleetCards from './components/FleetCards';
import AlertLog from './components/AlertLog';
import TaskQueue from './components/TaskQueue';
// Wave2-A4: Task injection panel (FR-DASH-5)
import TaskInjector from './components/TaskInjector';

function App() {
  const { ros, connected } = useRosBridge();
  const [state, dispatch] = useFleetState();
  // Wave2-A4: Service caller wrapper used by TaskInjector + RobotDetail.
  // A8: null while disconnected, so callers can tell "unavailable" from "failed".
  const callService = useRosService(ros, connected);
  // A15: robot ids discovered from rosapi, or the labelled fallback list
  const { robotIds } = useFleetDiscovery(ros, connected);
  // Stable primitive key so the per-robot subscribe effect only re-runs when the
  // *contents* of the fleet change, not on every discovery poll.
  const robotIdsKey = robotIds.join(',');

  const [showResourceGraph, setShowResourceGraph] = useState(false);

  // Dev: expose dispatch for interactive testing
  useEffect(() => {
    if (process.env.NODE_ENV === 'development') {
      window.__seleneDispatch = dispatch;
    }
  }, [dispatch]);

  const selectRobot = useCallback((id) => {
    dispatch({ type: 'SET_SELECTED_ROBOT', payload: id });
  }, [dispatch]);

  const toggleHeatmap = useCallback(() => {
    dispatch({ type: 'TOGGLE_HEATMAP' });
  }, [dispatch]);

  const toggleResourceGraph = useCallback(() => {
    setShowResourceGraph((prev) => !prev);
  }, []);

  // Wave2-A4: Picker-result callback — FleetMap invokes this on a picker click
  const handlePickerResult = useCallback((point) => {
    dispatch({ type: 'SET_PICKER_RESULT', payload: point });
  }, [dispatch]);

  // A-reconnect: clear the previous backend session's state when the bridge
  // comes back. Declared before the subscribe effects so the clear lands before
  // any new message can be dispatched.
  //
  // The ref starts false, so the FIRST successful connect does NOT reset — only
  // a true reconnect (connected true -> false -> true) does. Because the effect
  // depends only on `connected`, dispatching RESET here cannot re-trigger it.
  const hasConnectedBeforeRef = useRef(false);
  useEffect(() => {
    if (!connected) return;
    if (hasConnectedBeforeRef.current) {
      dispatch({ type: 'RESET' });
    }
    hasConnectedBeforeRef.current = true;
  }, [connected, dispatch]);

  // A15: Per-robot subscriptions for the *discovered* fleet.
  //
  // Keyed on robotIdsKey: whenever the fleet set changes, every per-robot topic
  // is unsubscribed and rebuilt from the new list. That is deliberately a full
  // teardown rather than an incremental diff — it makes duplicate or leaked
  // ROSLIB.Topic subscriptions structurally impossible. The discovery set
  // converges within a few polls and is stable after that, so the churn is
  // bounded to fleet-composition changes.
  useEffect(() => {
    if (!ros || !connected) return undefined;
    const ids = robotIdsKey ? robotIdsKey.split(',') : [];
    const listeners = [];

    ids.forEach((id) => {
      // RobotState.
      //
      // D-34: NO throttle_rate, and the removal of `throttle_rate: 500` is the
      // point rather than a tidy-up.
      //
      // WHAT IT WAS DOING. `throttle_rate` is a rosbridge SERVER-SIDE minimum
      // interval, applied per subscription before anything reaches this browser,
      // and `queue_length` was unset — which in the rosbridge protocol means
      // DROP, not delay. With the agent publishing RobotState only from its
      // 0.5 s timer the two rates coincided and the throttle was invisible. It
      // stopped being invisible when the agent started publishing on FSM
      // TRANSITION as well (D-34 Part A): a transition sample is an EDGE, it
      // carries information no later sample can reproduce, and a 500 ms drop
      // window re-aliases the topic at exactly 2 Hz no matter what the publisher
      // does. The register's measured case is an IDLE window held for 0.247 s
      // between a cancel and the next auction — shorter than the throttle, so
      // the hand-off would never appear in RobotDetail's state history however
      // often the agent published it.
      //
      // WHY ZERO RATHER THAN A SMALLER NUMBER, from the traffic rather than from
      // taste. Any non-zero throttle is a drop window, so the only question is
      // whether the resulting volume is affordable — and it plainly is.
      // RobotState is a small fixed-shape message (four short strings, a Pose2D,
      // a Twist, three float32s, a Time, a bool and a short capabilities list —
      // a few hundred bytes of JSON over the bridge). The publisher is already
      // the rate limiter at 2 Hz per robot, which is 20 Hz for the shipped
      // ten-robot fleet, and D-34 bounds the transition traffic it adds at under
      // 3% of that. Compare what this dashboard ALREADY accepts unthrottled on
      // the same socket: /orchestrator/task_queue at 2 Hz, each message a
      // complete task table plus a 32-entry event ring, and
      // /orchestrator/resource_map at 0.5 Hz carrying up to 20k cells across
      // four parallel arrays. Unthrottled RobotState is far cheaper than either.
      //
      // The reducer already de-duplicates the level signal: `stateHistory` is
      // appended only when `prev.fsm_state !== msg.fsm_state`
      // (hooks/useFleetState.js), so the extra samples cannot double-count.
      //
      // NOT A MEASUREMENT. The drop-vs-delay semantics above is read from the
      // rosbridge protocol contract, not executed here. If throttle_rate turned
      // out to queue rather than drop, removing it would be a latency
      // improvement rather than a correctness fix — either way this direction is
      // safe. The live re-run has to confirm the IDLE hand-off actually appears
      // in RobotDetail's state history.
      const stateTopic = new ROSLIB.Topic({
        ros,
        name: TOPICS.ROBOT_STATE(id),
        messageType: MSG_TYPES.ROBOT_STATE,
      });
      stateTopic.subscribe((msg) => {
        dispatch({ type: 'UPDATE_ROBOT', payload: msg });
      });
      listeners.push(stateTopic);

      // Wave2-A4: planned_path (nav_msgs/Path) — extract world x/y per pose
      const pathTopic = new ROSLIB.Topic({
        ros,
        name: TOPICS.PLANNED_PATH(id),
        messageType: MSG_TYPES.PATH,
        throttle_rate: 500,
      });
      pathTopic.subscribe((msg) => {
        const poses = Array.isArray(msg?.poses) ? msg.poses : [];
        const points = poses
          .map((p) => {
            const pos = p?.pose?.position;
            if (!pos || typeof pos.x !== 'number' || typeof pos.y !== 'number') {
              return null;
            }
            return { x: pos.x, y: pos.y };
          })
          .filter(Boolean);
        dispatch({
          type: 'UPDATE_ROBOT_PATH',
          payload: { robotId: id, path: points },
        });
      });
      listeners.push(pathTopic);
    });

    return () => {
      listeners.forEach((l) => l.unsubscribe());
    };
  }, [ros, connected, dispatch, robotIdsKey]);

  // Fleet-wide (non per-robot) subscriptions. Kept in their own effect so a
  // change in fleet composition does not tear these down.
  useEffect(() => {
    if (!ros || !connected) return undefined;
    const listeners = [];

    // Resource map updates
    const mapTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.MAP_UPDATE,
      messageType: MSG_TYPES.RESOURCE_MAP_UPDATE,
    });
    // The RAW message goes to the reducer, which projects and validates it.
    //
    // This callback used to build the projection itself, and in doing so
    // dereferenced `msg.location.x` with no guard: a ResourceMapUpdate with a
    // missing location threw inside the roslib websocket handler rather than
    // being rejected and counted. It also validated nothing at all, so a single
    // non-finite ice_concentration made the graph's Peak/Avg panel read
    // "NaN wt%" for the rest of the session. Projecting in the reducer puts this
    // topic under the same contract UPDATE_RESOURCE_MAP has had since D-02, and
    // makes the rejection testable without a browser.
    mapTopic.subscribe((msg) => {
      dispatch({ type: 'ADD_RESOURCE_READING', payload: msg });
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

    // D-03: the authoritative task table + operator/status event ring.
    //
    // NO throttle_rate, deliberately. The publisher is already the rate limiter
    // (task_queue_publish_rate, 2 Hz) and every message is a COMPLETE snapshot,
    // so throttling here could only delay a message that is self-sufficient on
    // arrival — it cannot reduce the work needed to stay correct.
    //
    // This topic REPLACES the /orchestrator/task_announcement and
    // /orchestrator/task_assignment subscriptions that used to be here. They
    // existed only to feed the client-side lifecycle inference the reducer no
    // longer performs, so keeping them would make rosbridge serialise two
    // event-driven topics into dispatches that hit the reducer's default case.
    // Both topics are still published; nothing in the dashboard reads them.
    const taskQueueTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.TASK_QUEUE,
      messageType: MSG_TYPES.TASK_QUEUE,
    });
    taskQueueTopic.subscribe((msg) => {
      dispatch({ type: 'UPDATE_TASK_QUEUE', payload: msg });
    });
    listeners.push(taskQueueTopic);

    // D-02: the orchestrator's fused posterior grid. Also a complete snapshot,
    // also unthrottled, for the same reason — and here throttling would be
    // actively harmful, since dropping one 0.5 Hz snapshot means up to two
    // seconds of a visibly stale heatmap.
    const resourceMapTopic = new ROSLIB.Topic({
      ros,
      name: TOPICS.RESOURCE_MAP,
      messageType: MSG_TYPES.RESOURCE_MAP,
    });
    resourceMapTopic.subscribe((msg) => {
      dispatch({ type: 'UPDATE_RESOURCE_MAP', payload: msg });
    });
    listeners.push(resourceMapTopic);

    return () => {
      listeners.forEach((l) => l.unsubscribe());
    };
  }, [ros, connected, dispatch]);

  const selectedRobot = state.selectedRobotId ? state.robots[state.selectedRobotId] : null;

  return (
    <div className="app">
      <Header
        connected={connected}
        /* D-06: renamed from simTime — this is orchestrator wall clock, not
           simulation time. See the comment in Header.jsx. */
        elapsedSec={state.missionProgress?.elapsed_sim_time}
        showResourceGraph={showResourceGraph}
        onToggleResourceGraph={toggleResourceGraph}
      />

      <div className="app__map">
        {showResourceGraph ? (
          <ResourceGraph
            readings={state.resourceReadings}
            /* Readings the reducer refused. Surfaced so "nothing published yet"
               and "everything published is malformed" are distinguishable on
               screen — they look identical otherwise, and the second is the one
               that needs someone to go and look. */
            droppedReadings={state.resourceReadingsDropped}
            onClose={() => setShowResourceGraph(false)}
          />
        ) : (
          <FleetMap
            robots={state.robots}
            /* `resourceReadings` is deliberately NOT passed any more. FleetMap
               stopped consuming it when the heatmap moved from splatting raw
               per-reading ResourceMapUpdate blobs to rasterising the fused
               posterior below (D-02), and a prop that is passed but never
               destructured reads, wrongly, as though the map still builds from
               raw readings. ResourceGraph still receives it above, and what it
               shows is the per-sample picture the posterior cannot: the
               individual readings, their spatial proximity to each other and
               their agreement. THIS IS NOT A TIME SERIES and this comment used
               to claim it was. Nothing in the dashboard reads
               ResourceMapUpdate.stamp — the reducer does not project it and no
               consumer asks for it — so no view here can order samples in time
               at all. Restoring that would mean carrying the stamp through the
               reducer AND giving it a reader, not re-asserting the claim. */
            /* D-02: the fused posterior the heatmap now rasterises, already
               validated and converted to typed arrays by the reducer, plus the
               status the legend needs to distinguish "not connected" from
               "connected, nothing published yet" from "snapshots rejected". */
            resourceMap={state.resourceMap}
            resourceMapStatus={{
              connected,
              received: !!state.resourceMap,
              dropped: state.resourceMapDropped,
            }}
            selectedRobotId={state.selectedRobotId}
            onSelectRobot={selectRobot}
            heatmapVisible={state.heatmapVisible}
            onToggleHeatmap={toggleHeatmap}
            /* Wave2-A3: selected-task highlight inputs */
            selectedTaskId={state.selectedTaskId}
            tasksById={state.tasksById}
            /* Wave2-A4: picker mode + planned path inputs */
            pickerMode={state.pickerMode}
            pickerContext={state.pickerContext}
            robotPaths={state.robotPaths}
            onPickerResult={handlePickerResult}
          />
        )}
      </div>

      <div className="app__sidebar">
        {/* Wave2-A4: pass state/dispatch/callService for override buttons + time-to-empty */}
        {/* A8: key by robot_id so per-robot local state (battery rolling
            window, pending confirmation, and the optimistic in-flight override
            row) does not bleed across robot selections.
            D-05: the override HISTORY is deliberately no longer in that list —
            it moved into the reducer (state.taskEvents) precisely because this
            key was destroying it on every robot selection. The key stays; what
            it destroys no longer includes anything the operator needs. */}
        <RobotDetail
          key={selectedRobot?.robot_id || 'no-robot'}
          robot={selectedRobot}
          state={state}
          dispatch={dispatch}
          callService={callService}
        />
        {/* A4: `readings` removed — MissionProgress never accepted it. */}
        <MissionProgress
          progress={state.missionProgress}
          robots={state.robots}
        />
        {/* Wave2-A3: TaskQueue panel */}
        <TaskQueue state={state} dispatch={dispatch} />
        {/* Wave2-A4: TaskInjector panel */}
        <TaskInjector
          state={state}
          dispatch={dispatch}
          callService={callService}
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
