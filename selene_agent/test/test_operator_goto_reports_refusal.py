"""`send_to_location` must not report success for a goal it cannot reach.

WHY THIS FILE EXISTS
--------------------
Measured on the 2026-08-01 exit gate, three lines inside half a millisecond:

    [scout_02] NAVIGATING --(OPERATOR_GOTO)--> NAVIGATING
    [scout_02] Operator goto plan failed: goal (-81.5, -94.5) is on 26.1 deg
               ground, over the 20.0 deg traversable limit; a robot could not
               stop, work or set off again there
    [scout_02] NAVIGATING --(OPERATOR_CANCEL)--> IDLE

The terrain guard did exactly its job. What was wrong is that
``operator_command_logic`` had already decided to answer ``accepted=True``:
it called ``ctx.start_navigation(...)``, discarded the return value, and set
``response.accepted = True`` unconditionally. So the operator was told the
command had been taken, the robot returned to IDLE 0.3 ms later, and the only
record of the refusal was a log line on the robot.

That is the same defect class as a skill reporting mass it never moved: a
success answer for work that did not happen. The exit gate's check 11 then
measured a stale ``planned_path`` and blamed the OVERRIDE for the terrain
guard's correct refusal.

WHY IT SURFACED ONLY NOW. Until D-28 was closed at 9c1a4d7 nothing read
``navigation.max_traversable_slope_deg``, so A* refused a goal for occupancy or
bounds alone and this path was nearly unreachable. With the slope rule live, a
6 m heading-relative pick lands on refused ground often enough to matter.
"""

from unittest.mock import MagicMock

import pytest

from selene_agent.fsm import AgentState, FSMEvent
from selene_agent.operator_command import operator_command_logic


class _Ctx:
    """Minimal operator-command context whose planner verdict is settable."""

    def __init__(self, plan_failure=''):
        self.robot_id = 'scout_01'
        self.state = AgentState.IDLE
        self.current_skill = None
        self.current_task_id = ''
        self.pending_task_id = ''
        self.operator_target = None
        self.last_seq = 0
        self.events = []
        self.nav_starts = []
        self.warns = []
        self._plan_failure = plan_failure

        self.get_state = lambda: self.state
        self.fire_event = self._fire
        self.get_current_skill = lambda: self.current_skill
        self.set_current_skill = lambda s: setattr(self, 'current_skill', s)
        self.set_current_task_id = lambda t: setattr(self, 'current_task_id', t)
        self.get_pending_task_id = lambda: self.pending_task_id
        self.set_pending_task_id = lambda t: setattr(self, 'pending_task_id', t)
        self.publish_bid_withdrawal = lambda *a: None
        self.start_navigation = self._start_navigation
        self.set_operator_target = lambda t: setattr(self, 'operator_target', t)
        self.start_recharge = lambda: None
        self.get_last_seq = lambda: self.last_seq
        self.set_last_seq = lambda s: setattr(self, 'last_seq', s)
        self.log_warn = self.warns.append
        self.stop_navigation = lambda: None

    def _fire(self, event):
        self.events.append(event)
        if event == FSMEvent.OPERATOR_GOTO:
            self.state = AgentState.NAVIGATING
        elif event == FSMEvent.OPERATOR_CANCEL:
            self.state = AgentState.IDLE

    def _start_navigation(self, x, y):
        self.nav_starts.append((float(x), float(y)))
        if self._plan_failure:
            # Mirror the real agent: it drops back to IDLE itself before
            # returning the reason.
            self._fire(FSMEvent.OPERATOR_CANCEL)
        return self._plan_failure


def _request(command='send_to_location', x=-81.5, y=-94.5, seq=1):
    req = MagicMock()
    req.command = command
    req.sequence = seq
    req.target.x = x
    req.target.y = y
    return req


def _response():
    resp = MagicMock()
    resp.accepted = None
    resp.reason = None
    return resp


REFUSAL = ('goal (-81.5, -94.5) is on 26.1 deg ground, over the 20.0 deg '
           'traversable limit')


def test_a_refused_goal_is_reported_as_not_accepted():
    """THE 2026-08-01 CASE. The planner refused; the operator must be told."""
    ctx = _Ctx(plan_failure=REFUSAL)
    resp = operator_command_logic(ctx, _request(), _response())

    assert resp.accepted is False, (
        'send_to_location reported success for a goal the terrain guard '
        'refused; that is what made check 11 blame the override')
    assert resp.reason == REFUSAL, (
        'the refusal reached the operator with no reason attached')
    assert '26.1 deg' in resp.reason


def test_a_reachable_goal_is_still_accepted():
    """The fix must not make every goto fail."""
    ctx = _Ctx(plan_failure='')
    resp = operator_command_logic(ctx, _request(), _response())

    assert resp.accepted is True
    assert resp.reason == ''
    assert ctx.nav_starts == [(-81.5, -94.5)]
    assert ctx.current_task_id == 'override_goto_1'
    assert FSMEvent.OPERATOR_GOTO in ctx.events


def test_a_refused_goal_leaves_no_pseudo_task_behind():
    """A robot that refused must not still advertise override_goto_<seq>.

    The dashboard renders `current_task_id` and the exit gate matches on it, so
    a leftover pseudo-task id would say the robot is under an operator command
    it has already abandoned.
    """
    ctx = _Ctx(plan_failure=REFUSAL)
    operator_command_logic(ctx, _request(seq=7), _response())

    assert ctx.current_task_id == '', (
        f'left current_task_id={ctx.current_task_id!r} after a refused goto')
    assert ctx.operator_target is None


def test_a_refused_goal_still_records_the_sequence():
    """Sequence bookkeeping must not be skipped by the refusal path.

    `get_last_seq`/`set_last_seq` is how a duplicate request is rejected. If a
    refused command did not record its sequence, a retry of the SAME sequence
    would be treated as new.
    """
    ctx = _Ctx(plan_failure=REFUSAL)
    operator_command_logic(ctx, _request(seq=42), _response())
    assert ctx.last_seq == 42


def test_the_robot_ends_in_idle_after_a_refusal():
    """It must not be stranded in NAVIGATING with no path."""
    ctx = _Ctx(plan_failure=REFUSAL)
    operator_command_logic(ctx, _request(), _response())
    assert ctx.state == AgentState.IDLE
    assert FSMEvent.OPERATOR_CANCEL in ctx.events


@pytest.mark.parametrize('command', ['cancel_task', 'force_recharge'])
def test_other_operator_commands_are_untouched(command):
    """Only send_to_location consults the planner."""
    ctx = _Ctx(plan_failure=REFUSAL)
    resp = operator_command_logic(ctx, _request(command=command), _response())
    assert resp.accepted is True
    assert ctx.nav_starts == []


def test_a_context_whose_start_navigation_returns_none_still_accepts():
    """Backwards compatibility, stated rather than assumed.

    Callers written before the return value existed return None. None is falsy,
    so they are treated as success — which is the pre-existing behaviour and the
    right default for a stub that cannot fail.
    """
    ctx = _Ctx(plan_failure='')
    ctx.start_navigation = lambda x, y: None
    resp = operator_command_logic(ctx, _request(), _response())
    assert resp.accepted is True
