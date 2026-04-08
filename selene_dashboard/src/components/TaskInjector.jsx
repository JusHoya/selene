// Wave2-A4: Task injection panel — form + confirmation + service call + feedback.
// Implements FR-DASH-5. Calls the orchestrator InjectTask service via the
// useRosService hook. Supports map-click target picking via the pickerMode
// reducer cases (also Wave2-A4).
import React, { useState, useEffect } from 'react';
import { SERVICES, SERVICE_TYPES } from '../utils/rosTopics';
import './TaskInjector.css';

// Wave2-A4: Supported task types — must match orchestrator InjectTask handler
const TASK_TYPES = [
  { value: 'prospect', label: 'Survey Zone (Prospect)' },
  { value: 'excavate', label: 'Extract at Site' },
  { value: 'haul', label: 'Haul to Depot' },
];

function TaskInjector({ state, dispatch, callService }) {
  // Wave2-A4: Local form state
  const [taskType, setTaskType] = useState('prospect');
  const [targetX, setTargetX] = useState('');
  const [targetY, setTargetY] = useState('');
  const [quantity, setQuantity] = useState('0');
  const [assignedRobot, setAssignedRobot] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState(null);

  // Wave2-A4: Watch for picker result — populate target fields when a map-click arrives
  useEffect(() => {
    if (state.pickerResult && state.pickerMode === 'inject_task') {
      setTargetX(state.pickerResult.x.toFixed(1));
      setTargetY(state.pickerResult.y.toFixed(1));
      dispatch({ type: 'CLEAR_PICKER_MODE' });
    }
  }, [state.pickerResult, state.pickerMode, dispatch]);

  // Wave2-A4: Auto-dismiss feedback after a few seconds
  useEffect(() => {
    if (!feedback) return undefined;
    const timer = setTimeout(() => setFeedback(null), 4000);
    return () => clearTimeout(timer);
  }, [feedback]);

  // Wave2-A4: Enter map picker mode
  const handlePickOnMap = () => {
    dispatch({ type: 'SET_PICKER_MODE', payload: { mode: 'inject_task' } });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setShowConfirm(true);
  };

  // Wave2-A4: Confirm + call the orchestrator inject_task service
  const confirmSubmit = async () => {
    setShowConfirm(false);
    if (!callService) {
      setFeedback({ type: 'error', message: 'rosbridge not connected' });
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        task_type: taskType,
        target_location: {
          x: parseFloat(targetX) || 0,
          y: parseFloat(targetY) || 0,
          z: 0,
        },
        quantity: parseFloat(quantity) || 0,
        assigned_robot_id: assignedRobot || '',
      };
      const result = await callService(
        SERVICES.INJECT_TASK,
        SERVICE_TYPES.INJECT_TASK,
        payload,
      );
      if (result && result.success) {
        setFeedback({
          type: 'success',
          message: `Injected ${result.task_id || 'task'}`,
        });
        // Reset form on success
        setTargetX('');
        setTargetY('');
        setQuantity('0');
        setAssignedRobot('');
      } else {
        setFeedback({
          type: 'error',
          message: (result && result.message) || 'inject failed',
        });
      }
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err?.message || 'service call failed',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const robotIds = Object.keys(state?.robots || {});
  const canSubmit = targetX !== '' && targetY !== '' && !submitting;
  const needsQuantity = taskType === 'excavate' || taskType === 'haul';
  const isPicking = state?.pickerMode === 'inject_task';

  return (
    <div className="task-injector">
      <div className="task-injector__header">Inject Task</div>
      <form onSubmit={handleSubmit} className="task-injector__form">
        <label>
          Type
          <select
            value={taskType}
            onChange={(e) => setTaskType(e.target.value)}
          >
            {TASK_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>

        <div className="task-injector__target">
          <label>
            X (m)
            <input
              type="number"
              step="0.1"
              value={targetX}
              onChange={(e) => setTargetX(e.target.value)}
            />
          </label>
          <label>
            Y (m)
            <input
              type="number"
              step="0.1"
              value={targetY}
              onChange={(e) => setTargetY(e.target.value)}
            />
          </label>
          <button type="button" onClick={handlePickOnMap}>
            {isPicking ? 'Picking\u2026' : 'Pick on Map'}
          </button>
        </div>

        {needsQuantity && (
          <label>
            Quantity (kg)
            <input
              type="number"
              step="0.1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
        )}

        <label>
          Assign Robot (optional)
          <select
            value={assignedRobot}
            onChange={(e) => setAssignedRobot(e.target.value)}
          >
            <option value="">&mdash; auction &mdash;</option>
            {robotIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>

        <button type="submit" disabled={!canSubmit}>
          {submitting ? 'Submitting\u2026' : 'Submit'}
        </button>
      </form>

      {showConfirm && (
        <div className="task-injector__confirm">
          <p>
            Inject <strong>{taskType}</strong> task at ({targetX}, {targetY})
            {assignedRobot ? ` on ${assignedRobot}` : ' (auction)'}?
          </p>
          <div>
            <button type="button" onClick={confirmSubmit}>
              Confirm
            </button>
            <button type="button" onClick={() => setShowConfirm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {feedback && (
        <div
          className={`task-injector__feedback task-injector__feedback--${feedback.type}`}
        >
          {feedback.message}
        </div>
      )}
    </div>
  );
}

export default TaskInjector;
