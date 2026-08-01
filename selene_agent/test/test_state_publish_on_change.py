"""The IDLE hand-off the 2 Hz sampler could not see -- deviation D-34.

THE MEASURED EVENT. From the two exit-gate runs' launch logs, quoted in
``docs/phase5_deviation_register.md`` D-34 and D-04::

    [scout_01] NAVIGATING --(OPERATOR_CANCEL)--> IDLE
    [scout_01] IDLE --(TASK_ANNOUNCED)--> BIDDING
    [scout_01] Bid on manual_0000: score=0.915 eta=53.8s
    [orchestrator_node] Auction manual_0000: winner=scout_01 score=0.915 bids=1
    [scout_01] BIDDING --(AUCTION_WON)--> ASSIGNED

    | run | -> IDLE     | -> BIDDING   | IDLE lasted |
    |-----|-------------|--------------|-------------|
    | 1   | 131.418348  | 131.665462   | 0.247 s     |
    | 2   | 496.478300  | 496.779290   | 0.301 s     |

The system did precisely what PRD rows 3 and 4 assert. The gate's probe polled
``latest_state`` on the 0.5 s ``/{rid}/state`` topic, never saw IDLE, and
returned SKIP on both runs.

WHAT THIS FILE DOES, in one test per claim, and what each half is worth:

* the SAMPLER half is arithmetic over the measured timeline. It passes with or
  without the fix -- it is a derivation of why the miss happened, not a
  regression assertion, and it is here because the two halves are only
  meaningful side by side;
* the OBSERVER half drives the REAL ``AgentFSM`` through the real sequence and
  asserts IDLE is emitted. It fails without the fix at
  ``set_transition_observer`` (``AttributeError``).

ROS-free: this imports ``selene_agent.fsm`` and nothing else. ``agent_node``
imports ``rclpy`` and ``selene_msgs`` at module scope (``:26``, ``:32-36``) and
cannot be imported in the Windows/pure-Python lanes at all -- its half of the
change is pinned structurally by ``test_agent_state_publish_wiring.py``.
"""

from __future__ import annotations

from selene_agent.fsm import AgentFSM, FSMEvent


#: The run-1 IDLE window, from the register's table above. Wall-clock seconds
#: as the launch log printed them.
IDLE_ENTERED_S = 131.418348
IDLE_LEFT_S = 131.665462
IDLE_WINDOW_S = IDLE_LEFT_S - IDLE_ENTERED_S      # 0.247114
STATE_PERIOD_S = 0.5                              # agent_node.py:315


def _sampled_states(timeline, first_sample_s, period_s):
    """States a periodic sampler of *period_s* would record from *timeline*.

    *timeline* is ``[(t_enter, state), ...]`` sorted by time; the sampler
    reports whichever state is current at each sample instant, which is
    exactly what a level-signal publisher on a timer does.
    """
    out = []
    t = first_sample_s
    end = timeline[-1][0]
    while t <= end:
        current = timeline[0][1]
        for t_enter, state in timeline:
            if t_enter <= t:
                current = state
            else:
                break
        out.append(current)
        t += period_s
    return out


def _measured_timeline():
    return [
        (IDLE_ENTERED_S - 1.0, 'NAVIGATING'),
        (IDLE_ENTERED_S, 'IDLE'),
        (IDLE_LEFT_S, 'BIDDING'),
        (IDLE_LEFT_S + 1.0, 'BIDDING'),
    ]


# ---------------------------------------------------------------------------
# The sampler half -- a derivation, NOT a regression test
# ---------------------------------------------------------------------------

def test_a_half_second_sampler_misses_the_measured_idle_window():
    """Half the phases of a 0.5 s sampler never see a 0.247 s state.

    NO FIX IS BEING TESTED HERE. This is the arithmetic behind the SKIP, kept
    executable so the claim "the instrument was wrong, not the system" is
    checkable rather than asserted. It passes on the unmodified tree.

    The miss fraction is DERIVED, not tuned: a periodic sampler of period T
    lands inside a window of length W < T for exactly W/T of its phases, so it
    misses for 1 - W/T. With the register's measured W = 0.247114 s and the
    agent's T = 0.5 s that is 50.6% of phases -- which is also why the register
    is careful to say that missing on BOTH runs is a phase-locking hypothesis
    (n = 2), not a measurement.
    """
    timeline = _measured_timeline()
    phases = [i / 1000.0 * STATE_PERIOD_S for i in range(1000)]

    missed = 0
    for phase in phases:
        first = timeline[0][0] + phase
        if 'IDLE' not in _sampled_states(timeline, first, STATE_PERIOD_S):
            missed += 1

    expected_miss_fraction = 1.0 - IDLE_WINDOW_S / STATE_PERIOD_S
    assert abs(missed / len(phases) - expected_miss_fraction) < 0.01, (
        f'a {STATE_PERIOD_S} s sampler should miss a {IDLE_WINDOW_S:.6f} s '
        f'state for {expected_miss_fraction:.1%} of phases; measured '
        f'{missed / len(phases):.1%} over {len(phases)} phases'
    )
    assert missed > 0, (
        'if no phase misses the window there was no aliasing to fix'
    )


