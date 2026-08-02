/**
 * THE EMERGENCY ARMING CONTROL — what leaves the browser, and when.
 *
 * WHAT THIS CHANGE IS. An operator injection may now ask the orchestrator to
 * ABORT an auction that is already in flight rather than queue behind it. That
 * is a deliberate change to auction semantics, not a defect fix: priority alone
 * has never been able to jump a running auction, because the orchestrator runs
 * one at a time and everything else waits whatever its priority. The whole
 * control surface for the new behaviour is a single trailing `emergency` field
 * on the InjectTask request — there is no new ROS parameter — so this panel is
 * the only place a human can express it, and these tests are the only thing
 * standing between "the checkbox renders" and "the checkbox is wired".
 *
 * WHY THE OUTGOING REQUEST IS THE SUBJECT. This repository has been bitten
 * seven times by the same shape: a field declared, configured, rendered — and
 * read by nobody. A checkbox whose state never reaches `callService` would look
 * completely correct on screen and in a screenshot. So every assertion below is
 * made against the payload object the REAL component handed to the REAL service
 * caller, not against the checkbox's own `checked` property.
 *
 * THE `false` CASE IS ASSERTED AS HARD AS THE `true` ONE, and deliberately so.
 * `emergency` is a trailing field, so rosbridge would default it for us if the
 * key were simply absent — which means an unwired control and a correctly wired
 * one that is switched off produce IDENTICAL behaviour on the wire. Asserting
 * that the key is PRESENT and `false` is what tells those two apart.
 *
 * WHAT THIS FILE CANNOT DO. jsdom does not paint. Nothing here is evidence that
 * the armed control is visually distinct, that the red is legible, or that an
 * operator would notice it — the styling lives in TaskInjector.css and only
 * opening the dashboard in Chrome demonstrates it. What is pinned here is the
 * request, the class names and the words, which is the machine-checkable half.
 * There is also no rosbridge and no orchestrator in this file: `callService` is
 * a spy, so nothing below is evidence that the backend honours the field.
 *
 * MUTATION RUN, EXECUTED — the numbers below were read off real runs, not
 * reasoned about. Baseline for this branch is 122 passed over 9 suites.
 *
 * (1) In components/TaskInjector.jsx delete the `emergency,` line from the
 *     `payload` object literal — i.e. render the whole control and never send
 *     what it decides, which is the exact "wired but never read" shape this
 *     repository has been bitten by seven times. Whole run went 6 failed / 116
 *     passed, all six in this file:
 *       · is PRESENT and false on an ordinary injection
 *       · is true when the control is armed
 *       · the confirmation panel names the consequence before it is paid
 *       · an ordinary confirmation carries no emergency warning
 *       · an accepted emergency DISARMS the control
 *       · a REJECTED emergency stays armed
 *     Note which tests are NOT among them: every assertion about the checkbox,
 *     the button label and the panel classes still passes. A suite built only
 *     out of those would have certified an unwired control.
 *
 * (2) Delete `setEmergency(false)` from confirmSubmit's success branch — the
 *     arming persists across injections. Whole run went 1 failed / 121 passed:
 *     'an accepted emergency DISARMS the control, so the next one is ordinary'.
 *     One test, and it is the one that reads the SECOND request off the spy;
 *     the checkbox assertion beside it fails too, but they are in the same test
 *     deliberately, because a disarmed-looking checkbox that still sends true
 *     is worse than either failure alone.
 */

// `act` from 'react', not from 'react-dom/test-utils', for the same reason as
// resourceGraph.lifecycle.test.jsx: React 18.3.1 warns on every call to the
// latter.
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import TaskInjector from '../components/TaskInjector';
import { SERVICES, SERVICE_TYPES } from '../utils/rosTopics';

let host;
let root;

// A fleet with two robots, so the "preferred robot" select has options and this
// suite exercises the same form an operator sees rather than a degenerate one.
const STATE = {
  robots: {
    scout_01: { robot_id: 'scout_01' },
    hauler_01: { robot_id: 'hauler_01' },
  },
  pickerMode: null,
  pickerResult: null,
};

function render(props) {
  act(() => {
    root.render(
      <TaskInjector state={STATE} dispatch={() => {}} {...props} />,
    );
  });
}

// React installs its own value setter on the input element, so assigning
// `el.value` directly is invisible to it. This is the standard escape hatch:
// call the PROTOTYPE's setter, then fire the event React listens for.
function setValue(el, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value',
  ).set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

