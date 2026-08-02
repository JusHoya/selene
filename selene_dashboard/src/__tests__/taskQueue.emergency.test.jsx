/**
 * THE EMERGENCY BADGE — the row property, from the wire to the DOM.
 *
 * WHAT THE BADGE CLAIMS. `TaskStatus.emergency` is true only for an operator
 * injection that was armed as an emergency, which is the one thing that lets
 * the orchestrator ABORT an auction already in flight instead of queueing
 * behind it. An HTN-generated task can never carry it. The badge is therefore
 * not a severity or a priority: it is a statement about what the orchestrator
 * was permitted to do to the auction, and it must not appear on a row that did
 * not earn it.
 *
 * THE DEGRADE CASE IS THE INTERESTING ONE. rosbridge serialises from ITS OWN
 * selene_msgs build, so an orchestrator that predates the field publishes rows
 * with the key absent entirely and roslib hands the reducer `undefined`. That
 * must render an ORDINARY row. Note this is the opposite default from
 * `pose_valid` (utils/poseFix.js reads an absent key as a fix), and the
 * asymmetry is the point: there the fail-safe would blank the whole map, here
 * it would label every ordinary row of an older backend as a preemption that
 * never happened.
 *
 * BOTH COPIES OF THE RULE ARE PINNED, SEPARATELY. `projectTaskRow` coerces the
 * wire value and `TaskRow` coerces again, because TaskRow is also handed
 * hand-built records by other views and by tests and does not assume it went
 * through the projector. Two copies is the price of that, and what would be
 * unacceptable is only one of them being tested — the same reasoning
 * poseValidity.test.js records for hasPositionFix.
 *
 * WHAT THIS FILE CANNOT DO. jsdom does not paint. The red rail, the badge
 * colour and whether either is legible beside the status chip are not tested
 * here and are not tested anywhere; only opening the panel in Chrome shows
 * that. What is pinned is presence, absence, and the words.
 *
 * MUTATION RUN, EXECUTED. Baseline for this branch is 122 passed over 9 suites.
 *
 * (1) In hooks/useFleetState.js delete `emergency: !!row.emergency` from
 *     projectTaskRow — the field arrives on the wire and the reducer drops it.
 *     Whole run went 5 failed / 117 passed:
 *       · true, false and ABSENT decode to exactly two outcomes
 *       · the whole queue of a pre-change orchestrator reads as ordinary
 *       · an emergency row is badged and an ordinary row beside it is not
 *       · the row carries the modifier class and says why in its tooltip
 *       · a finished emergency task keeps its badge in the history section
 *     NOT among them: 'a row whose message never carried the field renders as
 *     ordinary'. That is correct and worth saying — dropping the projection
 *     makes every row read as ordinary, which is exactly what that test asks
 *     for. It is a guard on the DEGRADE path, not a regression test for the
 *     projection, and it cannot substitute for one.
 *
 * (2) In components/TaskQueue.jsx change TaskRow's `!!task.emergency` to
 *     `task.emergency !== false` — the ROS-2-flavoured wrong default, where an
 *     absent field reads as an emergency. Whole run went 1 failed / 121 passed:
 *     'TaskRow coerces for itself, not only through the reducer'.
 *     ONE TEST, AND THAT IS THE WHOLE ARGUMENT FOR ITS EXISTENCE. Every row
 *     that came through the reducer carries an explicit `false`, so the
 *     projector masks this mutation completely; only the hand-built records
 *     see it. A suite that tested the badge exclusively through
 *     UPDATE_TASK_QUEUE would have shipped a component that badges every row
 *     handed to it by any other view.
 *
 * (3) Force `const isEmergency = false` — the badge never renders. Whole run
 *     went 4 failed / 118 passed: the three badge-presence tests above plus
 *     'TaskRow coerces for itself'. The projection tests are NOT among them,
 *     which is the same split from the other side.
 */

import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import TaskQueue from '../components/TaskQueue';
import { fleetReducer, initialState } from '../hooks/useFleetState';

let host;
let root;

// One TaskQueueState.tasks row as rosbridge delivers it. `emergency` is spread
// from overrides so a test can set it true, set it false, or DELETE it — and
// the third is the state a pre-change orchestrator produces.
function wireRow(taskId, overrides = {}) {
  return {
    task_id: taskId,
    task_type: 'prospect',
    status: 'PENDING',
    status_reason: '',
    assigned_robot: '',
    preferred_robot: '',
    target_location: { x: -100, y: -150, z: 0 },
    priority: 5.0,
    progress: 0.0,
    quantity_kg: 0.0,
    auction_rounds: 0,
    parent_task_id: '',
    depends_on: [],
    required_capabilities: ['prospect'],
    status_changed: { sec: 1000, nanosec: 0 },
    emergency: false,
    ...overrides,
  };
}

/** The real reducer, fed a real-shaped snapshot. */
function snapshot(rows) {
  return fleetReducer(initialState, {
    type: 'UPDATE_TASK_QUEUE',
    payload: { tasks: rows, events: [], events_dropped: 0 },
  });
}

function render(state) {
  act(() => {
    root.render(<TaskQueue state={state} dispatch={() => {}} />);
  });
}

/** The <li> whose id cell reads `taskId`, or undefined. */
function rowFor(taskId) {
  return Array.from(host.querySelectorAll('.task-queue__row')).find(
    (li) => li.querySelector('.task-queue__id').textContent === taskId,
  );
}

const badgeIn = (li) => li.querySelector('.task-queue__emergency');

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete global.IS_REACT_ACT_ENVIRONMENT;
});

// ------------------------------------------------------------- the projection

