"""The state publisher's wiring, read as source -- deviations D-31 and D-34.

WHY THIS FILE IS AN AST TEST AND NOT A UNIT TEST. ``agent_node.py`` imports
``rclpy`` at ``:26`` and ``selene_msgs``/``geometry_msgs``/``nav_msgs`` at
``:32-36``, all at module scope, so it cannot be imported at all in the
pure-Python lanes that produce this repository's test baselines -- and no file
under ``selene_agent/test`` imports it today. The alternative idiom this
repository already uses is to read the module as TEXT: ``ast``-parsing a
source file is how ``selene_orchestrator/test/test_no_orphan_parameters.py``
(``:36``, ``:61-73``) catches a declared-but-unread parameter, and how
``selene_agent/test/test_haul_pickup_standoff.py`` (``:52-57``) keeps two
constants in two packages from drifting apart. This file follows that idiom.

WHAT IT IS FOR. Both halves of this change are wiring, and this repository has
shipped a hook nothing calls **five** times (``AdaptiveSurveyPlanner``,
``MaterialInventory``'s writers, ``resource_map_publish_rate``,
``recharge_threshold``, ``navigation.max_traversable_slope_deg``). A green
``test_fsm_transition_observer.py`` proves the observer mechanism works; it
proves nothing whatever about the node calling it. That is what is asserted
here.

WHAT IT CANNOT DO. It reads structure, not behaviour. It cannot tell you a
message reached DDS, that the type hash matches a rebuilt orchestrator, or
that a real robot ever published ``pose_valid=false``. Those are live-run
claims and this file does not make them.

MUTATIONS RUN AGAINST THIS FILE (house rule 2), each applied to
``agent_node.py``, the test run, then reverted:

* delete ``self._fsm.set_transition_observer(self._on_fsm_transition)``
  -> ``test_the_transition_observer_is_actually_wired_up`` FAILS;
* move that call above ``self._state_pub = ...``
  -> ``test_the_observer_is_attached_after_everything_it_reads`` FAILS;
* replace ``msg.pose_valid = bool(odom.is_valid)`` with
  ``msg.pose_valid = True`` -> ``test_pose_valid_comes_from_the_sensor_flag``
  FAILS;
* delete the ``msg.pose_valid`` assignment entirely
  -> ``test_the_state_message_reports_pose_validity`` FAILS.
"""

from __future__ import annotations

import ast
import os

import pytest


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
AGENT_NODE_PY = os.path.join(
    REPO, 'selene_agent', 'selene_agent', 'agent_node.py')
ROBOT_STATE_MSG = os.path.join(REPO, 'selene_msgs', 'msg', 'RobotState.msg')


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _tree():
    with open(AGENT_NODE_PY, 'r', encoding='utf-8') as handle:
        return ast.parse(handle.read())


def _agent_node_class(tree):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'AgentNode':
            return node
    raise AssertionError(
        'class AgentNode not found in agent_node.py -- has it moved?')


def _method(tree, name):
    cls = _agent_node_class(tree)
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'AgentNode.{name} not found in agent_node.py')


