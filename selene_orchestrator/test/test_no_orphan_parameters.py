"""Every declared ROS parameter must actually be read.

WHY THIS EXISTS. `resource_map_publish_rate` was declared in Phase 3, written
into orchestrator_params.yaml, documented in the PRD as FR-MAP-1(e)'s
"configurable rate (default 0.5 Hz)" — and never read. No timer was bound to
it, so the fused resource map was never published at all, and FR-MAP-4 (the
RViz2 overlay that would have consumed it) was recorded as descoped rather than
blocked. The requirement was not dropped by decision; it evaporated because
nothing connected the parameter to any behaviour and nothing noticed.

A declared-but-unread parameter is a specific, detectable smell: it looks like
a supported knob in the config file and in `ros2 param list`, an operator can
set it, and it does nothing. This test finds them by AST rather than by grep,
so a name in a comment or a docstring cannot mask one.

It is deliberately an allow-list, not a blanket ban. The name below is a
pre-existing orphan that this change does not fix; it is recorded here so it is
visible and counted, and so a NEW one fails the build.

THE LIST SHRANK ON 2026-07-31. It used to hold two names. `recharge_threshold`
was the other, annotated "the agent decides recharge locally (selene_agent
battery logic); the orchestrator declares a threshold it never applies" — an
accurate description of the orchestrator's half and a wrong assumption about
the agent's. The agent had NO battery logic on that path: ``_handle_working``
ended every task with an unconditional ``_start_recharge()``, so robots
recharged after every waypoint at 88-93% charge and the survey never finished.
The parameter has moved to the node that can act on it
(``selene_agent/agent_node.py``, passed by ``selene_agent/launch/agent.launch.py``)
and the recharge decision it names now exists. See deviation D-19.

That is the lesson this file was written for, arriving from the other
direction: an entry on an allow-list is a claim about the rest of the system,
and nothing was checking that claim.
"""

import ast
import pathlib

SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / 'selene_orchestrator' / 'orchestrator_node.py')

# Declared but never read, as of 2026-07-31:
#   fleet_state_publish_rate - the orchestrator has no fleet-state publisher at
#                              all; robot state flows agent -> dashboard.
# Removing a name from this set is a fix. Adding one needs a reason in writing.
KNOWN_ORPHANS = {
    'fleet_state_publish_rate',
}


def _string_arg(call):
    """First positional argument of a call, when it is a plain string."""
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _collect(tree):
    declared, read = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = _string_arg(node)
        if name is None:
            continue
        if node.func.attr == 'declare_parameter':
            declared.add(name)
        elif node.func.attr == 'get_parameter':
            read.add(name)
    return declared, read


def test_no_new_orphan_parameters():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    declared, read = _collect(tree)

    assert declared, 'no declare_parameter calls found — has the file moved?'

    orphans = declared - read
    unexpected = orphans - KNOWN_ORPHANS
    assert not unexpected, (
        'parameter(s) declared but never read: ' + ', '.join(sorted(unexpected))
        + '. A declared parameter that nothing reads is a knob that silently '
          'does nothing — see this file\'s docstring for how that lost '
          'FR-MAP-1(e) for two phases. Read it, or do not declare it.')


def test_resource_map_publish_rate_is_read():
    """The specific regression this whole exercise came from.

    Named separately from the allow-list check so that if someone ever removes
    the timer, the failure says which requirement broke rather than just
    reporting a count.
    """
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    declared, read = _collect(tree)
    assert 'resource_map_publish_rate' in declared
    assert 'resource_map_publish_rate' in read, (
        'resource_map_publish_rate is declared but not read: the fused '
        'resource map is not being published, so FR-MAP-1(e) is unmet and '
        'FR-MAP-4 has nothing to display.')


def test_known_orphans_are_still_orphans():
    """Keeps the allow-list honest.

    If one of these gets wired up, this fails and the name should be deleted
    from KNOWN_ORPHANS — otherwise the list rots into a permanent excuse.
    """
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    declared, read = _collect(tree)
    fixed = {n for n in KNOWN_ORPHANS if n in read}
    assert not fixed, (
        'these are now read and should be removed from KNOWN_ORPHANS: '
        + ', '.join(sorted(fixed)))
    missing = {n for n in KNOWN_ORPHANS if n not in declared}
    assert not missing, (
        'KNOWN_ORPHANS names a parameter that is no longer declared: '
        + ', '.join(sorted(missing)))