def test_no_sampling_period_above_the_window_is_safe():
    """Shortening the timer is the same defect at higher cost.

    Any period longer than the shorter measured window (0.247 s) has phases
    that miss it, so "sample faster" only moves the threshold. That is the
    reason the fix publishes the edge instead of raising the rate, and it is
    worth having executable because "just make the timer 10 Hz" is the first
    thing a reader will propose.
    """
    timeline = _measured_timeline()
    for period in (0.5, 0.4, 0.3, 0.25):
        missed = sum(
            1 for i in range(200)
            if 'IDLE' not in _sampled_states(
                timeline, timeline[0][0] + i / 200.0 * period, period)
        )
        if period > IDLE_WINDOW_S:
            assert missed > 0, (
                f'a {period} s sampler must have phases that miss a '
                f'{IDLE_WINDOW_S:.6f} s window'
            )


# ---------------------------------------------------------------------------
# The observer half -- this is the regression test
# ---------------------------------------------------------------------------

def test_the_transition_observer_emits_the_idle_handoff():
    """The real FSM, the real sequence: IDLE is on the wire.

    FAILS WITHOUT THE FIX: ``AgentFSM`` had no ``set_transition_observer``, so
    this raises ``AttributeError`` on the third line.
    """
    emitted: list[str] = []
    fsm = AgentFSM('scout_01', logger=lambda msg: None)
    fsm.set_transition_observer(lambda p, e, n: emitted.append(fsm.state.value))

    # NAVIGATING, as the robot was when the operator cancelled.
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    emitted.clear()

    fsm.handle_event(FSMEvent.OPERATOR_CANCEL)   # -> IDLE
    fsm.handle_event(FSMEvent.TASK_ANNOUNCED)    # -> BIDDING
    fsm.handle_event(FSMEvent.AUCTION_WON)       # -> ASSIGNED

    assert emitted == ['IDLE', 'BIDDING', 'ASSIGNED']
    assert 'IDLE' in emitted, (
        'the state that cost PRD rows 3 and 4 two SKIPs must reach the wire'
    )


def test_the_observer_emission_does_not_depend_on_timing():
    """No phase, no period, no sleep: an edge is emitted because it happened.

    This is the whole difference from the sampler half above. The emitted
    sequence is a function of the transitions alone, so the 0.247 s window is
    represented whether it lasted 0.247 s or 0.247 ms.
    """
    emitted: list[str] = []
    fsm = AgentFSM('scout_01', logger=lambda msg: None)
    fsm.set_transition_observer(lambda p, e, n: emitted.append(n.value))

    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    # The D-19 in-field settle: two transitions in one 10 Hz tick, so RETURNING
    # never lasted a full tick let alone a sampling period.
    fsm.handle_event(FSMEvent.TASK_COMPLETE)
    fsm.handle_event(FSMEvent.RECHARGE_NOT_NEEDED)

    assert emitted == ['NAVIGATING', 'WORKING', 'RETURNING', 'IDLE']
    assert 'RETURNING' in emitted, (
        'fsm.py and recharge_policy.py used to document RETURNING as '
        'unobservable; both comments were corrected in this change and this '
        'is what makes the correction true'
    )


def test_transition_count_per_task_bounds_the_added_message_rate():
    """The added rate is one message per transition -- counted, not guessed.

    STRUCTURAL, NOT MEASURED. It counts the transitions the real FSM makes on
    the two task shapes the fleet actually runs. It cannot tell you how many
    tasks a run performs; the register publishes no transition count and the
    launch log's ``--(event)-->`` lines are where the real number comes from.
    Recorded here so the bound in ``AgentNode._on_fsm_transition``'s docstring
    is checkable rather than asserted.
    """
    def count(events):
        seen = []
        fsm = AgentFSM('rate_bot', logger=lambda m: None)
        fsm.set_transition_observer(lambda p, e, n: seen.append(n))
        for event in events:
            fsm.handle_event(event)
        return len(seen)

    in_field_task = count([
        FSMEvent.TASK_ANNOUNCED, FSMEvent.AUCTION_WON,
        FSMEvent.WAYPOINT_ASSIGNED, FSMEvent.ARRIVED,
        FSMEvent.TASK_COMPLETE, FSMEvent.RECHARGE_NOT_NEEDED,
    ])
    recharging_task = count([
        FSMEvent.TASK_ANNOUNCED, FSMEvent.AUCTION_WON,
        FSMEvent.WAYPOINT_ASSIGNED, FSMEvent.ARRIVED,
        FSMEvent.TASK_COMPLETE, FSMEvent.AT_BASE_NEED_CHARGE,
        FSMEvent.CHARGE_COMPLETE,
    ])
    lost_auction = count([FSMEvent.TASK_ANNOUNCED, FSMEvent.AUCTION_LOST])

    assert (in_field_task, recharging_task, lost_auction) == (6, 7, 2)

    # 2 Hz baseline over a 1800 s run, against a robot completing a task every
    # two minutes with three lost auctions between each.
    baseline = 2.0 * 1800.0
    added = 15 * (in_field_task + 3 * lost_auction)
    assert added / baseline < 0.10, (
        f'added {added} messages against a baseline of {baseline:.0f} is '
        f'{added / baseline:.1%}; if this ever exceeds 10% the bound in '
        f'_on_fsm_transition needs restating'
    )
