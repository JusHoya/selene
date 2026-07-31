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

  const robotIds = Object.keys(state?.robots || {});
  // A8: callService is null while rosbridge is disconnected, so this is now a
  // live check rather than a permanently-true one. Block submission and say why.
  const notConnected = !callService;
  const needsQuantity = taskType === 'excavate' || taskType === 'haul';
  const isPicking = state?.pickerMode === 'inject_task';

  // D-04: the quantity control means something now, so it has to be validated
  // before the service call rather than coerced. `parseFloat(quantity) || 0`
  // used to turn '-5' into -5 and 'abc' into 0 and send either one; the
  // orchestrator rejects a negative or non-finite quantity outright, and an
  // operator who typed one deserves to be told here, not by a failed call.
  // An empty field is rejected rather than read as 0 — 0 has a specific meaning
  // ("fill to capacity") and must be typed deliberately.
  const quantityValue = Number(quantity);
  let quantityError = '';
  if (needsQuantity) {
    if (quantity.trim() === '') {
      quantityError = 'enter a target mass (0 = fill to capacity)';
    } else if (!Number.isFinite(quantityValue)) {
      quantityError = 'target mass must be a number';
    } else if (quantityValue < 0) {
      quantityError = 'target mass cannot be negative';
    }
  }
  const canSubmit = targetX !== '' && targetY !== '' && !submitting
    && !notConnected && !quantityError;

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
    // D-04: the form stays editable behind the confirmation panel, so the
    // quantity can have been made invalid between opening it and confirming.
    // Re-check rather than trust the disabled state of a button pressed
    // earlier.
    if (quantityError) {
      setFeedback({ type: 'error', message: quantityError });
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
        // D-04: KILOGRAMS, and now read end to end — the orchestrator stores it
        // on the task, announces it, assigns it, and the excavate skill honours
        // it. 0.0 means unconstrained (fill to the robot's own RCDL capacity),
        // which is what every task did before the field was read at all.
        //
        // Forced to 0 for a task type that has no mass, so a value left in the
        // hidden field by a previous task type cannot be sent. InjectTask.srv
        // says a non-zero quantity on a prospect is accepted-and-ignored, so
        // this is belt and braces; it keeps the confirmation text truthful.
        quantity: needsQuantity ? quantityValue : 0,
        // D-04: a PREFERENCE, not an assignment. The orchestrator no longer
        // force-assigns on this field — the task enters the auction either way
        // and the preferred robot wins only if it bids.
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
          // Verbatim, so the operator reads what the orchestrator actually did
          // ('queued (preferred scout_01)', or that a quantity was ignored)
          // rather than a generic success this component made up.
          message: result.message || `Injected ${result.task_id || 'task'}`,
          taskId: result.task_id || '',
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
            Target mass (kg) &mdash; 0 = fill to capacity
            <input
              type="number"
              step="0.1"
              min="0"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              aria-invalid={quantityError ? 'true' : 'false'}
            />
            {/* D-04: a visible reason, not just a disabled button. */}
            {quantityError && (
              <span className="task-injector__field-error">{quantityError}</span>
            )}
          </label>
        )}

        <label>
          Preferred Robot (optional)
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

        {/* D-04: this used to read "Assign Robot", and it used to force-assign:
            the orchestrator pre-empted the chosen robot's running task and
            published a TaskAssignment directly, skipping the auction the PRD
            requires (docs/PRD.md:533). It is a preference now, and saying so
            here is the only place an operator would ever learn it. */}
        {assignedRobot && (
          <div className="task-injector__hint">
            prefer {assignedRobot} (still auctioned) &mdash; it wins only if it
            bids; if it does not bid the preference is dropped and the auction
            opens to the whole fleet
          </div>
        )}

        <button type="submit" disabled={!canSubmit}>
          {submitting ? 'Submitting\u2026' : 'Submit'}
        </button>
      </form>

      {/* A8: visible reason the control is unavailable */}
      {notConnected && (
        <div className="task-injector__offline">
          rosbridge not connected &mdash; task injection unavailable
        </div>
      )}

      {showConfirm && (
        <div className="task-injector__confirm">
          <p>
            Inject <strong>{taskType}</strong> task at ({targetX}, {targetY})
            {needsQuantity
              ? (quantityValue > 0
                ? `, target ${quantityValue} kg`
                : ', fill to capacity')
              : ''}
            {assignedRobot
              ? `, prefer ${assignedRobot} (still auctioned)`
              : ' (auction)'}?
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
          {feedback.taskId && (
            <span className="task-injector__feedback-id">{feedback.taskId}</span>
          )}
        </div>
      )}
    </div>
  );
}

export default TaskInjector;
