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

// What this panel SENT, in this panel's own voice, for the feedback line.
//
// Not derived from the orchestrator's reply. The reply is rendered verbatim
// beside it and says what the ORCHESTRATOR decided; this says what left the
// browser. An operator who believed they had armed the control and had not
// needs to be able to tell those two apart, and a backend that silently ignored
// the field would otherwise be indistinguishable from a control that never set
// it.
//
// "ELIGIBLE TO", not "will". The dashboard does not own the preemption rule —
// the orchestrator preempts only a LOWER-priority auction (task_feed's
// should_preempt), and on most injections there is no auction in flight to
// preempt at all. Promising a preemption here would make this line a lie on the
// majority of injections.
function emergencySummary(armed) {
  return armed
    ? 'sent with emergency = TRUE — eligible to preempt a lower-priority'
      + ' auction already in flight'
    : 'sent with emergency = false — waits for any auction already in flight to'
      + ' resolve';
}

function TaskInjector({ state, dispatch, callService }) {
  // Wave2-A4: Local form state
  const [taskType, setTaskType] = useState('prospect');
  const [targetX, setTargetX] = useState('');
  const [targetY, setTargetY] = useState('');
  const [quantity, setQuantity] = useState('0');
  const [assignedRobot, setAssignedRobot] = useState('');
  // OFF by default, and re-set to OFF after every accepted injection (see the
  // reset block in confirmSubmit). An arming control that persists is the
  // accident: the operator arms it once for a genuine emergency and every
  // routine injection for the rest of the shift silently carries preemption
  // authority with it.
  const [emergency, setEmergency] = useState(false);
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
        // A DELIBERATE CHANGE TO AUCTION SEMANTICS, not a priority. Priority
        // alone has never been able to jump an auction that is already open:
        // the orchestrator runs one auction at a time and a higher-priority
        // task waits for the running one to resolve. This flag is what asks it
        // to abort that auction instead.
        //
        // ALWAYS SENT, never omitted when false. `emergency` is a trailing
        // field on InjectTask.srv, so rosbridge would default it to false for
        // us — but then the request the operator can read in a network trace
        // would not contain the field they just decided about, and a key that
        // appears only in the dangerous case is one nobody can prove is wired.
        // Sending it both ways is what makes the "false by default" assertion
        // in the test suite a measurement rather than an absence.
        emergency,
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
          sent: emergencySummary(emergency),
        });
        // Reset form on success
        setTargetX('');
        setTargetY('');
        setQuantity('0');
        setAssignedRobot('');
        // DISARMED HERE, and only here. Not in the error branches: an injection
        // that was rejected for a bad coordinate is one the operator is about
        // to retry, and silently dropping the emergency flag between the two
        // attempts would send the retry with different semantics from the one
        // they confirmed. Success is the point at which the decision has been
        // spent.
        setEmergency(false);
      } else {
        setFeedback({
          type: 'error',
          message: (result && result.message) || 'inject failed',
          // What was sent matters MOST on a failure — a rejected emergency is
          // the case where the operator needs to know whether the request they
          // are about to retry carried preemption authority.
          sent: emergencySummary(emergency),
        });
      }
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err?.message || 'service call failed',
        sent: emergencySummary(emergency),
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

        {/* THE EMERGENCY ARMING CONTROL.
            This is not a priority dial and it is not styled like one. Priority
            has never been able to jump a running auction \u2014 the orchestrator
            auctions one task at a time and everything else waits, whatever its
            priority. Arming this asks the orchestrator to ABORT the auction it
            is running, which is a change to auction semantics and costs the
            aborted task a round trip. The consequence is spelled out in BOTH
            states rather than only when armed, because "what happens if I leave
            this alone" is the question an operator actually has, and a control
            that only speaks when armed teaches nothing about the default. */}
        <div
          className={'task-injector__emergency'
            + (emergency ? ' task-injector__emergency--armed' : '')}
        >
          <label className="task-injector__emergency-arm">
            <input
              type="checkbox"
              checked={emergency}
              onChange={(e) => setEmergency(e.target.checked)}
              aria-label="emergency"
            />
            <span className="task-injector__emergency-title">
              {emergency ? '\u26a0 EMERGENCY \u2014 ARMED' : 'Emergency'}
            </span>
          </label>
          <div className="task-injector__emergency-consequence">
            {emergency
              ? 'preempts an auction already in flight: a lower-priority auction'
                + ' is aborted and this task is auctioned instead'
              : 'off \u2014 this task waits for an auction already in flight to'
                + ' resolve before it is auctioned'}
          </div>
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          className={emergency ? 'task-injector__submit--emergency' : undefined}
        >
          {submitting
            ? 'Submitting\u2026'
            : (emergency ? 'Submit EMERGENCY' : 'Submit')}
        </button>
      </form>

      {/* A8: visible reason the control is unavailable */}
      {notConnected && (
        <div className="task-injector__offline">
          rosbridge not connected &mdash; task injection unavailable
        </div>
      )}

      {showConfirm && (
        <div
          className={'task-injector__confirm'
            + (emergency ? ' task-injector__confirm--emergency' : '')}
        >
          <p>
            Inject{emergency ? ' EMERGENCY' : ''} <strong>{taskType}</strong>
            {' '}task at ({targetX}, {targetY})
            {needsQuantity
              ? (quantityValue > 0
                ? `, target ${quantityValue} kg`
                : ', fill to capacity')
              : ''}
            {assignedRobot
              ? `, prefer ${assignedRobot} (still auctioned)`
              : ' (auction)'}?
          </p>
          {/* The second step of the arming. The checkbox above is one click;
              this is where the cost is stated, at the moment it is about to be
              paid. The stranded-bidder sentence is not decoration: a robot that
              already bid on the aborted auction is told nothing, and stays in
              BIDDING — unable to bid on anything, including this emergency —
              until its own auction timeout expires. That is shipped agent
              behaviour (selene_agent/agent_node.py, _handle_bidding), and it is
              the reason an emergency injection is not free. */}
          {emergency && (
            <p className="task-injector__confirm-emergency">
              EMERGENCY: if a lower-priority auction is already in flight, the
              orchestrator ABORTS it and auctions this task instead. The aborted
              task returns to the queue with its round refunded, but any robot
              that had already bid on it stays in BIDDING until its own auction
              timeout expires — it can bid on nothing until then, including
              this. Leave the control off and this task simply waits its turn.
            </p>
          )}
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
          {/* What the BROWSER sent, beside what the orchestrator replied. See
              emergencySummary() for why these are two separate sentences and
              not one. */}
          {feedback.sent && (
            <span className="task-injector__feedback-sent">{feedback.sent}</span>
          )}
        </div>
      )}
    </div>
  );
}

export default TaskInjector;
