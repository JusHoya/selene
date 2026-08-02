"""The live preemption demonstrator's own decision logic, without ROS.

WHY THIS FILE EXISTS
--------------------
``scripts/demo_emergency_preemption.py`` is the apparatus that produced the
FIRST ``auction_preempted`` ever observed on the wire in this project (register
D-44). It is an instrument, and 2026-08-01's second lesson is that instruments
need running and testing as much as systems do: four of that day's five new
deviations were measuring apparatus rather than the system, and THREE OF THE FOUR
WERE REPORTING SUCCESS (D-38 a CI job that had never fired, D-39 a preflight
check printing OK against an empty string, D-40 a canvas whose animation loop had
never started under a header showing correct numbers, D-41 a simulator crash that
manufactured four believable "cannot climb" results).

This demonstrator earned the same suspicion honestly. It was REFUTED THREE TIMES
on live runs before it demonstrated anything, and each refutation was a defect in
the instrument rather than in the system under test:

  1. it injected the moment any auction was in flight, when an auction in flight
     has by construction already consumed every idle robot that could bid on it,
     so the orchestrator's gate (a) correctly refused and nothing was shown;
  2. it trusted its own cached ``RobotState`` to decide a robot was IDLE, and a
     6 ms-old sample was enough to be wrong — the robot had already bid;
  3. it accepted "an idle robot exists" as the precondition, which is true of
     the FIRST auction of every run, which is exactly the unusable case.

None of those was visible from reading it. All three are pinned below.

THE IMPORT IS THE OTHER HALF. Until it was reviewed this script called
``sys.exit(3)`` at module scope when rclpy was missing, which makes it
unimportable off a ROS box and therefore unreachable by every documented test
lane — the precise shape of register D-42, where ``battery_node.py``'s arithmetic
sat behind a module-level ``import rclpy``, no lane could reach it, and the
energy model consequently had ZERO tests of any kind while being wrong. That this
file imports at all on a machine without ROS is itself the regression test, and
``test_the_module_imports_without_ros`` says so.
"""

import importlib.util
import os
import sys

import pytest


REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMO_PATH = os.path.join(REPO_ROOT, 'scripts', 'demo_emergency_preemption.py')


