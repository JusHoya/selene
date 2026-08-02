import { useReducer } from 'react';
// D-31: the wire rule for RobotState.pose_valid, defined once beside the
// readers that consume it. See utils/poseFix.js for why an ABSENT key and an
// explicit `false` are decoded differently here when ROS 2 cannot tell them
// apart at all.
import { decodePoseValidity } from '../utils/poseFix';

const MAX_HISTORY = 20;
const MAX_ALERTS = 50;
const MAX_READINGS = 500;

// D-03/D-05: how many TaskEvents the client keeps. The orchestrator replays its
// whole ring (task_queue_event_history, default 32) in every snapshot, so this
// window is what lets the operator scroll back past the ring — six ring-fulls.
// Events beyond it are dropped by the CLIENT and are not counted in
// taskEventsDropped, which is the orchestrator's own eviction counter.
const MAX_TASK_EVENTS = 200;

export const initialState = {
  robots: {},
  resourceReadings: [],
  // Monotonic identity key minted per ACCEPTED reading. Same role, and the same
  // hard-won reason, as resourceMapRevision below: ResourceGraph used to
  // identify a reading by its POSITION in this array, and this array prepends,
  // so every arrival silently moved the operator's selection, the hover ring and
  // every node's association with its own sample onto a different reading. See
  // the note on `case 'RESET'` for why this one is carried across a reconnect.
  resourceReadingSeq: 0,
  // Readings rejected by the projector below. Counted rather than logged so the
  // view can SAY the feed is being rejected: a reading that fails validation and
  // is silently dropped is indistinguishable on screen from a scout that never
  // published, and "No resource data yet" is the wrong story to tell in that
  // case. ResourceGraph reads this in both its empty state and its stats panel.
  resourceReadingsDropped: 0,
  alerts: [],
  missionProgress: null,
  tasksById: {},           // task_id -> projection of one TaskQueueState.tasks row
  taskEvents: [],          // TaskEvent projections, ASCENDING by seq
  taskEventsDropped: 0,    // TaskQueueState.events_dropped (orchestrator-side)
  // False until the first TaskQueueState arrives. An empty tasksById cannot
  // carry this on its own — "the orchestrator says the queue is empty" and "no
  // snapshot has reached this browser" are different facts and the panel has to
  // be able to say which one it is showing.
  taskQueueReceived: false,
  // D-02: fused posterior grid from /orchestrator/resource_map. null until the
  // first snapshot is accepted — FleetMap draws nothing rather than substituting
  // anything, so "no posterior" is visible instead of invisible.
  resourceMap: null,
  resourceMapDropped: 0,   // snapshots rejected for parallel-array length mismatch
  // D-15: the raster cache key, and the reason it lives OUT here rather than
  // being derived from `resourceMap` itself. It counts accepted snapshots for
  // the lifetime of the BROWSER TAB, across any number of backend sessions, and
  // `case 'RESET'` deliberately carries it forward. See the comment on the
  // counter's use in UPDATE_RESOURCE_MAP for what went wrong when it did not.
  resourceMapRevision: 0,
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

// --- Wire-decoding helpers ---

// builtin_interfaces/Time -> milliseconds since the epoch, or 0 when absent.
//
// THE CLOCK THIS RETURNS IS THE PUBLISHER'S, NOT THE BROWSER'S. Every stamp on
// TaskQueueState (TaskStatus.status_changed, TaskEvent.stamp) is orchestrator
// wall clock; use_sim_time is unset repo-wide. It is therefore safe to compare
// two of these to each other (ordering) but NOT to Date.now() — a clock skew
// between the orchestrator host and the operator's browser would show up as a
// nonsense "3 minutes ago". Consumers render these as absolute times and use
// Date.now() only for things the client itself observed.
//
// rosbridge on ROS 2 emits {sec, nanosec}; the ROS 1 spelling {secs, nsecs} is
// accepted too so a bridge shim cannot silently zero every timestamp.
function rosTimeToMs(t) {
  if (!t) return 0;
  const sec = t.sec ?? t.secs;
  const nsec = t.nanosec ?? t.nsecs ?? 0;
  if (typeof sec !== 'number' || !Number.isFinite(sec)) return 0;
  return sec * 1000 + nsec / 1e6;
}

// True for anything with an indexable numeric length: roslibjs hands us plain
// JS arrays (rosbridge base64-encodes only uint8[]), but a bridge that already
// produced typed arrays must not be rejected as malformed.
function isNumericSequence(v) {
  return Array.isArray(v) || ArrayBuffer.isView(v);
}

// One TaskQueueState.tasks row -> the record TaskQueue.jsx and FleetMap render.
//
// `assigned_robot`, `target_x` and `target_y` are FROZEN NAMES: FleetMap's
// drawSelectedTaskHighlight reads exactly those three off tasksById and
// FleetMap.jsx belongs to another owner. Everything else here is additive.
function projectTaskRow(row) {
  const target = row.target_location || {};
  return {
    id: row.task_id,
    type: row.task_type || '',
    status: row.status || 'PENDING',
    status_reason: row.status_reason || '',
    assigned_robot: row.assigned_robot || '',
    preferred_robot: row.preferred_robot || '',
    target_x: typeof target.x === 'number' ? target.x : 0,
    target_y: typeof target.y === 'number' ? target.y : 0,
    priority: typeof row.priority === 'number' ? row.priority : 0,
    progress: typeof row.progress === 'number' ? row.progress : 0,
    quantity_kg: typeof row.quantity_kg === 'number' ? row.quantity_kg : 0,
    auction_rounds: typeof row.auction_rounds === 'number' ? row.auction_rounds : 0,
    // The operator armed this injection as an EMERGENCY, so the orchestrator was
    // allowed to abort an auction already in flight to run this one. It is a
    // property of how the task entered the queue, not of what it is doing now:
    // an HTN-generated task can never carry it, and it stays true for the whole
    // life of the row including after the task finishes.
    //
    // ABSENT READS AS FALSE, WHICH IS THE OPPOSITE DEFAULT FROM pose_valid, and
    // the asymmetry is deliberate. `decodePoseValidity` reads an absent key as a
    // fix because the fail-safe there would blank the entire map against a bridge
    // that predates the field (see utils/poseFix.js). Here the two errors are not
    // symmetric either, but the other way round: a false negative loses a badge
    // on one row, while a false positive would label every ordinary row of a
    // pre-change orchestrator as an emergency preemption that never happened.
    // The badge is a claim about auction semantics and must not be invented.
    emergency: !!row.emergency,
    parent_task_id: row.parent_task_id || '',
    depends_on: row.depends_on || [],
    required_capabilities: row.required_capabilities || [],
    // When the STATUS last changed, publisher clock. Used for ordering only.
    status_changed_ms: rosTimeToMs(row.status_changed),
  };
}

// One ResourceMapUpdate -> the record ResourceGraph renders, or null if the
// message is unusable.
//
// WHY THIS VALIDATES AT ALL, when the sibling case for this topic used to
// project inline in App.jsx's roslib callback with no checks whatsoever.
// UPDATE_RESOURCE_MAP already rejects degenerate geometry, and its comment gives
// the reason in one line: "a canvas draws NaN as nothing at all". Exactly the
// same is true here and worse, because these values also reach a TEXT panel: a
// single non-finite ice_concentration makes `Peak` and `Avg` read "NaN wt%" for
// the rest of the session, since both are reductions over the whole array and
// nothing ever evicts a bad sample except the 500-cap.
//
// The three rules mirror the PRODUCER's own contract rather than inventing one.
// ProspectSkill averages the sigmas its HAL sensor reports and agent_node drops
// any reading whose sigma is non-finite or <= 0 (selene_agent/selene_agent/
// agent_node.py:1349-1369), so a sigma of 0 on the wire means something upstream
// of the agent's own filter is wrong and the sample is not trustworthy.
// `location` is required because ResourceGraph's edge computation is a distance
// between two locations and a missing one is a TypeError inside a 30 fps loop.
//
// NOT VALIDATED: the RANGE of ice_concentration. The 0-10 wt% figure the node
// radius and the colour law assume is a display convention, not a wire contract
// (ResourceMapUpdate.msg declares a bare float32), and clamping is the
// renderer's job. A 40 wt% reading should draw at the top of the scale and be
// visible, not be thrown away by the reducer.
function projectResourceReading(msg, seq) {
  if (!msg) return null;
  const loc = msg.location;
  if (!loc) return null;
  const x = loc.x;
  const y = loc.y;
  const conc = msg.ice_concentration;
  const sigma = msg.sensor_uncertainty;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (!Number.isFinite(conc)) return null;
  if (!Number.isFinite(sigma) || sigma <= 0) return null;
  return {
    scout_id: typeof msg.scout_id === 'string' ? msg.scout_id : '',
    location: { x, y },
    ice_concentration: conc,
    sensor_uncertainty: sigma,
    // Identity, not data. Never sent to a backend, never compared across tabs.
    clientSeq: seq,
  };
}

// One TaskQueueState.events element -> the record the history lists render.
function projectTaskEvent(ev) {
  const target = ev.target || {};
  return {
    seq: ev.seq,
    stamp_ms: rosTimeToMs(ev.stamp),
    kind: ev.kind || '',
    task_id: ev.task_id || '',
    robot_id: ev.robot_id || '',
    actor: ev.actor || '',
    action: ev.action || '',
    detail: ev.detail || '',
    // Meaningful only when kind === 'operator'; always false for 'status'.
    accepted: !!ev.accepted,
    // TaskEvent.target: the world point the operator picked, and zero for every
    // other event. Flattened to match the tasksById convention rather than
    // carrying a nested Point through the UI.
    target_x: typeof target.x === 'number' ? target.x : 0,
    target_y: typeof target.y === 'number' ? target.y : 0,
  };
}

// Exported so the reducer's lifecycle/RESET behaviour can be exercised
// directly, without a browser or a running rosbridge.
export function fleetReducer(state, action) {
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

      // D-31: does `pose` below carry a measurement, or the odometry sensor's
      // pre-first-message default of (0, 0)?
      //
      // THE POSE IS STORED EITHER WAY, and that is the deliberate half of this.
      // The obvious alternative — store `pose: null` when the fix is missing —
      // would be absorbed silently by guards that already exist all over the
      // consumers (`if (!robot.pose) return;` in planRobotMarks and
      // drawPlannedPaths, `pose?.x ?? 0` in RobotDetail): the robot would
      // vanish from the map with no trace and the detail panel would print a
      // confident 0.0 m. RobotState.msg is explicit that "`pose` IS STILL
      // POPULATED when this is false ... the flag, not the value, carries the
      // meaning", so the flag is what the reducer carries, and every consumer
      // is made to test it and to SAY what it found.
      const poseValidity = decodePoseValidity(msg);

      // D-03: the task-lifecycle inference that used to live here is GONE.
      //
      // It watched current_task_id appear and disappear and wrote PENDING /
      // ASSIGNED / IN_PROGRESS / COMPLETED into tasksById from that alone, so
      // it could never produce FAILED or INTERRUPTED, and a task the
      // orchestrator had CANCELLED looked exactly like one that had finished:
      // the id simply stopped appearing on the robot. tasksById is now replaced
      // wholesale from /orchestrator/task_queue, which carries the
      // orchestrator's own TaskStatus plus the reason it changed.

      return {
        ...state,
        robots: {
          ...state.robots,
          [id]: {
            robot_id: msg.robot_id,
            robot_type: msg.robot_type,
            fsm_state: msg.fsm_state,
            pose: msg.pose || { x: 0, y: 0, theta: 0 },
            // D-31: false means `pose` above is NOT a position. Snake_case
            // because it is a wire field; `poseValidReported` beside it is
            // camelCase because it is client-derived — it says whether the
            // publisher carried the field at all, which distinguishes a
            // measured "there is a fix" from the legacy assumption of one.
            pose_valid: poseValidity.poseValid,
            poseValidReported: poseValidity.poseValidReported,
            velocity: msg.velocity || { linear: { x: 0 }, angular: { z: 0 } },
            battery_level: msg.battery_level,
            // D-06: Wh, from the robot's own RCDL. 0 (or absent) means the
            // agent predates the field; consumers must treat it as unknown
            // rather than as a robot with no battery.
            battery_capacity_wh: msg.battery_capacity_wh,
            current_task_id: msg.current_task_id,
            task_progress: msg.task_progress,
            capabilities: msg.capabilities || [],
            lastUpdate: Date.now(),
            stateHistory,
          },
        },
      };
    }

    // The payload is the RAW ResourceMapUpdate off the wire. It used to be
    // projected inside App.jsx's roslib callback, which dereferenced
    // `msg.location.x` with no guard — a malformed message threw inside the
    // websocket handler rather than being counted and dropped here.
    case 'ADD_RESOURCE_READING': {
      const seq = state.resourceReadingSeq + 1;
      const projected = projectResourceReading(action.payload, seq);
      if (!projected) {
        // A rejected reading does NOT consume a clientSeq. The counter is an
        // identity supply for things that exist; burning numbers on messages
        // that never entered the array would make gaps in it mean nothing.
        return { ...state, resourceReadingsDropped: state.resourceReadingsDropped + 1 };
      }
      const readings = [projected, ...state.resourceReadings];
      if (readings.length > MAX_READINGS) readings.pop();
      return { ...state, resourceReadings: readings, resourceReadingSeq: seq };
    }

    case 'ADD_ALERT': {
      const alerts = [{ ...action.payload, timestamp: Date.now() }, ...state.alerts];
      if (alerts.length > MAX_ALERTS) alerts.pop();
      return { ...state, alerts };
    }

    // D-03/D-05: the authoritative task table, replaced WHOLESALE on every
    // snapshot (2 Hz). Deliberately not merged with what we already hold: a
    // complete snapshot means a browser loaded mid-mission — or one that missed
    // messages — is correct from the next one, with no reconciliation logic that
    // could itself go wrong. Tasks are never removed from the orchestrator's
    // queue, so history survives here too.
    case 'UPDATE_TASK_QUEUE': {
      const msg = action.payload || {};
      const rows = Array.isArray(msg.tasks) ? msg.tasks : [];
      const tasksById = {};
      for (const row of rows) {
        if (!row || !row.task_id) continue;
        tasksById[row.task_id] = projectTaskRow(row);
      }

      // The event ring is replayed in full in every snapshot, so dedupe on seq
      // (TaskEvent.msg says so explicitly). Keeping the ones we already hold is
      // what lets the client window be larger than the orchestrator's ring.
      let taskEvents = state.taskEvents;
      const incoming = Array.isArray(msg.events) ? msg.events : [];
      if (incoming.length > 0) {
        const held = new Set(taskEvents.map((e) => e.seq));
        const fresh = incoming
          .filter((e) => e && typeof e.seq === 'number' && !held.has(e.seq))
          .map(projectTaskEvent);
        if (fresh.length > 0) {
          taskEvents = [...taskEvents, ...fresh].sort((a, b) => a.seq - b.seq);
          if (taskEvents.length > MAX_TASK_EVENTS) {
            taskEvents = taskEvents.slice(taskEvents.length - MAX_TASK_EVENTS);
          }
        }
      }

      return {
        ...state,
        tasksById,
        taskEvents,
        taskQueueReceived: true,
        // Non-zero means the orchestrator's ring evicted events before we ever
        // saw them, so the history below is NOT the complete record. It is on
        // the wire precisely because a late-joining browser cannot derive it.
        taskEventsDropped: typeof msg.events_dropped === 'number'
          ? msg.events_dropped
          : state.taskEventsDropped,
      };
    }

    // D-02: fused posterior snapshot from /orchestrator/resource_map.
    //
    // ResourceMap.msg states that a consumer MUST reject a message whose four
    // parallel arrays disagree in length. That rejection happens HERE, once, so
    // FleetMap can index the four arrays together without a per-cell guard in
    // its 30 fps loop. A rejected snapshot leaves the previous map standing —
    // stale-but-consistent beats half-decoded — and bumps resourceMapDropped so
    // the legend can say the feed is being rejected instead of silently
    // freezing.
    case 'UPDATE_RESOURCE_MAP': {
      const msg = action.payload;
      const index = msg?.cell_index;
      const mean = msg?.cell_mean;
      const variance = msg?.cell_variance;
      const count = msg?.cell_observation_count;

      const arraysWellFormed = isNumericSequence(index)
        && isNumericSequence(mean)
        && isNumericSequence(variance)
        && isNumericSequence(count)
        && index.length === mean.length
        && index.length === variance.length
        && index.length === count.length;
      // Geometry is checked here too, not because ResourceMap.msg requires it
      // but because a zero or missing resolution/width/height turns every world
      // coordinate the renderer computes into NaN or a division by zero, and a
      // canvas draws NaN as nothing at all — the failure would be invisible.
      // Zero observed cells is legitimate (nothing surveyed yet) and accepted.
      // prior_variance is in the same list because it is the DENOMINATOR the
      // certainty/alpha channel normalises every cell against; a 0 or a missing
      // value would make the whole confidence axis NaN, which again draws as
      // nothing rather than as an error.
      const geometryWellFormed = Number.isFinite(msg?.resolution)
        && msg.resolution > 0
        && Number.isFinite(msg?.width) && msg.width > 0
        && Number.isFinite(msg?.height) && msg.height > 0
        && Number.isFinite(msg?.prior_mean)
        && Number.isFinite(msg?.prior_variance) && msg.prior_variance > 0;
      if (!arraysWellFormed || !geometryWellFormed) {
        return { ...state, resourceMapDropped: state.resourceMapDropped + 1 };
      }

      const origin = msg.origin || {};
      // D-15: THE CACHE KEY MUST BE UNIQUE FOR THE TAB, NOT FOR THE SESSION.
      //
      // This used to read `(state.resourceMap?.revision || 0) + 1`, and the
      // comment on it claimed the counter was "Monotonic and O(1): the only
      // correct trigger for rebuilding the raster". O(1) it was; monotonic it
      // was not. `case 'RESET'` returns `{ ...initialState }` and
      // `initialState.resourceMap` is null, so a rosbridge reconnect sent the
      // counter back to zero and the next accepted snapshot — carrying an
      // entirely different backend session's cells — was **revision 1 again**.
      //
      // FleetMap.buildPosteriorRaster short-circuits on
      // `store.revision === map.revision` and its store is a useRef that
      // survives the RESET (App.jsx renders FleetMap with no connection-keyed
      // `key`), so if exactly one snapshot had been rasterised before the drop,
      // the rebuild was SKIPPED: the canvas kept blitting the dead session's
      // cells while ResourceLegend already reported the new snapshot's counts.
      // The dimension guard in buildPosteriorRaster cannot catch it — width and
      // height are unchanged across a restart — and it is a fully surveyed map
      // drawn over a freshly restarted, empty one for up to one publish period
      // (2 s at resource_map_publish_rate 0.5 Hz).
      //
      // Counting in reducer state and having RESET carry the count forward is
      // preferred over the alternative — clearing FleetMap's rasterRef from an
      // effect keyed on the prop going null — for two reasons. It fixes the KEY
      // rather than one consumer of it, so any future consumer that caches on
      // `revision` is safe by construction. And it does not depend on React
      // ever rendering the null: RESET and the first snapshot of the new
      // session are two dispatches, and nothing guarantees a commit lands
      // between them.
      const revision = state.resourceMapRevision + 1;
      return {
        ...state,
        resourceMapRevision: revision,
        resourceMap: {
          // Monotonic for the lifetime of the tab and O(1) to compare: the only
          // correct trigger for rebuilding the raster. Object identity changes
          // on every accepted snapshot and receivedAt changes with the clock,
          // so neither is a staleness test.
          revision,
          // CLIENT clock, at receipt — this one the browser did observe, so it
          // is the right basis for an on-screen "map age".
          receivedAt: Date.now(),
          resolution: msg.resolution,
          width: msg.width,
          height: msg.height,
          originX: typeof origin.x === 'number' ? origin.x : 0,
          originY: typeof origin.y === 'number' ? origin.y : 0,
          priorMean: msg.prior_mean,
          priorVariance: msg.prior_variance,
          totalObservations: msg.total_observations,
          // Typed arrays: roslibjs delivers boxed-number JS arrays, and the
          // conversion is paid once per snapshot (0.5 Hz, <= 20k elements)
          // instead of in a loop that runs 60x more often than the data
          // arrives. cell_index is uint32 on the wire but Int32Array here — the
          // largest legal index is width*height-1 = 249999 for the default
          // 500x500 grid, four orders of magnitude inside int32.
          cellIndex: Int32Array.from(index),
          cellMean: Float32Array.from(mean),
          cellVariance: Float32Array.from(variance),
          cellCount: Int32Array.from(count),
        },
      };
    }

    // A-reconnect: drop everything that belongs to the previous backend session.
    //
    // Without this, a rosbridge reconnect merged the old session's tasks and
    // alerts into the new one, and a re-announced task id kept its old
    // COMPLETED status. A reviewer observed the merged state on 2026-07-29
    // after restarting the backend under a running dashboard: the task queue
    // read "3 active / 70 done" within seconds of a fresh backend whose own
    // counter had restarted at zero. RESET itself has been unit-exercised by
    // dispatching it directly; the reconnect path that dispatches it has not
    // been re-exercised end to end since.
    //
    // D-02/D-03: tasksById, taskEvents and resourceMap are all cleared too, and
    // that is now cheap rather than destructive — both are SNAPSHOT topics, so
    // they re-populate in full within one publish period (500 ms for the task
    // queue, 2 s for the posterior). That is what makes the reconnect-merge bug
    // class structurally impossible here rather than heuristically handled.
    // Operator UI preferences and the current selection are preserved so a
    // backend restart does not also reset what the operator was looking at;
    // selectedTaskId is dropped because task ids do not survive a restart.
    case 'RESET':
      return {
        ...initialState,
        heatmapVisible: state.heatmapVisible,
        selectedRobotId: state.selectedRobotId,
        // D-15: NOT reset. This is a cache key, not session data. Zeroing it
        // made the first snapshot of a new backend session collide with the
        // first snapshot of the old one, and FleetMap's raster cache then
        // skipped the rebuild it needed most. Every other field here is
        // deliberately dropped; this one is deliberately kept, and a test
        // (src/__tests__/fleetState.resourceMapRevision.test.js) asserts that
        // no revision value is ever issued twice in a tab's lifetime.
        resourceMapRevision: state.resourceMapRevision,
        // NOT reset, for exactly the D-15 reason above. This is the key
        // ResourceGraph's node table and the operator's selection are joined on.
        // `resourceReadings` itself IS cleared — those samples belong to the
        // dead session — but re-issuing clientSeq 1 for a new session's first
        // reading is the same collision D-15 was opened for: any node, hover or
        // selection still holding key 1 from the previous session would silently
        // re-bind to an unrelated sample instead of resolving to nothing.
        //
        // resourceReadingsDropped is deliberately NOT carried forward: it is a
        // per-session diagnostic like resourceMapDropped, and a count that
        // spanned sessions could not answer "is the CURRENT backend sending me
        // garbage".
        resourceReadingSeq: state.resourceReadingSeq,
      };

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
