"""Pure-Python operator command logic for the SELENE agent.

The per-robot ``/{robot_id}/set_command`` ROS 2 service callback in
``agent_node.AgentNode`` delegates to ``operator_command_logic`` below.
Keeping the decision tree in its own module — with **zero** ROS,
selene_hal, or skill imports — lets unit tests drive every code path
with plain MagicMocks instead of standing up a real ROS node.

The accompanying ``_OperatorCommandContext`` dataclass holds the
callables the helper needs (FSM accessors, current-skill accessors,
publisher hooks, etc.) so production callers and tests share the same
dispatch shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from selene_agent.fsm import AgentState, FSMEvent


VALID_OPERATOR_COMMANDS = ('cancel_task', 'send_to_location', 'force_recharge')


@dataclass
class _OperatorCommandContext:
    """Injected dependencies for ``operator_command_logic``.

    Every interaction the helper has with agent state goes through one
    of these callables, so unit tests can substitute spies for the FSM,
    skill, navigator, bid publisher, and recharge starter without
    importing the rest of ``agent_node``.
    """
    robot_id: str
    get_state: Callable[[], AgentState]
    fire_event: Callable[[FSMEvent], None]
    get_current_skill: Callable[[], Any]
    set_current_skill: Callable[[Any], None]
    set_current_task_id: Callable[[str], None]
    get_pending_task_id: Callable[[], str]
    set_pending_task_id: Callable[[str], None]
    publish_bid_withdrawal: Callable[[str, str], None]
    start_navigation: Callable[[float, float], None]
    set_operator_target: Callable[[Optional[tuple]], None]
    start_recharge: Callable[[], None]
    get_last_seq: Callable[[], int]
    set_last_seq: Callable[[int], None]
    log_warn: Callable[[str], None]


def operator_command_logic(ctx: _OperatorCommandContext, request, response):
    """Pure decision tree for the per-agent SetRobotCommand handler.

    Decision order:
        1. Idempotent dedupe via ``request.sequence``.
        2. Reject if the agent is OFFLINE.
        3. Reject GOTO/RECHARGE if the agent is in ERROR (cancel still ok).
        4. Reject unknown commands up front so we never abort skills for
           a bogus request.
        5. Withdraw any pending bid (BIDDING state) so the orchestrator
           does not hang waiting for a winner.
        6. Abort the current skill, mirroring the critical-battery
           pattern from ``AgentNode._tick`` so actuators are torn down
           cleanly.
        7. Dispatch the FSM event + start the appropriate side-effect
           (navigation or recharge) and bump the dedupe counter.
    """
    # 1. Idempotent dedupe.
    if request.sequence <= ctx.get_last_seq():
        response.accepted = True
        response.reason = 'duplicate_sequence'
        return response

    state = ctx.get_state()

    # 2. Reject if OFFLINE.
    if state == AgentState.OFFLINE:
        response.accepted = False
        response.reason = f'agent in {state.value}'
        return response

    # 3. Reject GOTO/RECHARGE in ERROR. Cancel is still allowed so the
    #    operator can clear the fault back to IDLE.
    if state == AgentState.ERROR and request.command != 'cancel_task':
        response.accepted = False
        response.reason = 'agent in ERROR, only cancel_task allowed'
        return response

    # 4. Validate command BEFORE tearing down skills, so a typo never
    #    causes the agent to silently abort its current work.
    if request.command not in VALID_OPERATOR_COMMANDS:
        response.accepted = False
        response.reason = f"unknown command '{request.command}'"
        return response

    ctx.log_warn(
        f'[{ctx.robot_id}] Operator command: {request.command} '
        f'(seq={request.sequence})'
    )

    # 5. Withdraw any pending bid before changing state.
    if state == AgentState.BIDDING:
        pending = ctx.get_pending_task_id()
        if pending:
            ctx.publish_bid_withdrawal(pending, ctx.robot_id)
            ctx.set_pending_task_id('')

    # 6. Abort the current skill (mirror critical-battery pattern from
    #    AgentNode._tick at agent_node.py:192-195).
    skill = ctx.get_current_skill()
    if skill is not None and skill.is_running():
        skill.abort()
    ctx.set_current_skill(None)
    ctx.set_current_task_id('')

    # 7. Dispatch on command.
    if request.command == 'cancel_task':
        ctx.fire_event(FSMEvent.OPERATOR_CANCEL)
    elif request.command == 'send_to_location':
        # Pseudo-task — does NOT enter the orchestrator task queue. The
        # ``override_goto_<seq>`` task_id lets the dashboard render a
        # label and lets ``AgentNode._handle_navigating`` recognise the
        # special completion path that returns to IDLE on arrival.
        ctx.set_current_task_id(f'override_goto_{request.sequence}')
        target_x = float(request.target.x)
        target_y = float(request.target.y)
        ctx.set_operator_target((target_x, target_y))
        ctx.fire_event(FSMEvent.OPERATOR_GOTO)
        ctx.start_navigation(target_x, target_y)
    elif request.command == 'force_recharge':
        ctx.fire_event(FSMEvent.OPERATOR_RECHARGE)
        ctx.start_recharge()

    ctx.set_last_seq(int(request.sequence))
    response.accepted = True
    response.reason = ''
    return response
