"""``AgentFSM``'s transition observer -- deviation D-34.

WHAT THIS IS FOR. ``/{robot_id}/state`` was a level signal sampled from a
0.5 s timer, so a state shorter than the sampling period could not be
represented on the wire at all. Measured from the two exit-gate runs' launch
logs (``docs/phase5_deviation_register.md`` D-34), the IDLE window between an
operator cancel and the next bid lasted 0.247 s and 0.301 s; neither run's
probe ever saw an IDLE sample, so checks 6 and 9 SKIPped and PRD rows 3 and 4
went unmeasured on a system that had done exactly what they assert.

The fix is an observer on the one place any state changes -- ``handle_event``
-- that ``AgentNode`` hangs its state publisher off. This file drives the REAL
``AgentFSM``; nothing here is a double. It is ROS-free: ``fsm.py`` imports
nothing but ``time``, ``enum`` and ``typing``.

ALL BUT ONE OF THESE FAIL WITHOUT THE FIX, and fail at the point of contact:
``AgentFSM.__init__`` had no ``on_transition`` parameter and the class had no
``set_transition_observer``, so construction raises ``TypeError`` and the
setter raises ``AttributeError``. Confirmed by mutation -- see the module
docstring of ``test_agent_state_publish_wiring.py`` for the mutations run
against the node half.
"""

from __future__ import annotations

import pytest

from selene_agent.fsm import (
    AgentFSM, AgentState, FSMEvent, InvalidTransitionError,
)


def _spy_fsm(record, robot_id="obs_bot"):
    """FSM whose observer appends ``(prev, event, new, state_at_call)``."""
    fsm = AgentFSM(robot_id, logger=lambda msg: None)

    def observer(prev, event, new):
        record.append((prev, event, new, fsm.state))

    fsm.set_transition_observer(observer)
    return fsm


# ---- The hook exists and fires ---------------------------------------------

def test_observer_fires_once_per_legal_transition():
    seen: list[tuple] = []
    fsm = _spy_fsm(seen)

    fsm.handle_event(FSMEvent.TASK_ANNOUNCED)
    fsm.handle_event(FSMEvent.AUCTION_WON)

    assert len(seen) == 2, (
        'exactly one notification per successful transition; got '
        f'{len(seen)} for 2 transitions'
    )
    assert seen[0][:3] == (
        AgentState.IDLE, FSMEvent.TASK_ANNOUNCED, AgentState.BIDDING)
    assert seen[1][:3] == (
        AgentState.BIDDING, FSMEvent.AUCTION_WON, AgentState.ASSIGNED)


def test_observer_sees_the_state_already_moved():
    """``fsm.state is new_state`` when the callback runs.

    Load-bearing: ``AgentNode._on_fsm_transition`` builds the message from
    ``self._fsm.state``, not from the ``new_state`` argument. If the hook fired
    before the assignment, every on-change sample would carry the state the
    robot had just LEFT -- an aliasing defect worse than the one D-34 is about,
    because it would be wrong rather than merely absent.
    """
    seen: list[tuple] = []
    fsm = _spy_fsm(seen)

    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)

    prev, event, new, state_at_call = seen[0]
    assert state_at_call is AgentState.NAVIGATING
    assert state_at_call is new


def test_observer_sees_the_transition_log_already_written():
    """The log entry for this edge exists by the time the callback runs.

    Same reason as the state ordering above: an observer that reads the FSM
    must see a settled FSM, not one mid-update.
    """
    lengths: list[int] = []
    fsm = AgentFSM('log_bot', logger=lambda msg: None)
    fsm.set_transition_observer(
        lambda p, e, n: lengths.append(len(fsm.get_transition_log())))

    fsm.handle_event(FSMEvent.TASK_ANNOUNCED)
    fsm.handle_event(FSMEvent.AUCTION_LOST)

    assert lengths == [1, 2]


def test_constructor_argument_and_setter_are_equivalent():
    """Both wiring routes work; the node uses the setter, tests use either.

    ``AgentNode`` cannot use the constructor argument -- ``self._state_pub``
    does not exist yet at the ``AgentFSM(...)`` call -- but the parameter is
    the natural one for any other caller, so both are supported and both are
    pinned.
    """
    ctor_seen: list[tuple] = []
    ctor = AgentFSM('ctor_bot', logger=lambda m: None,
                    on_transition=lambda p, e, n: ctor_seen.append((p, e, n)))
    ctor.handle_event(FSMEvent.TASK_ANNOUNCED)

    setter_seen: list[tuple] = []
    setter = AgentFSM('setter_bot', logger=lambda m: None)
    setter.set_transition_observer(
        lambda p, e, n: setter_seen.append((p, e, n)))
    setter.handle_event(FSMEvent.TASK_ANNOUNCED)

    assert ctor_seen == setter_seen != []