describe('projectTaskRow carries emergency off the wire', () => {
  test('true, false and ABSENT decode to exactly two outcomes', () => {
    const absent = wireRow('survey_003');
    delete absent.emergency;
    const state = snapshot([
      wireRow('manual_0000', { emergency: true }),
      wireRow('survey_002', { emergency: false }),
      absent,
    ]);

    expect(state.tasksById.manual_0000.emergency).toBe(true);
    expect(state.tasksById.survey_002.emergency).toBe(false);
    // Not `undefined`, and not true. A missing field is a backend that cannot
    // report the property, which is not the same as a task that has it.
    expect(state.tasksById.survey_003.emergency).toBe(false);
  });

  test('the whole queue of a pre-change orchestrator reads as ordinary', () => {
    // The condition is per-BRIDGE, so it is never one row: either every row
    // carries the key or none does.
    const rows = ['survey_001', 'survey_002', 'excavate_001'].map((id) => {
      const row = wireRow(id);
      delete row.emergency;
      return row;
    });
    const state = snapshot(rows);
    Object.values(state.tasksById).forEach((task) => {
      expect(task.emergency).toBe(false);
    });
    expect(Object.keys(state.tasksById)).toHaveLength(3);
  });
});

// ------------------------------------------------------------------ the badge

describe('the emergency badge renders for emergency rows only', () => {
  test('an emergency row is badged and an ordinary row beside it is not', () => {
    render(snapshot([
      wireRow('manual_0000', { emergency: true, priority: 10.0 }),
      wireRow('survey_002'),
    ]));

    const emergencyRow = rowFor('manual_0000');
    const ordinaryRow = rowFor('survey_002');
    expect(emergencyRow).toBeDefined();
    expect(ordinaryRow).toBeDefined();

    expect(badgeIn(emergencyRow)).not.toBeNull();
    expect(badgeIn(emergencyRow).textContent).toBe('EMG');
    expect(badgeIn(ordinaryRow)).toBeNull();

    // Exactly one badge in the whole panel — the assertion that catches a badge
    // rendered unconditionally, which the two per-row checks above would miss
    // if the ordinary row were somehow not found.
    expect(host.querySelectorAll('.task-queue__emergency')).toHaveLength(1);
  });

  test('a row whose message never carried the field renders as ordinary', () => {
    const absent = wireRow('survey_002');
    delete absent.emergency;
    render(snapshot([absent]));

    const row = rowFor('survey_002');
    expect(row).toBeDefined();
    expect(badgeIn(row)).toBeNull();
    expect(row.className).not.toMatch(/task-queue__row--emergency/);
  });

  test('TaskRow coerces for itself, not only through the reducer', () => {
    // Its own copy of the rule, exercised with hand-built records that never
    // went near projectTaskRow — the shape every other view hands it.
    render({
      taskQueueReceived: true,
      tasksById: {
        no_field: { id: 'no_field', type: 'prospect', status: 'PENDING' },
        null_field: {
          id: 'null_field', type: 'prospect', status: 'PENDING', emergency: null,
        },
        armed: {
          id: 'armed', type: 'prospect', status: 'PENDING', emergency: true,
        },
      },
      taskEvents: [],
    });

    expect(badgeIn(rowFor('no_field'))).toBeNull();
    expect(badgeIn(rowFor('null_field'))).toBeNull();
    expect(badgeIn(rowFor('armed'))).not.toBeNull();
  });

  test('the row carries the modifier class and says why in its tooltip', () => {
    // The badge is three letters. The tooltip is where the semantics fit, and
    // it is the only place the panel can explain what "EMG" bought.
    render(snapshot([wireRow('manual_0000', { emergency: true, priority: 10.0 })]));

    const row = rowFor('manual_0000');
    expect(row.className).toMatch(/task-queue__row--emergency/);
    expect(row.getAttribute('title'))
      .toMatch(/EMERGENCY injection — allowed to preempt an auction in flight/);
  });

  test('an ordinary row says nothing about emergencies in its tooltip', () => {
    render(snapshot([wireRow('survey_002')]));
    expect(rowFor('survey_002').getAttribute('title'))
      .not.toMatch(/EMERGENCY/);
  });

  test('a finished emergency task keeps its badge in the history section', () => {
    // The flag records how the task ENTERED the queue, so it outlives the
    // auction it preempted. A completed row that lost the badge would make the
    // record of the preemption disappear at exactly the moment someone goes
    // looking for it.
    render(snapshot([wireRow('manual_0000', {
      emergency: true, status: 'COMPLETED', status_reason: 'skill_completed',
    })]));

    const row = rowFor('manual_0000');
    expect(row).toBeDefined();
    expect(badgeIn(row)).not.toBeNull();
  });
});

// --------------------------------------------------------- the six-column grid

describe('the badge does not disturb the row layout', () => {
  test('an emergency row has the same number of grid children as an ordinary one', () => {
    // .task-queue__row and .task-queue__col-header declare the SAME six-column
    // template in TaskQueue.css. A seventh direct child on the row and not on
    // the header would silently misalign every row under the header, which is
    // the kind of thing nothing but a screenshot would catch — so the badge
    // lives INSIDE the id cell and this counts the children to prove it.
    render(snapshot([
      wireRow('manual_0000', { emergency: true }),
      wireRow('survey_002'),
    ]));

    const emergencyRow = rowFor('manual_0000');
    const ordinaryRow = rowFor('survey_002');
    expect(emergencyRow.children).toHaveLength(ordinaryRow.children.length);
    expect(host.querySelector('.task-queue__col-header').children)
      .toHaveLength(ordinaryRow.children.length);
  });
});