const form = () => host.querySelector('.task-injector__form');
const armCheckbox = () => host.querySelector('.task-injector__emergency-arm input');
const submitButton = () => host.querySelector('button[type="submit"]');
const confirmPanel = () => host.querySelector('.task-injector__confirm');
const confirmButton = () => host.querySelector('.task-injector__confirm button');
const feedback = () => host.querySelector('.task-injector__feedback');

function fillTarget(x, y) {
  const inputs = host.querySelectorAll('.task-injector__target input');
  act(() => setValue(inputs[0], x));
  act(() => setValue(inputs[1], y));
}

function arm() {
  act(() => {
    armCheckbox().click();
  });
}

// The submit event is dispatched on the FORM rather than by clicking the submit
// button. Clicking would go through jsdom's implicit-submission behaviour,
// which differs by jsdom version and is not what is under test here; the
// component's contract is that its onSubmit opens the confirmation panel.
function submit() {
  act(() => {
    form().dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    );
  });
}

// confirmSubmit is async and awaits the service call, so the act() must be
// awaited too or the assertions run before the promise settles.
async function confirm() {
  await act(async () => {
    confirmButton().click();
  });
}

function accepting() {
  return jest.fn().mockResolvedValue({
    success: true,
    task_id: 'manual_0000',
    message: 'queued (emergency: may preempt an auction in flight)',
  });
}

/** The payload object the component handed to callService on its Nth call. */
function payloadOf(spy, n = 0) {
  return spy.mock.calls[n][2];
}

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

// ------------------------------------------------------- the outgoing request

describe('the emergency field on the InjectTask request', () => {
  test('is PRESENT and false on an ordinary injection', () => {
    // The load-bearing case. An unwired checkbox and a correctly wired one that
    // is switched off are indistinguishable unless the key is asserted present.
    const callService = accepting();
    render({ callService });
    fillTarget('-100', '-150');
    submit();
    return confirm().then(() => {
      expect(callService).toHaveBeenCalledTimes(1);
      const [name, type, payload] = callService.mock.calls[0];
      expect(name).toBe(SERVICES.INJECT_TASK);
      expect(type).toBe(SERVICE_TYPES.INJECT_TASK);
      expect(Object.prototype.hasOwnProperty.call(payload, 'emergency'))
        .toBe(true);
      expect(payload.emergency).toBe(false);
      // A boolean, not a string or a number: the srv field is `bool` and
      // rosbridge is not asked to coerce anything.
      expect(typeof payload.emergency).toBe('boolean');
    });
  });

  test('is true when the control is armed', async () => {
    const callService = accepting();
    render({ callService });
    fillTarget('-100', '-150');
    arm();
    submit();
    await confirm();

    expect(payloadOf(callService).emergency).toBe(true);
    // Nothing else about the request changed: the emergency flag is not a
    // priority, not a preference and not an assignment, and it must not have
    // quietly become one of those.
    expect(payloadOf(callService).assigned_robot_id).toBe('');
    expect(payloadOf(callService).task_type).toBe('prospect');
    expect(payloadOf(callService).target_location)
      .toEqual({ x: -100, y: -150, z: 0 });
  });

  test('the default is OFF on a freshly mounted panel', () => {
    render({ callService: accepting() });
    expect(armCheckbox().checked).toBe(false);
    expect(host.querySelector('.task-injector__emergency--armed')).toBeNull();
    expect(submitButton().textContent).toBe('Submit');
  });
});

// ------------------------------------------------- arming, and un-arming again

