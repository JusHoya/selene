"""The recharge decision — deviation D-19.

WHAT THIS PINS. Before 2026-07-31 ``agent_node._handle_working`` ended every
task, successful or failed, with

    self._fsm.handle_event(FSMEvent.TASK_COMPLETE)
    self._start_recharge()

with no battery test anywhere on that path. Measured live on ROS 2 Jazzy +
Gazebo the same day: scouts drove home and charged after every survey waypoint
at **88-93% battery**, were in RECHARGING for the majority of two runs, and
reached 155 map observations in ~10 minutes and 316 in ~21. The HTN's
``SelectSite`` cannot resolve until every survey waypoint is COMPLETE and no
excavate or haul exists until it does, so this defect alone is what kept the
D-06 material ledger structurally at zero in a live run.

Every test below fails against that code and passes against the fix, and the
two halves are covered separately on purpose:

* ``TestRechargeReason`` — the energy question, in ``EnergyManager``.
* ``TestSettleAfterTask`` / ``TestBeginRechargeCycle`` — what the agent DOES
  with the answer, in ``recharge_policy``, driven with spies exactly as
  ``test_agent_operator_callback.py`` drives ``operator_command_logic``.
* ``TestNotStrandingTheFleet`` — the guards that stop the fix trading a slow
  fleet for a fleet that parks itself in the field with a flat battery.
* ``TestScoutArithmetic`` — the numbers, re-derived from the shipped RCDL, so
  a change to ``selene_hal/config/scout.yaml`` has to be looked at rather than
  absorbed.

Nothing here was run against ROS. There is no ROS on this machine; see
``docs/phase5_deviation_register.md`` "Verification limits".
"""
from __future__ import annotations

import math
import os
import pathlib
import sys

import pytest
import yaml

# Make the agent package importable when running pytest from elsewhere.
_REPO_PKG_PARENT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..'),
)
if _REPO_PKG_PARENT not in sys.path:
    sys.path.insert(0, _REPO_PKG_PARENT)