def test_observer_can_be_detached():
    seen: list[tuple] = []
    fsm = _spy_fsm(seen)
    fsm.handle_event(FSMEvent.TASK_ANNOUNCED)
    assert len(seen) == 1

    fsm.set_transition_observer(None)
    fsm.handle_event(FSMEvent.AUCTION_WON)
    assert len(seen) == 1, 'a detached observer must not be called again'


# ---- The hook does NOT fire ------------------------------------------------

def test_observer_not_called_on_a_rejected_transition():
    """A refused event is not an edge and must not publish one.

    Without this, an ``ARRIVED`` arriving in IDLE -- which the FSM correctly
    refuses -- would still put a RobotState on the wire, and the gate probe
    counts samples.
    """
    seen: list[tuple] = []
    fsm = _spy_fsm(seen)

    with pytest.raises(InvalidTransitionError):
        fsm.handle_event(FSMEvent.ARRIVED)

    assert seen == []
    assert fsm.state is AgentState.IDLE


# ---- The hook cannot damage the FSM ----------------------------------------

def test_a_raising_observer_does_not_corrupt_the_fsm():
    """An exception in the observer is caught, logged, and does not escape.

    ``handle_event`` is called from timer callbacks, DDS subscription
    callbacks and a service handler. An exception escaping any of those takes
    the whole agent node down -- a state publisher that cannot serialise is
    not a reason to stop a robot's FSM.
    """
    logged: list[str] = []
    fsm = AgentFSM('boom_bot', logger=logged.append)

    def bad(prev, event, new):
        raise RuntimeError('publisher exploded')

    fsm.set_transition_observer(bad)

    result = fsm.handle_event(FSMEvent.TASK_ANNOUNCED)

    assert result is AgentState.BIDDING
    assert fsm.state is AgentState.BIDDING
    assert len(fsm.get_transition_log()) == 1
    assert any('publisher exploded' in line for line in logged), (
        'a failing observer must be logged, not swallowed silently -- a filter '
        'whose rejections are invisible is how D-31 survived a full run'
    )

    # And the next transition still notifies: the guard is released.
    later: list[tuple] = []
    fsm.set_transition_observer(lambda p, e, n: later.append((p, e, n)))
    fsm.handle_event(FSMEvent.AUCTION_WON)
    assert len(later) == 1


def test_a_reentrant_observer_transitions_but_does_not_renotify():
    """The ``_notifying`` guard, stated exactly as it behaves.

    An observer that fires an event still moves the FSM -- the machine is not
    frozen while notifying -- but produces no nested notification, so a
    careless observer cannot recurse without bound. This is LOGICAL
    re-entrancy only; the agent runs a SingleThreadedExecutor and this is not
    a lock (see ``AgentFSM._notify_transition``).
    """
    seen: list[tuple] = []
    fsm = AgentFSM('reentrant_bot', logger=lambda m: None)

    def observer(prev, event, new):
        seen.append((prev, event, new))
        if event is FSMEvent.TASK_ANNOUNCED:
            # Fired from inside the notification: the FSM must move...
            fsm.handle_event(FSMEvent.AUCTION_LOST)

    fsm.set_transition_observer(observer)
    fsm.handle_event(FSMEvent.TASK_ANNOUNCED)

    # ...and it did.
    assert fsm.state is AgentState.IDLE
    assert [e['event'] for e in fsm.get_transition_log()] == [
        FSMEvent.TASK_ANNOUNCED, FSMEvent.AUCTION_LOST,
    ]
    # But only the outer edge was announced.
    assert seen == [
        (AgentState.IDLE, FSMEvent.TASK_ANNOUNCED, AgentState.BIDDING),
    ]


def test_unbounded_recursion_is_impossible():
    """A pathological observer that re-fires its own event terminates.

    Without the guard this is infinite mutual recursion inside a DDS callback.
    """
    fsm = AgentFSM('loop_bot', logger=lambda m: None)
    calls = {'n': 0}

    def observer(prev, event, new):
        calls['n'] += 1
        if calls['n'] < 100:  # a real bug would not stop; this test must
            fsm.handle_event(FSMEvent.FAULT)

    fsm.set_transition_observer(observer)
    fsm.handle_event(FSMEvent.FAULT)

    assert calls['n'] == 1
    assert fsm.state is AgentState.ERROR


# ---- The default is unchanged ----------------------------------------------

def test_no_observer_is_the_default_and_costs_nothing():
    """23 pre-existing ``test_fsm.py`` cases construct AgentFSM with no hook.

    Characterization pin, not a regression test: it asserts the property that
    made the change safe to land, rather than a behaviour that was broken.
    """
    fsm = AgentFSM('plain_bot', logger=lambda m: None)
    assert fsm.handle_event(FSMEvent.TASK_ANNOUNCED) is AgentState.BIDDING
    assert fsm.state is AgentState.BIDDING