describe('arming is deliberate and does not persist', () => {
  test('the armed panel says so in three places at once', () => {
    // Colour alone is not readable aloud and is not available to a colour-blind
    // operator, so the arming has to be visible in TEXT as well. Asserted on
    // the words and the class names, which is all jsdom can see.
    render({ callService: accepting() });
    arm();

    expect(armCheckbox().checked).toBe(true);
    expect(host.querySelector('.task-injector__emergency--armed')).not.toBeNull();
    expect(submitButton().textContent).toBe('Submit EMERGENCY');
    expect(host.querySelector('.task-injector__emergency-consequence').textContent)
      .toMatch(/preempts an auction already in flight/);
    // Precise about WHICH auction, because the shipped predicate is
    // (task_feed.should_preempt): the running task must be strictly lower
    // priority. A panel promising to preempt any auction would be over-claiming
    // on the one case the operator most needs to predict.
    expect(host.querySelector('.task-injector__emergency-consequence').textContent)
      .toMatch(/lower-priority/);
  });

  test('the disarmed panel still explains what the default DOES', () => {
    // A control that only speaks when armed teaches an operator nothing about
    // the case they are in every other time.
    render({ callService: accepting() });
    expect(host.querySelector('.task-injector__emergency-consequence').textContent)
      .toMatch(/waits for an auction already in flight/);
  });

  test('the confirmation panel names the consequence before it is paid', async () => {
    const callService = accepting();
    render({ callService });
    fillTarget('-100', '-150');
    arm();
    submit();

    expect(confirmPanel().className)
      .toMatch(/task-injector__confirm--emergency/);
    const warning = host.querySelector('.task-injector__confirm-emergency');
    expect(warning).not.toBeNull();
    expect(warning.textContent).toMatch(/ABORTS it/);
    // The cost, not just the capability: a robot that had already bid on the
    // aborted auction is told nothing and is stuck until its own timeout.
    expect(warning.textContent).toMatch(/stays in\s+BIDDING/);

    await confirm();
    expect(payloadOf(callService).emergency).toBe(true);
  });

  test('an ordinary confirmation carries no emergency warning', async () => {
    const callService = accepting();
    render({ callService });
    fillTarget('-100', '-150');
    submit();

    expect(confirmPanel().className)
      .not.toMatch(/task-injector__confirm--emergency/);
    expect(host.querySelector('.task-injector__confirm-emergency')).toBeNull();

    await confirm();
    expect(payloadOf(callService).emergency).toBe(false);
  });

  test('an accepted emergency DISARMS the control, so the next one is ordinary', async () => {
    // THE ACCIDENT THIS PREVENTS. An arming control that persists is armed once
    // for a real emergency and then silently carries preemption authority into
    // every routine injection for the rest of the shift.
    const callService = accepting();
    render({ callService });
    fillTarget('-100', '-150');
    arm();
    submit();
    await confirm();
    expect(payloadOf(callService, 0).emergency).toBe(true);

    expect(armCheckbox().checked).toBe(false);
    expect(submitButton().textContent).toBe('Submit');

    // ...and the very next injection proves it on the wire rather than on the
    // checkbox, which is the only proof that counts here.
    fillTarget('-80', '-120');
    submit();
    await confirm();
    expect(callService).toHaveBeenCalledTimes(2);
    expect(payloadOf(callService, 1).emergency).toBe(false);
  });

  test('a REJECTED emergency stays armed, so a retry is not silently downgraded', async () => {
    // The other half of the same decision. The operator is about to retype a
    // coordinate and press submit again; dropping the flag between the attempt
    // they confirmed and the retry would change the semantics under them.
    const callService = jest.fn().mockResolvedValue({
      success: false,
      task_id: '',
      message: 'target (-100.0, -150.0) is outside the terrain',
    });
    render({ callService });
    fillTarget('-100', '-150');
    arm();
    submit();
    await confirm();

    expect(payloadOf(callService).emergency).toBe(true);
    expect(armCheckbox().checked).toBe(true);
    expect(submitButton().textContent).toBe('Submit EMERGENCY');
  });
});

// ------------------------------------------------------------ what was sent

describe('the feedback names what the browser sent', () => {
  test('an accepted emergency reports the orchestrator AND the request', async () => {
    const callService = accepting();
    render({ callService });
    fillTarget('-100', '-150');
    arm();
    submit();
    await confirm();

    // The orchestrator's own message, verbatim — unchanged behaviour, asserted
    // here because the new line must be added BESIDE it and not instead of it.
    expect(feedback().textContent)
      .toMatch(/queued \(emergency: may preempt an auction in flight\)/);
    const sent = host.querySelector('.task-injector__feedback-sent');
    expect(sent).not.toBeNull();
    expect(sent.textContent).toMatch(/emergency = TRUE/);
  });

  test('an ordinary injection says that too, rather than saying nothing', async () => {
    // An operator who believed they had armed the control and had not is the
    // person this line is for. Silence would look identical to success.
    const callService = accepting();
    render({ callService });
    fillTarget('-100', '-150');
    submit();
    await confirm();

    const sent = host.querySelector('.task-injector__feedback-sent');
    expect(sent).not.toBeNull();
    expect(sent.textContent).toMatch(/emergency = false/);
  });

  test('a rejected call still says what was sent', async () => {
    const callService = jest.fn().mockRejectedValue(
      Object.assign(new Error('rosbridge not connected'), { code: 'NOT_CONNECTED' }),
    );
    render({ callService });
    fillTarget('-100', '-150');
    arm();
    submit();
    await confirm();

    expect(feedback().className).toMatch(/task-injector__feedback--error/);
    expect(host.querySelector('.task-injector__feedback-sent').textContent)
      .toMatch(/emergency = TRUE/);
  });
});