def _dotted(node):
    """Render ``self._state_pub.publish`` style chains, else ''."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return '.'.join(reversed(parts))
    return ''


def _calls(scope):
    """``[(dotted_name, Call), ...]`` for every call inside *scope*."""
    found = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name:
                found.append((name, node))
    return found


def _call_names(scope):
    return [name for name, _ in _calls(scope)]


def _assignments_to(scope, dotted):
    """Every ``ast.Assign`` in *scope* whose target renders as *dotted*."""
    found = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if _dotted(target) == dotted:
                found.append(node)
    return found


# ---------------------------------------------------------------------------
# D-31 -- the message can say "this pose is not a measurement"
# ---------------------------------------------------------------------------

def _msg_fields():
    """``[(type, name), ...]`` for RobotState.msg, comments and blanks out."""
    fields = []
    with open(ROBOT_STATE_MSG, 'r', encoding='utf-8') as handle:
        for raw in handle:
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            assert len(parts) >= 2, f'unparsable RobotState.msg line: {raw!r}'
            fields.append((parts[0], parts[1]))
    return fields


def test_robot_state_carries_pose_valid_as_a_trailing_bool():
    """Contract C1: ``bool pose_valid``, appended at the END.

    Trailing matters twice over. A field appended at the end is the least
    disruptive change to the wire format, and ``bool`` default-initialises to
    ``false``, which is the fail-safe direction: a publisher that has not been
    updated reports "no fix" rather than a confident fabricated origin. See
    the field's own comment for what that default costs.
    """
    fields = _msg_fields()
    names = [name for _, name in fields]
    assert 'pose_valid' in names, (
        'RobotState.msg has no pose_valid field, so a consumer cannot tell a '
        'fabricated (0, 0) from a real position -- which is D-31')
    assert fields[-1] == ('bool', 'pose_valid'), (
        f'pose_valid must be the trailing field and of type bool; the message '
        f'ends with {fields[-1]}')


def test_the_state_message_reports_pose_validity():
    """``_build_state_msg`` sets ``msg.pose_valid``.

    FAILS WITHOUT THE FIX: the assignment does not exist.
    """
    build = _method(_tree(), '_build_state_msg')
    assigns = _assignments_to(build, 'msg.pose_valid')
    assert len(assigns) == 1, (
        f'expected exactly one msg.pose_valid assignment in '
        f'_build_state_msg, found {len(assigns)}')


def test_pose_valid_comes_from_the_sensor_flag():
    """It is derived from the odometry reading, not asserted.

    FAILS WITHOUT THE FIX, and fails again on the obvious wrong fix: a
    hardcoded ``msg.pose_valid = True`` reproduces D-31 exactly, because
    ``GazeboOdometrySensor.read()`` never raises and its pre-first-message
    cache is a perfectly well-formed ``OdometryReading`` at the origin.
    """
    build = _method(_tree(), '_build_state_msg')
    assign = _assignments_to(build, 'msg.pose_valid')[0]

    attrs = {node.attr for node in ast.walk(assign.value)
             if isinstance(node, ast.Attribute)}
    assert 'is_valid' in attrs, (
        'msg.pose_valid must be derived from the OdometryReading.is_valid '
        'flag; anything else is a claim rather than a measurement')

    constants = {node.value for node in ast.walk(assign.value)
                 if isinstance(node, ast.Constant)}
    assert True not in constants, (
        'msg.pose_valid is being assigned a literal True somewhere in its '
        'expression -- that is D-31 with an extra step')


def test_pose_valid_is_read_next_to_the_pose_it_qualifies():
    """The flag and the coordinates come from ONE odometry read.

    Two separate ``read()`` calls could disagree: the HAL caches the last
    message and a DDS callback can replace it between them, so the flag would
    describe a reading the pose did not come from. They share a call today and
    this pins that.
    """
    build = _method(_tree(), '_build_state_msg')
    reads = [
        node for node in ast.walk(build)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'read'
        and isinstance(node.func.value, ast.Call)
        and _dotted(node.func.value.func) == 'self._hal.get_sensor'
    ]
    assert len(reads) == 1, (
        f'_build_state_msg should read the odometry sensor exactly once; '
        f'found {len(reads)} self._hal.get_sensor(...).read() calls')


def test_the_odometry_cache_is_an_invalid_origin_and_says_so_deliberately():
    """The premise of the whole fix, pinned in selene_hal's own type.

    CHARACTERIZATION PIN, not a regression test: it passes on the unmodified
    tree. It is here because every comment in this change rests on what an
    un-populated ``OdometryReading`` contains, and a default that changed
    silently would make those comments lies while every other test stayed
    green.

    IT ALSO CORRECTS A CLAIM THE DIAGNOSIS MADE LOOSELY. The D-31 write-up
    says the sensor "returns a cached OdometryReading defaulting to
    is_valid=False". It does not: ``SensorReading.is_valid`` DEFAULTS TO TRUE
    (``selene_hal/selene_hal/data_types.py:39``), and
    ``GazeboOdometrySensor.__init__`` passes ``is_valid=False`` explicitly
    (``gazebo_hal.py:357-359``). The distinction matters -- it means any
    future reading built without that argument is born claiming to be valid,
    so the safe direction on the HAL side is a decision that has to keep being
    made, not something the language provides. Both facts are asserted below.

    Guarded with ``importorskip`` because ``selene_hal`` is a different
    package: an unguarded cross-package import is exactly what turned the
    two-package gate lane red in D-36.
    """
    data_types = pytest.importorskip('selene_hal.data_types')

    # What the Gazebo odometry sensor actually caches before its first message.
    cached = data_types.OdometryReading(sensor_name='odometry', is_valid=False)
    assert cached.is_valid is False
    assert (cached.x, cached.y, cached.theta) == (0.0, 0.0, 0.0), (
        'the fabricated startup pose is the origin; if this stops being '
        '(0, 0) the D-31 write-up needs its numbers redone')

    # And the trap: the bare default claims validity.
    assert data_types.OdometryReading().is_valid is True, (
        'SensorReading.is_valid no longer defaults to True -- update the '
        'comments in RobotState.msg and agent_node._build_state_msg, which '
        'say it does')


# ---------------------------------------------------------------------------
# D-34 -- the transition observer is actually called
# ---------------------------------------------------------------------------

def test_the_transition_observer_is_actually_wired_up():
    """``AgentNode`` installs ``_on_fsm_transition`` on its FSM.

    THIS IS THE ANTI-"WIRED BUT NEVER CALLED" TEST. Without it, D-34's fix is
    a hook with green unit tests and zero call sites -- the sixth instance of
    the pattern that has cost this repository five register entries.

    FAILS WITHOUT THE FIX: no ``set_transition_observer`` call exists.
    """
    tree = _tree()
    init = _method(tree, '__init__')

    wirings = [call for name, call in _calls(init)
               if name == 'self._fsm.set_transition_observer']
    assert len(wirings) == 1, (
        f'expected exactly one self._fsm.set_transition_observer(...) call in '
        f'AgentNode.__init__, found {len(wirings)} -- a transition observer '
        f'that is never installed publishes nothing')

    bound = wirings[0].args
    assert len(bound) == 1 and _dotted(bound[0]) == 'self._on_fsm_transition', (
        'the observer must be AgentNode._on_fsm_transition; found '
        f'{[_dotted(a) for a in bound]}')

    # And that method must actually publish, or the wiring is decorative.
    handler = _method(tree, '_on_fsm_transition')
    assert 'self._state_pub.publish' in _call_names(handler), (
        '_on_fsm_transition does not publish on self._state_pub, so the '
        'transition still never reaches the wire')


def test_the_observer_is_attached_after_everything_it_reads():
    """Wiring order, made executable rather than left as a comment.

    ``_on_fsm_transition`` -> ``_build_state_msg`` reads ``self._state_pub``,
    ``self._current_skill`` and ``self._current_task_id``. Installing the
    observer at the ``AgentFSM(...)`` construction site -- which is where the
    obvious implementation puts it -- precedes all three, so any transition
    fired during the remainder of ``__init__`` raises ``AttributeError`` out
    of a constructor.

    FAILS if the wiring is moved back up to the constructor.
    """
    tree = _tree()
    init = _method(tree, '__init__')

    wiring = [call for name, call in _calls(init)
              if name == 'self._fsm.set_transition_observer'][0]

    for attribute in ('self._state_pub', 'self._current_skill',
                      'self._current_task_id'):
        assigns = _assignments_to(init, attribute)
        assert assigns, f'{attribute} is not assigned in AgentNode.__init__'
        first = min(node.lineno for node in assigns)
        assert wiring.lineno > first, (
            f'the transition observer is installed at line {wiring.lineno}, '
            f'before {attribute} is set at line {first}. A transition fired '
            f'between those two lines raises AttributeError inside a '
            f'constructor.')


def test_the_fsm_is_not_constructed_with_a_live_observer():
    """The constructor argument exists, but the node must not use it.

    Same defect as above from the other side: ``AgentFSM(...)`` is built ~40
    lines before the publisher exists, so passing ``on_transition`` there
    reintroduces exactly the ordering hazard the setter was added to avoid.
    """
    init = _method(_tree(), '__init__')
    constructions = [call for name, call in _calls(init) if name == 'AgentFSM']
    assert len(constructions) == 1, 'expected one AgentFSM(...) construction'
    keywords = {kw.arg for kw in constructions[0].keywords}
    assert 'on_transition' not in keywords, (
        'AgentNode must attach its observer with set_transition_observer '
        'AFTER the publisher block, not at the AgentFSM construction site')


def test_the_planned_path_does_not_ride_on_every_transition():
    """``publish_path`` stays on the 0.5 s timer.

    A ``nav_msgs/Path`` is large and carries no edge information; multiplying
    it by the transition rate buys nothing. Splitting ``_publish_state`` into
    a builder and a publisher is what makes this separable, so the split is
    asserted too.
    """
    tree = _tree()
    build = _method(tree, '_build_state_msg')
    timer = _method(tree, '_publish_state')
    handler = _method(tree, '_on_fsm_transition')

    build_calls = _call_names(build)
    assert 'self._state_pub.publish' not in build_calls, (
        '_build_state_msg must build, not publish')
    assert 'self._navigator.publish_path' not in build_calls

    timer_calls = _call_names(timer)
    assert 'self._build_state_msg' in timer_calls, (
        'the timer and the transition handler must share one message '
        'definition, or the two paths drift apart')
    assert 'self._state_pub.publish' in timer_calls
    assert 'self._navigator.publish_path' in timer_calls, (
        'the 2 Hz timer is still the only publisher of the planned path')

    assert 'self._navigator.publish_path' not in _call_names(handler), (
        'the planned path must not be republished on every FSM transition')


def test_assignment_fields_are_stored_before_the_auction_won_event():
    """D-34 A3: the ASSIGNED sample must carry the task it is about.

    ``AUCTION_WON`` used to fire before ``self._current_task_id`` was stored.
    That was invisible while state was sampled at 2 Hz; with an on-change
    publish it puts an ASSIGNED message on the wire carrying the previous
    task's id until the next timer tick corrects it.

    FAILS if the event is moved back above the stores.
    """
    handler = _method(_tree(), '_on_task_assigned')

    task_id_stores = _assignments_to(handler, 'self._current_task_id')
    assert task_id_stores, (
        '_on_task_assigned no longer stores self._current_task_id')
    store_line = max(node.lineno for node in task_id_stores)

    won_calls = [
        call for name, call in _calls(handler)
        if name.endswith('handle_event')
        and any(_dotted(arg) == 'FSMEvent.AUCTION_WON' for arg in call.args)
    ]
    assert len(won_calls) == 1, (
        f'expected exactly one AUCTION_WON handle_event call in '
        f'_on_task_assigned, found {len(won_calls)}')
    assert won_calls[0].lineno > store_line, (
        f'AUCTION_WON fires at line {won_calls[0].lineno}, before the '
        f'assignment fields are stored at line {store_line} -- so the '
        f'ASSIGNED message published by that transition carries a stale '
        f'current_task_id')