from selene_hal.battery_interface import BatteryInterface     # noqa: E402
from selene_hal.data_types import BatteryState                # noqa: E402
from selene_agent.energy_manager import (                     # noqa: E402
    RECHARGE_BELOW_THRESHOLD,
    RECHARGE_CRITICAL,
    RECHARGE_RETURN_MARGIN,
    EnergyManager,
)
from selene_agent.fsm import AgentFSM, AgentState, FSMEvent   # noqa: E402
from selene_agent.recharge_policy import (                    # noqa: E402
    UNAFFORDABLE_PASSES_BEFORE_RECHARGE,
    _RechargeContext,
    begin_recharge_cycle_logic,
    settle_after_task_logic,
    should_recharge_after_refusals,
    validated_recharge_threshold,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

class _Battery(BatteryInterface):
    """Battery stub whose draws default to the shipped scout's RCDL."""

    def __init__(self, capacity_wh=50.0, charge_fraction=1.0,
                 idle_draw=10.0, locomotion_draw=150.0):
        self._capacity = capacity_wh
        self._charge = charge_fraction
        self._idle = idle_draw
        self._locomotion = locomotion_draw

    def get_state(self) -> BatteryState:
        return BatteryState(
            charge_fraction=self._charge,
            capacity_wh=self._capacity,
            remaining_wh=self._capacity * self._charge,
        )

    def get_capacity_wh(self) -> float:
        return self._capacity

    def get_idle_draw_w(self) -> float:
        return self._idle

    def get_locomotion_draw_w(self) -> float:
        return self._locomotion

    def set_charge(self, fraction: float) -> None:
        self._charge = fraction


def _manager(charge=0.9, station=(-30.0, -100.0), threshold=0.30,
             capacity_wh=50.0):
    battery = _Battery(capacity_wh=capacity_wh, charge_fraction=charge)
    em = EnergyManager(
        battery,
        critical_threshold=0.15,
        recharge_target=0.90,
        recharge_station=station,
        recharge_threshold=threshold,
    )
    em.update(battery.get_state())
    return em, battery


class _AgentSpy:
    """The mutable agent state ``recharge_policy`` touches, and nothing else.

    Holds a REAL ``AgentFSM`` rather than a mirror of the transition table:
    the two new events D-19 adds are the thing under test, and a spy that
    reimplemented them would pass whether or not they exist.
    """

    def __init__(self, state=AgentState.IDLE, reason='', charge=0.9,
                 threshold=0.30, robot_id='scout_01'):
        self.fsm = AgentFSM(robot_id, logger=lambda _m: None)
        self._force_state(state)
        self.reason = reason
        self.charge = charge
        self.threshold = threshold
        self.robot_id = robot_id
        self.recharge_calls = 0
        self.aborts = 0
        self.logs: list[str] = []

    def _force_state(self, state):
        """Put the FSM into *state* without asserting a transition path."""
        self.fsm._state = state

    def context(self) -> _RechargeContext:
        return _RechargeContext(
            robot_id=self.robot_id,
            get_state=lambda: self.fsm.state,
            fire_event=self.fsm.handle_event,
            recharge_reason=lambda: self.reason,
            start_recharge=self._start_recharge,
            get_charge_fraction=lambda: self.charge,
            recharge_threshold=self.threshold,
            log_info=self.logs.append,
            abort_current_skill=self._abort,
        )

    def _start_recharge(self):
        self.recharge_calls += 1

    def _abort(self):
        self.aborts += 1


# --------------------------------------------------------------------------- #
#  The energy question                                                         #
# --------------------------------------------------------------------------- #

class TestRechargeReason:

    def test_a_healthy_robot_has_no_reason_to_recharge(self):
        """THE REGRESSION. 90% at the base station is not a reason to charge.

        This is the exact state the live fleet was in every time it drove home:
        a scout that had just finished a waypoint, near full, with the station
        within reach. The old code had no predicate at all, so there was
        nothing to return '' from.
        """
        em, _ = _manager(charge=0.90)
        assert em.recharge_reason((-30.0, -100.0)) == ''
        assert em.recharge_reason((-95.0, -170.0)) == ''

    def test_the_measured_live_charges_all_say_stay_out(self):
        """88-93%, the band actually observed on 2026-07-31."""
        for percent in (88, 89, 90, 91, 92, 93):
            em, _ = _manager(charge=percent / 100.0)
            assert em.recharge_reason((-95.0, -170.0)) == '', percent

    def test_below_the_floor_is_a_reason(self):
        em, _ = _manager(charge=0.30, threshold=0.30)
        assert em.recharge_reason((-30.0, -100.0)) == RECHARGE_BELOW_THRESHOLD

    def test_just_above_the_floor_is_not(self):
        em, _ = _manager(charge=0.3001, threshold=0.30)
        assert em.recharge_reason((-30.0, -100.0)) == ''

    def test_critical_outranks_the_floor(self):
        """Both tiers are true at 10%; the more urgent name is the one used."""
        em, _ = _manager(charge=0.10, threshold=0.30)
        assert em.recharge_reason((-30.0, -100.0)) == RECHARGE_CRITICAL

    def test_the_floor_is_a_floor_not_the_whole_policy(self):
        """A robot above the floor that cannot get home must still go home.

        The distance is the point: 40% of a 50 Wh scout is 20 Wh, and at
        0.0509 Wh/m that buys ~393 m of driving with the 1.10 margin applied.
        Put the station 900 m away and the flat percentage is a lie.
        """
        em, _ = _manager(charge=0.40, station=(900.0, 0.0), threshold=0.30)
        assert em.recharge_reason((0.0, 0.0)) == RECHARGE_RETURN_MARGIN

    def test_the_margin_tier_is_skipped_without_a_position(self):
        """Unreadable odom must not fabricate a distance.

        The floor still applies, so the robot is not left unprotected; what it
        must not do is guess how far it is from base and act on the guess.
        """
        em, _ = _manager(charge=0.40, station=(900.0, 0.0), threshold=0.30)
        assert em.recharge_reason(None) == ''
        em, _ = _manager(charge=0.20, station=(900.0, 0.0), threshold=0.30)
        assert em.recharge_reason(None) == RECHARGE_BELOW_THRESHOLD

    def test_can_return_to_base_carries_the_safety_margin(self):
        """The 1.10 margin is the difference between the two assertions."""
        em, _ = _manager(charge=1.0, station=(0.0, 0.0))
        # 50 Wh / 0.0509259... Wh per m = 981.8 m of bare range.
        bare_range = em.get_remaining_wh() / em.compute_energy_cost_wh(1.0)
        assert em.can_return_to_base((bare_range * 0.9, 0.0)) is True
        assert em.can_return_to_base((bare_range * 0.999, 0.0)) is False


# --------------------------------------------------------------------------- #
#  What the agent does with the answer                                         #
# --------------------------------------------------------------------------- #

class TestSettleAfterTask:

    def test_a_full_robot_goes_back_to_idle_and_does_not_recharge(self):
        """THE REGRESSION, at the wiring level.

        The FSM starts in RETURNING because ``(WORKING, TASK_COMPLETE)`` put
        it there — that transition is not ours to change. The assertion is
        that the robot leaves it immediately and starts no RechargeSkill.
        """
        agent = _AgentSpy(state=AgentState.RETURNING, reason='', charge=0.91)
        acted = settle_after_task_logic(agent.context())
        assert acted == ''
        assert agent.fsm.state is AgentState.IDLE
        assert agent.recharge_calls == 0

    @pytest.mark.parametrize('reason', [
        RECHARGE_CRITICAL, RECHARGE_BELOW_THRESHOLD, RECHARGE_RETURN_MARGIN,
    ])
    def test_a_robot_that_needs_charge_still_gets_it(self, reason):
        """The other half: D-19 must not have removed recharging."""
        agent = _AgentSpy(state=AgentState.RETURNING, reason=reason,
                          charge=0.22)
        acted = settle_after_task_logic(agent.context())
        assert acted == reason
        assert agent.fsm.state is AgentState.RETURNING
        assert agent.recharge_calls == 1

    def test_returning_is_never_published(self):
        """RETURNING must not be observable by the 2 Hz state publisher.

        Both events fire inside one call, so there is no tick boundary between
        them. Asserted through the FSM's own transition log rather than by
        timing: WORKING -> RETURNING -> IDLE, with nothing in between that
        could be sampled.
        """
        agent = _AgentSpy(state=AgentState.WORKING, reason='', charge=0.91)
        agent.fsm.handle_event(FSMEvent.TASK_COMPLETE)
        settle_after_task_logic(agent.context())
        path = [(e['from_state'], e['event'], e['to_state'])
                for e in agent.fsm.get_transition_log()]
        assert path == [
            (AgentState.WORKING, FSMEvent.TASK_COMPLETE, AgentState.RETURNING),
            (AgentState.RETURNING, FSMEvent.RECHARGE_NOT_NEEDED,
             AgentState.IDLE),
        ]

    def test_the_decision_is_logged_either_way(self):
        """An operator reading the log must be able to see the choice."""
        stayed = _AgentSpy(state=AgentState.RETURNING, reason='', charge=0.91)
        settle_after_task_logic(stayed.context())
        assert 'staying in the field' in stayed.logs[0]
        assert '91.0%' in stayed.logs[0]

        went = _AgentSpy(state=AgentState.RETURNING,
                         reason=RECHARGE_BELOW_THRESHOLD, charge=0.28)
        settle_after_task_logic(went.context())
        assert 'returning to recharge' in went.logs[0]
        assert RECHARGE_BELOW_THRESHOLD in went.logs[0]


class TestBeginRechargeCycle:

    def test_an_idle_robot_is_sent_home(self):
        agent = _AgentSpy(state=AgentState.IDLE, charge=0.25)
        assert begin_recharge_cycle_logic(agent.context(), 'floor') is True
        assert agent.fsm.state is AgentState.RETURNING
        assert agent.recharge_calls == 1

    def test_a_working_robot_aborts_its_skill_first(self):
        """Order matters: a latched cmd_vel must not outlive the decision."""
        agent = _AgentSpy(state=AgentState.WORKING, charge=0.20)
        assert begin_recharge_cycle_logic(agent.context(), 'floor') is True
        assert agent.aborts == 1
        assert agent.fsm.state is AgentState.RETURNING

    @pytest.mark.parametrize('state', [
        AgentState.RETURNING, AgentState.RECHARGING,
        AgentState.ERROR, AgentState.OFFLINE,
    ])
    def test_states_with_no_transition_are_refused_not_raised(self, state):
        """``InvalidTransitionError`` out of a timer callback ends the node.

        ``AgentFSM.handle_event`` raises on an illegal transition, and every
        caller of this helper is a timer or a subscription callback. Refusing
        is the difference between a robot that declines to recharge and an
        agent process that exits.
        """
        agent = _AgentSpy(state=state, charge=0.10)
        assert begin_recharge_cycle_logic(agent.context(), 'floor') is False
        assert agent.fsm.state is state
        assert agent.recharge_calls == 0
        assert agent.aborts == 0


# --------------------------------------------------------------------------- #
#  Not trading a slow fleet for a stranded one                                 #
# --------------------------------------------------------------------------- #

class TestNotStrandingTheFleet:

    def test_refusals_below_the_bound_do_nothing(self):
        for passes in range(1, UNAFFORDABLE_PASSES_BEFORE_RECHARGE):
            assert should_recharge_after_refusals(
                passes, AgentState.IDLE, in_startup_grace=False) is False

    def test_enough_refusals_send_the_robot_home(self):
        assert should_recharge_after_refusals(
            UNAFFORDABLE_PASSES_BEFORE_RECHARGE, AgentState.IDLE,
            in_startup_grace=False) is True

    def test_the_startup_grace_suppresses_it(self):
        """The HAL reports 0% until DDS delivers the first battery sample.

        ``can_afford_task`` therefore refuses everything for the first few
        seconds. Without this guard the entire fleet drives to the charging
        station in the first second of every mission.
        """
        assert should_recharge_after_refusals(
            99, AgentState.IDLE, in_startup_grace=True) is False

    @pytest.mark.parametrize('state', [
        s for s in AgentState if s is not AgentState.IDLE
    ])
    def test_only_an_idle_robot_counts_as_stranded(self, state):
        assert should_recharge_after_refusals(
            99, state, in_startup_grace=False) is False

    def test_an_idle_robot_that_drains_below_the_floor_still_charges(self):
        """The slow path that catches everything the refusal counter misses.

        A robot resting IDLE in the field draws idle power. Once it crosses
        the floor, ``_handle_idle``'s check fires. This asserts the predicate
        that check reads, at the charge the drain reaches it at.
        """
        em, battery = _manager(charge=0.35, threshold=0.30)
        assert em.recharge_reason((-95.0, -170.0)) == ''
        battery.set_charge(0.29)
        em.update(battery.get_state())
        assert em.recharge_reason((-95.0, -170.0)) == RECHARGE_BELOW_THRESHOLD


class TestThresholdValidation:

    def test_a_sane_threshold_passes_through_silently(self):
        value, complaint = validated_recharge_threshold(0.30, 0.15, 0.90)
        assert value == 0.30
        assert complaint == ''

    def test_a_threshold_at_or_above_the_target_is_clamped(self):
        """Otherwise a freshly-charged robot immediately wants to charge."""
        value, complaint = validated_recharge_threshold(0.95, 0.15, 0.90)
        assert value == pytest.approx(0.85)
        assert 'busy loop' in complaint
        value, complaint = validated_recharge_threshold(0.90, 0.15, 0.90)
        assert value == pytest.approx(0.85)
        assert complaint

    def test_a_threshold_below_critical_is_allowed_but_complained_about(self):
        """Emergency-only recharging is a policy, not a fault — but say so."""
        value, complaint = validated_recharge_threshold(0.10, 0.15, 0.90)
        assert value == 0.10
        assert 'unreachable' in complaint

    @pytest.mark.parametrize('bad', [0.0, -0.5, float('nan'), float('inf')])
    def test_nonsense_falls_back_to_the_declared_default(self, bad):
        value, complaint = validated_recharge_threshold(bad, 0.15, 0.90)
        assert value == 0.30
        assert complaint


# --------------------------------------------------------------------------- #
#  The FSM half                                                                #
# --------------------------------------------------------------------------- #

class TestNewFsmTransitions:

    def test_recharge_not_needed_only_leaves_returning(self):
        fsm = AgentFSM('scout_01', logger=lambda _m: None)
        fsm._state = AgentState.RETURNING
        assert fsm.handle_event(FSMEvent.RECHARGE_NOT_NEEDED) is AgentState.IDLE

    @pytest.mark.parametrize('state', [
        s for s in AgentState if s is not AgentState.RETURNING
    ])
    def test_recharge_not_needed_is_illegal_everywhere_else(self, state):
        from selene_agent.fsm import InvalidTransitionError
        fsm = AgentFSM('scout_01', logger=lambda _m: None)
        fsm._state = state
        with pytest.raises(InvalidTransitionError):
            fsm.handle_event(FSMEvent.RECHARGE_NOT_NEEDED)

    @pytest.mark.parametrize('state', [
        AgentState.IDLE, AgentState.BIDDING, AgentState.ASSIGNED,
        AgentState.NAVIGATING, AgentState.WORKING,
    ])
    def test_recharge_needed_reaches_returning(self, state):
        fsm = AgentFSM('scout_01', logger=lambda _m: None)
        fsm._state = state
        assert fsm.handle_event(FSMEvent.RECHARGE_NEEDED) \
            is AgentState.RETURNING

    @pytest.mark.parametrize('state', [
        AgentState.RETURNING, AgentState.RECHARGING,
        AgentState.ERROR, AgentState.OFFLINE,
    ])
    def test_recharge_needed_is_illegal_where_it_would_be_wrong(self, state):
        from selene_agent.fsm import InvalidTransitionError
        fsm = AgentFSM('scout_01', logger=lambda _m: None)
        fsm._state = state
        with pytest.raises(InvalidTransitionError):
            fsm.handle_event(FSMEvent.RECHARGE_NEEDED)


# --------------------------------------------------------------------------- #
#  The numbers, from the shipped configuration                                 #
# --------------------------------------------------------------------------- #

class TestScoutArithmetic:
    """Re-derives the policy's headroom from ``selene_hal/config/scout.yaml``.

    Not a duplicate of the tests above: those fix the SHAPE of the policy, this
    one fixes the SCALE, so that changing a scout's battery or draw has to be
    looked at rather than silently absorbed. Same idea as
    ``test_haul_against_fill_model.py`` reading capacities out of the RCDL.
    """

    @staticmethod
    def _scout_manager(charge, station):
        rcdl = yaml.safe_load(
            (REPO / 'selene_hal' / 'config' / 'scout.yaml')
            .read_text(encoding='utf-8'))
        bat = rcdl['battery']
        battery = _Battery(
            capacity_wh=float(bat['capacity']),
            charge_fraction=charge,
            idle_draw=float(bat['idle_draw']),
            locomotion_draw=float(bat['locomotion_draw']),
        )
        em = EnergyManager(
            battery, critical_threshold=0.15, recharge_target=0.90,
            recharge_station=station, recharge_threshold=0.30,
        )
        em.update(battery.get_state())
        return em

    def test_the_floor_covers_the_whole_survey_zone(self):
        """The floor must not be the tier that strands a scout.

        The furthest task seen in the live log was (-95, -170); the agent's
        default recharge station is (-30, -100), 95.4 m away. At the 30% floor
        a scout holds 15 Wh, and the return leg from there costs 5.35 Wh with
        the 1.10 margin applied -- a 2.80x reserve. So on the shipped geometry
        the flat floor always fires before the margin tier, which is what makes
        it a floor rather than a second opinion.
        """
        em = self._scout_manager(charge=0.30, station=(-30.0, -100.0))
        distance = em.get_distance_to_base((-95.0, -170.0))
        assert distance == pytest.approx(math.hypot(65.0, 70.0), rel=1e-9)
        cost = em.compute_energy_cost_wh(distance) * 1.10
        assert cost == pytest.approx(5.35, abs=0.05)
        assert em.get_remaining_wh() == pytest.approx(15.0)
        assert em.can_return_to_base((-95.0, -170.0)) is True

    def test_the_reserve_at_the_floor_is_measured_not_assumed(self):
        """Stated as a ratio so a smaller battery fails this rather than a run.

        2.80x on the shipped scout. The bound is 2.0 rather than 2.79 because
        this is asserting that the floor has real headroom over the worst
        observed geometry, not pinning a figure to two decimal places; the
        exact number is in the test above it.
        """
        em = self._scout_manager(charge=0.30, station=(-30.0, -100.0))
        cost = em.compute_energy_cost_wh(
            em.get_distance_to_base((-95.0, -170.0))) * 1.10
        assert em.get_remaining_wh() / cost == pytest.approx(2.80, abs=0.01)
        assert em.get_remaining_wh() / cost > 2.0