def load_demo():
    """Import the demonstrator by path, exactly as the probe tests do.

    By path rather than as a package because ``scripts/`` is not one. This
    SUCCEEDING without ROS on the path is the D-42 regression assertion.
    """
    spec = importlib.util.spec_from_file_location(
        'demo_emergency_preemption_under_test', DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


demo = load_demo()


class _FakeWitness:
    """Stands in for ``PreemptionWitness`` with no ROS behind it.

    Only the three things the pure helpers read: recorded queue snapshots, and
    the two fleet queries. Nothing is subscribed and nothing spins.
    """

    def __init__(self, snapshots=None, robots=None):
        self.snapshots = list(snapshots or [])
        self.robots = dict(robots or {})

    # Mirrors of the real methods, which are pure over ``self.robots``.
    busy_capable = demo.PreemptionWitness.busy_capable
    idle_capable = demo.PreemptionWitness.idle_capable


def test_the_module_imports_without_ros():
    """D-42's shape: the file must be reachable by a lane with no ROS.

    ``load_demo`` already ran at import time; this asserts the consequence
    explicitly so the reason is recorded next to the failure if it ever breaks.
    A module-level ``sys.exit`` would have made THIS FILE exit the pytest
    process rather than fail a test, which is why the assertion is about the
    recorded error rather than about an exception.
    """
    assert hasattr(demo, '_ROS_IMPORT_ERROR')
    assert hasattr(demo, 'victim_outcome')
    assert hasattr(demo, 'find_live_auction')


def test_main_exits_3_when_ros_is_absent(monkeypatch, capsys):
    """The exit code moved from import time to ``main``; it still exists."""
    monkeypatch.setattr(demo, '_ROS_IMPORT_ERROR', 'rclpy is not importable')
    monkeypatch.setattr(sys, 'argv', ['demo_emergency_preemption.py'])
    assert demo.main() == 3
    assert 'rclpy is not importable' in capsys.readouterr().err


# ------------------------------------------------------------------------- #
#  busy_capable / idle_capable — refutation 2 and 3                          #
# ------------------------------------------------------------------------- #

def test_busy_capable_never_returns_a_bidding_robot():
    """REFUTATION 2. A BIDDING robot is the one robot freeing proves nothing on.

    Cancelling it withdraws the very bid the running auction is waiting on, so
    the auction would resolve differently for a reason that has nothing to do
    with preemption. It must not be offered as the robot to free.
    """
    witness = _FakeWitness(robots={'scout_01': ('BIDDING', ['prospect'])})
    assert witness.busy_capable('prospect') is None


@pytest.mark.parametrize('state', ['IDLE', 'ERROR', 'OFFLINE', 'RECHARGING'])
def test_busy_capable_excludes_the_unusable_states(state):
    witness = _FakeWitness(robots={'scout_01': (state, ['prospect'])})
    assert witness.busy_capable('prospect') is None


@pytest.mark.parametrize('state', ['NAVIGATING', 'WORKING', 'ASSIGNED',
                                   'RETURNING'])
def test_busy_capable_accepts_a_genuinely_working_robot(state):
    witness = _FakeWitness(robots={'scout_01': (state, ['prospect'])})
    assert witness.busy_capable('prospect') == 'scout_01'


def test_busy_capable_respects_capability():
    """An idle hauler is not a robot a prospect emergency can be given to.

    This is the fleet's own answer: ``agent_node`` declines an announcement
    whose required_capabilities its HAL does not cover, and the set tested there
    is the same one published in ``RobotState.capabilities``.
    """
    witness = _FakeWitness(robots={
        'hauler_01': ('NAVIGATING', ['haul']),
        'scout_01': ('NAVIGATING', ['prospect']),
    })
    assert witness.busy_capable('haul') == 'hauler_01'
    assert witness.busy_capable('prospect') == 'scout_01'
    assert witness.busy_capable('excavate') is None


def test_idle_capable_finds_only_idle_robots():
    witness = _FakeWitness(robots={
        'scout_01': ('NAVIGATING', ['prospect']),
        'scout_02': ('IDLE', ['prospect']),
    })
    assert witness.idle_capable('prospect') == 'scout_02'


def test_both_queries_are_deterministic_across_dict_order():
    """Sorted, so two runs on the same fleet free the same robot.

    An instrument that picks a different subject depending on dict iteration
    order produces runs that cannot be compared with each other.
    """
    forward = _FakeWitness(robots={
        'scout_01': ('NAVIGATING', ['prospect']),
        'scout_02': ('NAVIGATING', ['prospect']),
    })
    backward = _FakeWitness(robots={
        'scout_02': ('NAVIGATING', ['prospect']),
        'scout_01': ('NAVIGATING', ['prospect']),
    })
    assert forward.busy_capable('prospect') == backward.busy_capable('prospect')


# ------------------------------------------------------------------------- #
#  find_live_auction — refutation 1 and 3                                    #
# ------------------------------------------------------------------------- #

def _rows(**tasks):
    """Queue rows keyed by task_id, in the shape ``_on_queue`` records."""
    out = {}
    for task_id, (status, rounds) in tasks.items():
        out[task_id] = {
            'status': status, 'status_reason': '', 'assigned_robot': '',
            'auction_rounds': rounds, 'emergency': False, 'priority': 5.0,
        }
    return out


def test_an_open_auction_alone_is_not_the_window(monkeypatch):
    """REFUTATION 1 and 3, together, and this is the load-bearing test.

    At boot every scout is IDLE, so "an auction is in flight" is true of the
    first auction of every run — and that auction has already consumed the only
    robots that could bid on it. Requiring a BUSY robot is what makes the
    window the one the orchestrator can actually act on. Measured live: three
    consecutive runs were REFUTED on exactly this before the requirement was
    tightened.
    """
    monkeypatch.setattr(demo.rclpy, 'spin_once', lambda *a, **k: None,
                        raising=False)
    witness = _FakeWitness(
        snapshots=[(1.0, _rows(survey_a=('AUCTIONING', 1)))],
        robots={'scout_01': ('IDLE', ['prospect']),
                'scout_02': ('BIDDING', ['prospect'])})
    victim, rounds = demo.find_live_auction(witness, 0.2, 'prospect')
    assert victim is None
    assert rounds is None


def test_the_window_opens_when_a_busy_robot_coexists(monkeypatch):
    monkeypatch.setattr(demo.rclpy, 'spin_once', lambda *a, **k: None,
                        raising=False)
    witness = _FakeWitness(
        snapshots=[(1.0, _rows(survey_a=('AUCTIONING', 3)))],
        robots={'scout_01': ('NAVIGATING', ['prospect'])})
    victim, rounds = demo.find_live_auction(witness, 5.0, 'prospect')
    assert victim == 'survey_a'
    assert rounds == 3


def test_an_injected_task_is_never_its_own_victim(monkeypatch):
    """A task cannot preempt its own auction, and crediting an injection as its
    own victim would be the clause proving itself.
    """
    monkeypatch.setattr(demo.rclpy, 'spin_once', lambda *a, **k: None,
                        raising=False)
    witness = _FakeWitness(
        snapshots=[(1.0, _rows(manual_0000=('AUCTIONING', 1)))],
        robots={'scout_01': ('NAVIGATING', ['prospect'])})
    victim, _ = demo.find_live_auction(witness, 0.2, 'prospect')
    assert victim is None


def test_only_the_latest_snapshot_counts(monkeypatch):
    """A task that was AUCTIONING two seconds ago has very likely resolved.

    auction_timeout_sec is 5.0 s, and preempting needs the auction still open at
    the orchestrator's NEXT tick — not to have been open once.
    """
    monkeypatch.setattr(demo.rclpy, 'spin_once', lambda *a, **k: None,
                        raising=False)
    witness = _FakeWitness(
        snapshots=[(1.0, _rows(survey_a=('AUCTIONING', 1))),
                   (2.0, _rows(survey_a=('ASSIGNED', 1)))],
        robots={'scout_01': ('NAVIGATING', ['prospect'])})
    victim, _ = demo.find_live_auction(witness, 0.2, 'prospect')
    assert victim is None


# ------------------------------------------------------------------------- #
#  victim_outcome — what the demonstration actually reads                    #
# ------------------------------------------------------------------------- #

def test_victim_outcome_reports_the_preemption():
    """The observation the live run produced: PENDING, reason, round refunded."""
    rows = _rows(survey_a=('PENDING', 0))
    rows['survey_a']['status_reason'] = demo.AUCTION_PREEMPTED
    witness = _FakeWitness(snapshots=[(10.0, rows)])
    reason, rounds, status = demo.victim_outcome(witness, 'survey_a', 5.0)
    assert reason == demo.AUCTION_PREEMPTED
    assert rounds == 0
    assert status == 'PENDING'


def test_victim_outcome_ignores_snapshots_from_before_the_injection():
    """An ``auction_preempted`` predating the injection is somebody else's.

    A second operator, or a second SELENE stack on the same domain (D-42), can
    put one there. Crediting it would be the instrument reporting a success it
    did not cause.
    """
    stale = _rows(survey_a=('PENDING', 0))
    stale['survey_a']['status_reason'] = demo.AUCTION_PREEMPTED
    witness = _FakeWitness(snapshots=[(1.0, stale)])
    reason, rounds, status = demo.victim_outcome(witness, 'survey_a', 5.0)
    assert reason is None
    assert rounds is None
    assert status is None


def test_victim_outcome_skips_while_the_task_is_still_auctioning():
    witness = _FakeWitness(snapshots=[
        (6.0, _rows(survey_a=('AUCTIONING', 1))),
        (7.0, _rows(survey_a=('ASSIGNED', 1))),
    ])
    reason, rounds, status = demo.victim_outcome(witness, 'survey_a', 5.0)
    assert status == 'ASSIGNED'
    assert rounds == 1


def test_the_reason_literal_matches_what_the_orchestrator_writes():
    """The demonstrator spells the reason rather than importing it, so that a
    divergence between the two is a FINDING and not an invisible agreement.
    This test is where the two are compared.

    ``importorskip``: the gate lane runs without ``selene_agent`` on the path
    and this repo's D-36 lesson is that an unguarded cross-package import turns
    a skip into a lane failure.
    """
    task_feed = pytest.importorskip('selene_orchestrator.task_feed')
    assert demo.AUCTION_PREEMPTED == task_feed.AUCTION_PREEMPTED
