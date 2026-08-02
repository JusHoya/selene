#!/usr/bin/env python3
"""Demonstrate — on a running system — that an emergency injection preempts.

WHY THIS EXISTS SEPARATELY FROM THE EXIT GATE.

The Phase 5 exit gate injects an emergency task (check 5/6, register D-44) but
it CANNOT choose the moment it does so: its stimulus timeline is pinned to
``pick_prospect_robot``, which by construction runs when nothing capable is
idle. An auction only ever OPENS when an idle robot could bid on the task
(``_auction_tick``'s idle gate plus ``servable=``), so at the gate's injection
instant there is usually no auction in flight at all, and check 6's corroboration
clause correctly reports NOT APPLICABLE and asserts nothing about preemption.
That is the honest outcome and it is the one the ninth and tenth gate runs
produced. It leaves the preemption path itself UNDEMONSTRATED.

This script demonstrates exactly that path and nothing else. It watches
``/orchestrator/task_queue`` for a task that is genuinely AUCTIONING and injects
an EMERGENCY prospect the moment it sees one, which is the only condition under
which ``_preempt_for_emergency`` is reachable at all.

THE CONJUNCTION IS NARROWER THAN "AN AUCTION IS IN FLIGHT", AND THIS SCRIPT HAD
TO BE REWRITTEN ONCE TO NOTICE IT. ``_preempt_for_emergency`` refuses to spend
the preemption unless some robot is IDLE **and** capable of the emergency
(gate (a) — it will not empty the auction slot on a tick where it cannot also
announce). But every idle robot that CAN bid on an announcement bids on it
immediately and leaves IDLE (``agent_node._on_task_announced``), so a prospect
auction in flight has, by construction, already consumed every idle
prospect-capable robot. Measured, first run of this script: the emergency was
injected 0.001 s after an auction was seen in flight, and nothing was
preempted — correctly, because no idle scout remained. The window is real but
it needs a robot that is idle for a reason unrelated to the running auction.

So this script MANUFACTURES the conjunction, and says so in its own output: it
frees one busy prospect-capable robot with an ``OverrideRobot`` ``cancel_task``
— the same supported operator path ``phase5_probe.pick_prospect_robot`` uses,
for the same reason — while the victim's auction is still open. That robot is
not bidding on the victim's auction (it was NAVIGATING, not IDLE, when the
announcement went out), so freeing it creates exactly the state the preemption
path exists for: an auction in flight, and an idle robot that could serve a more
urgent task. **A fleet this script perturbed is not a fleet that arrived here on
its own**, and no conclusion below should be read as "this happens unprompted".

WHAT IT PROVES, IF IT PASSES:
  (a) an ``auction_preempted`` ``status_reason`` on the victim, observed on the
      wire — the mechanism, not a unit test's model of it;
  (b) the victim RETURNS to the queue rather than being cancelled, with its
      ``auction_rounds`` REFUNDED to what it held before its auction;
  (c) the emergency is announced in the SAME tick, carrying
      ``TaskAnnouncement.emergency = True``;
  (d) the emergency is assigned to a real robot.

WHAT IT DOES NOT PROVE. Nothing about the NON-emergency path, which is
deliberately unchanged and is exercised by no automated check anywhere (register
open item 30). Run with ``--no-emergency`` to watch that path decline to preempt;
that is a control, not a proof, because "nothing happened" is also what a broken
injection looks like — which is why the control additionally requires the
injected task to be accepted and to reach the queue.

USAGE (a SELENE stack must already be running, e.g. scripts/start.sh or
``ros2 launch selene_sim unified_sim.launch.py``):

    python3 scripts/demo_emergency_preemption.py
    python3 scripts/demo_emergency_preemption.py --no-emergency   # the control

Exit codes follow the gate's contract: 0 demonstrated, 1 refuted, 2 could not be
measured (no auction was ever in flight inside the watch window — a SKIP, never
a pass), 3 could not start.
"""

from __future__ import annotations

import argparse
import sys
import time

# THE IMPORT FAILURE IS RECORDED, NOT ACTED ON, and that is deliberate. An
# ``sys.exit`` at module scope -- which is what this file did until it was
# reviewed -- makes the module unimportable without ROS, so NO documented test
# lane can reach a line of it. That is precisely the shape register D-42 names:
# ``battery_node.py``'s arithmetic sat behind a module-level ``import rclpy``,
# no lane could reach it, and its energy model therefore had zero tests of any
# kind while being wrong. Apparatus is not exempt from that rule -- 2026-08-01's
# second lesson is that four of five deviations that day were instruments, three
# of them reporting success. ``main`` exits 3 on the recorded error instead, and
# the pure decision helpers below are importable and tested.
_ROS_IMPORT_ERROR = ''

try:
    import rclpy
    from rclpy.node import Node
except ImportError as exc:  # pragma: no cover - exercised only without ROS
    rclpy = None
    Node = object
    _ROS_IMPORT_ERROR = (
        'rclpy is not importable (%s). Source the workspace first:\n'
        '  source /opt/ros/jazzy/setup.bash && source install/setup.bash'
        % (exc,))

try:
    from selene_msgs.msg import RobotState, TaskAnnouncement, TaskQueueState
    from selene_msgs.srv import InjectTask, OverrideRobot
except ImportError as exc:  # pragma: no cover - only without the workspace
    RobotState = TaskAnnouncement = TaskQueueState = None
    InjectTask = OverrideRobot = None
    _ROS_IMPORT_ERROR = _ROS_IMPORT_ERROR or (
        'selene_msgs is not importable (%s). Build and source the workspace: '
        'colcon build && source install/setup.bash' % (exc,))


#: The status a task holds while its auction is open.
AUCTIONING = 'AUCTIONING'

#: What the orchestrator writes onto a preempted victim
#: (``task_feed.AUCTION_PREEMPTED``). Spelled here rather than imported so this
#: script measures the WIRE and not the orchestrator's own constant — if the two
#: ever disagree, that disagreement is the finding.
AUCTION_PREEMPTED = 'auction_preempted'

#: Operator injections are ``manual_NNNN`` (``TaskQueue.make_unique_task_id``).
#: A victim must not be one: a task cannot preempt its own auction, and crediting
#: an injection as its own victim would be the clause proving itself.
MANUAL_PREFIX = 'manual_'


class PreemptionWitness(Node):
    """Records the task queue, announcements, and one injection."""

    def __init__(self):
        super().__init__('selene_preemption_witness')
        self.snapshots: list[tuple[float, dict]] = []
        self.announcements: list[tuple[float, str, bool]] = []
        #: robot_id -> latest (fsm_state, capabilities). Level, not history:
        #: this script only ever asks "who is busy RIGHT NOW", never "was
        #: anyone ever idle" — which is the D-34 mistake, and it is not the
        #: question here.
        self.robots: dict[str, tuple[str, list[str]]] = {}
        self.create_subscription(
            TaskQueueState, '/orchestrator/task_queue', self._on_queue, 10)
        self.create_subscription(
            TaskAnnouncement, '/orchestrator/task_announcement',
            self._on_announcement, 10)
        self._inject = self.create_client(
            InjectTask, '/orchestrator/inject_task')
        self._override = self.create_client(
            OverrideRobot, '/orchestrator/override_robot')

    def subscribe_fleet(self) -> list[str]:
        """Subscribe to every ``/<rid>/state`` the graph currently advertises.

        Discovered rather than configured, for the reason validate_phase5.sh
        derives its fleet instead of hardcoding 4: a literal here would silently
        measure the default fleet on a launch that started a different one.
        """
        fleet = []
        for topic, types in self.get_topic_names_and_types():
            if not topic.endswith('/state'):
                continue
            if 'selene_msgs/msg/RobotState' not in types:
                continue
            rid = topic[1:-len('/state')]
            if '/' in rid:
                continue
            fleet.append(rid)
            self.create_subscription(
                RobotState, topic, lambda msg, r=rid: self._on_state(r, msg), 10)
        return sorted(fleet)

    def _on_state(self, rid: str, msg) -> None:
        self.robots[rid] = (msg.fsm_state, list(msg.capabilities))

    def busy_capable(self, capability: str) -> str | None:
        """A robot with *capability* that is busy — NOT idle and not bidding.

        Deliberately excludes BIDDING: a robot bidding on the victim's own
        auction is the one robot whose freeing would prove nothing, because
        cancelling it withdraws the very bid the auction is waiting on.
        Excludes ERROR/OFFLINE/RECHARGING for the reason inject_task_logic's
        own pre-checks do.
        """
        unusable = ('IDLE', 'BIDDING', 'ERROR', 'OFFLINE', 'RECHARGING')
        for rid, (state, caps) in sorted(self.robots.items()):
            if capability in caps and state not in unusable:
                return rid
        return None

    def idle_capable(self, capability: str) -> str | None:
        """A robot with *capability* that is IDLE right now, or None."""
        for rid, (state, caps) in sorted(self.robots.items()):
            if capability in caps and state == 'IDLE':
                return rid
        return None

    def free_robot(self, robot_id: str):
        """OverrideRobot cancel_task. Returns the response, or None."""
        if not self._override.wait_for_service(timeout_sec=10.0):
            return None
        request = OverrideRobot.Request()
        request.robot_id = robot_id
        request.command = 'cancel_task'
        future = self._override.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=15.0)
        return future.result()

    def _on_queue(self, msg) -> None:
        rows = {}
        for task in msg.tasks:
            rows[task.task_id] = {
                'status': task.status,
                'status_reason': task.status_reason,
                'assigned_robot': task.assigned_robot,
                'auction_rounds': int(task.auction_rounds),
                # getattr: a snapshot from an orchestrator built before D-44
                # has no such field, and this script must say so rather than
                # raise halfway through a live run.
                'emergency': bool(getattr(task, 'emergency', False)),
                'priority': float(task.priority),
            }
        self.snapshots.append((time.time(), rows))

    def _on_announcement(self, msg) -> None:
        self.announcements.append(
            (time.time(), msg.task_id, bool(getattr(msg, 'emergency', False))))

    def inject(self, x: float, y: float, emergency: bool):
        """Call InjectTask. Returns the response, or None if it never answered."""
        if not self._inject.wait_for_service(timeout_sec=10.0):
            return None
        request = InjectTask.Request()
        request.task_type = 'prospect'
        request.target_location.x = float(x)
        request.target_location.y = float(y)
        request.target_location.z = 0.0
        request.quantity = 0.0
        request.assigned_robot_id = ''
        request.emergency = bool(emergency)
        future = self._inject.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=15.0)
        return future.result()


def spin_for(node, seconds: float) -> None:
    """Spin the node for *seconds* of wall clock."""
    end = time.time() + seconds
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.05)


def find_live_auction(node, deadline_sec: float, capability: str):
    """Wait for the FULL preemption window. Returns (task_id, rounds).

    Both halves must hold in the same snapshot, and requiring both is the
    correction this script needed after its first live run:

      (a) a non-injected task is AUCTIONING — there is something to preempt;
      (b) some robot with *capability* is BUSY, and therefore freeable — there
          is somewhere for the emergency to go that the running auction has not
          already claimed.

    (b) requires BUSY specifically, not "busy or already idle", and that is the
    third correction a live run forced. At boot every scout is IDLE, so "an
    auction is in flight and a scout is idle" is true of the FIRST auction of
    every run — and it is exactly the case that cannot be demonstrated, because
    that idle scout is the one bidding on the auction we would be preempting.
    Waiting for a busy one waits for the fleet to settle into work, which is
    both the honest precondition and the realistic one.

    Without (b) ``_preempt_for_emergency``'s gate (a) refuses, correctly, and
    the run measures the refusal rather than the preemption. At boot every scout
    is IDLE or BIDDING, so (b) is false for the freeing path and the first
    auctions of a run are unusable; the fleet has to settle into work first.

    Returns ``(None, None)`` if the window expires. Reads the LATEST snapshot
    only: a task that was AUCTIONING two seconds ago has very likely resolved
    (``auction_timeout_sec`` is 5.0 s), and preempting requires the auction to
    still be open at the orchestrator's NEXT tick, not to have been open once.
    """
    end = time.time() + deadline_sec
    seen = 0
    auctions_seen = 0
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.05)
        if not node.snapshots:
            continue
        seen = len(node.snapshots)
        _, rows = node.snapshots[-1]
        for task_id, row in rows.items():
            if task_id.startswith(MANUAL_PREFIX):
                continue
            if row['status'] != AUCTIONING:
                continue
            auctions_seen += 1
            if node.busy_capable(capability) is not None:
                return task_id, row['auction_rounds']
    print('  (watched %d queue snapshots; saw an open auction on %d of them, '
          'none of them alongside a BUSY %s-capable robot to free)'
          % (seen, auctions_seen, capability))
    return None, None


def victim_outcome(node, victim: str, since: float):
    """How did *victim* leave AUCTIONING after *since*? -> (reason, rounds)."""
    for stamp, rows in node.snapshots:
        if stamp < since:
            continue
        row = rows.get(victim)
        if row is None or row['status'] == AUCTIONING:
            continue
        return row['status_reason'], row['auction_rounds'], row['status']
    return None, None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--x', type=float, default=-50.0)
    parser.add_argument('--y', type=float, default=-100.0)
    parser.add_argument('--watch', type=float, default=120.0,
                        help='seconds to wait for an auction to be in flight')
    parser.add_argument('--settle', type=float, default=20.0,
                        help='seconds to record after the injection')
    parser.add_argument('--no-emergency', action='store_true',
                        help='the CONTROL: inject without the flag and require '
                             'that NOTHING is preempted')
    args = parser.parse_args()
    emergency = not args.no_emergency

    if _ROS_IMPORT_ERROR:
        print('ERROR: %s' % (_ROS_IMPORT_ERROR,), file=sys.stderr)
        return 3

    rclpy.init()
    node = PreemptionWitness()
    try:
        # Let discovery settle so the first snapshot is not also the first
        # message of the subscription.
        spin_for(node, 2.0)
        fleet = node.subscribe_fleet()
        if not fleet:
            print('ERROR: no /<robot>/state topics found. Is a SELENE stack '
                  'running?', file=sys.stderr)
            return 3
        print('Fleet: %s' % (', '.join(fleet),))
        spin_for(node, 2.0)

        print('Watching /orchestrator/task_queue for an auction in flight '
              '(up to %.0fs)...' % (args.watch,))
        victim, rounds_before = find_live_auction(node, args.watch, 'prospect')
        if victim is None:
            print('SKIP: no auction was in flight inside the watch window, so '
                  'the preemption path was never reachable. Nothing is '
                  'asserted. Try a busier fleet, or a longer --watch.')
            return 2

        print('  auction IN FLIGHT for %s (auction_rounds=%d)'
              % (victim, rounds_before))

        # MANUFACTURE THE CONJUNCTION. See the module docstring: an auction in
        # flight has already consumed every idle robot that could bid on it, so
        # without this step gate (a) of _preempt_for_emergency correctly
        # refuses and nothing is demonstrated. Freeing a BUSY robot (never a
        # bidding one) creates an idle robot whose idleness has nothing to do
        # with the running auction — which is the real-world case the whole
        # feature exists for: something more urgent arrives while the fleet is
        # mid-allocation.
        # PREFER FREEING A BUSY ROBOT EVEN WHEN ONE ALREADY READS IDLE, and
        # that preference is the second correction this script needed from a
        # live run. A robot this witness has recorded as IDLE may already have
        # bid: `agent_node._on_task_announced` transitions to BIDDING and
        # publishes, and a 6 ms-old cached sample is enough to be wrong about
        # it. Measured: a run where the conjunction appeared to hold, no robot
        # was freed, and nothing was preempted — because the orchestrator's own
        # `get_idle_robots` (which is what `_servable_by_idle_fleet` consults)
        # no longer counted that scout. A robot freed by cancel_task in this
        # tick cannot be a bidder on the auction that was announced before it,
        # so it is the only idle robot whose idleness this script can assert.
        freed = None
        busy = node.busy_capable('prospect')
        if busy is None:
            print('SKIP: the busy prospect-capable robot seen a moment ago is '
                  'no longer freeable, so the conjunction evaporated before it '
                  'could be used. Nothing is asserted; re-run.')
            return 2
        else:
            response = node.free_robot(busy)
            if response is None or not response.success:
                print('SKIP: cancel_task on %s was not accepted (%s), so the '
                      'conjunction was never established. Nothing is asserted.'
                      % (busy, getattr(response, 'message', 'no answer')))
                return 2
            freed = busy
            print('  FLEET PERTURBED: freed %s with an operator cancel_task to '
                  'create an idle prospect-capable robot while %s\'s auction '
                  'is still open' % (freed, victim))
            # The agent fires OPERATOR_CANCEL before answering, so IDLE is
            # imminent rather than instant. Wait for it to be OBSERVED, not
            # assumed -- but briefly, because the victim's auction is running
            # out (auction_timeout_sec 5.0) and a preemption after it resolves
            # measures nothing.
            # Wait for THIS robot to report IDLE, not for "some prospect-capable
            # robot to be idle" -- the latter is satisfied by the very stale
            # reading this branch exists to stop trusting.
            idle_by = time.time() + 3.0
            while time.time() < idle_by:
                rclpy.spin_once(node, timeout_sec=0.05)
                if node.robots.get(freed, ('', []))[0] == 'IDLE':
                    break
            observed = node.robots.get(freed, ('(no state)', []))[0]
            print('  %s now reports %s' % (freed, observed))
            if observed != 'IDLE':
                print('SKIP: %s did not reach IDLE within 3s of an accepted '
                      'cancel_task, so the conjunction was never established. '
                      'Nothing is asserted.' % (freed,))
                return 2

        still = node.snapshots[-1][1].get(victim, {}).get('status')
        if still != AUCTIONING:
            print('SKIP: %s left AUCTIONING (now %s) while the idle robot was '
                  'being manufactured, so there was no longer an auction to '
                  'preempt. Nothing is asserted; re-run.' % (victim, still))
            return 2

        inject_time = time.time()
        response = node.inject(args.x, args.y, emergency)
        if response is None:
            print('FAIL: /orchestrator/inject_task never answered.')
            return 1
        if not response.success:
            print('FAIL: injection refused: %s' % (response.message,))
            return 1
        injected = response.task_id
        print('  injected %s (emergency=%s) %.3fs after seeing the auction'
              % (injected, emergency, time.time() - inject_time))
        print('  response: %s' % (response.message,))

        spin_for(node, args.settle)

        reason, rounds_after, status = victim_outcome(node, victim, inject_time)
        announced = [a for a in node.announcements if a[1] == injected]
        assigned = None
        for _, rows in node.snapshots:
            row = rows.get(injected)
            if row and row['assigned_robot']:
                assigned = row['assigned_robot']
                break

        print('')
        print('  victim %s left AUCTIONING as %s, status_reason=%r, '
              'auction_rounds %d -> %s'
              % (victim, status, reason, rounds_before,
                 rounds_after if rounds_after is not None else '(never left)'))
        print('  %s announced %d time(s); emergency flag on the wire: %s'
              % (injected, len(announced),
                 [a[2] for a in announced] or 'no announcement seen'))
        print('  %s assigned to: %s' % (injected, assigned or '(unassigned)'))
        print('')

        if not emergency:
            # THE CONTROL. "Nothing was preempted" is also what a dead injection
            # looks like, so the task must additionally have been accepted and
            # be visible in the queue -- otherwise this proves nothing.
            in_queue = any(injected in rows for _, rows in node.snapshots)
            if reason == AUCTION_PREEMPTED:
                print('REFUTED: a NON-emergency injection preempted %s. The '
                      'flag is not the boundary it is documented to be.'
                      % (victim,))
                return 1
            if not in_queue:
                print('INCONCLUSIVE: nothing was preempted, but %s never '
                      'appeared in a queue snapshot either, so this run does '
                      'not distinguish "did not preempt" from "did not run".'
                      % (injected,))
                return 2
            print('CONTROL HELD: a non-emergency priority-10 injection did NOT '
                  'preempt the auction for %s, and did reach the queue.'
                  % (victim,))
            return 0

        problems = []
        if reason != AUCTION_PREEMPTED:
            problems.append(
                'victim %s did not carry status_reason %r (got %r) -- the '
                'auction it was in resolved normally, so no preemption '
                'happened' % (victim, AUCTION_PREEMPTED, reason))
        if rounds_after is not None and rounds_after > rounds_before:
            problems.append(
                'victim %s was CHARGED for the preempted round '
                '(auction_rounds %d -> %d); abort_auction is supposed to '
                'refund it' % (victim, rounds_before, rounds_after))
        if not announced:
            problems.append(
                '%s was never announced, so the abort emptied the auction '
                'slot and bought nothing' % (injected,))
        elif not any(flag for _, _, flag in announced):
            problems.append(
                '%s was announced but TaskAnnouncement.emergency was False on '
                'every announcement -- the flag did not reach the wire'
                % (injected,))
        if assigned is None:
            problems.append('%s was never assigned to a robot' % (injected,))

        if problems:
            print('REFUTED:')
            for problem in problems:
                print('  - %s' % (problem,))
            return 1

        perturbation = (
            ' The conjunction was MANUFACTURED: %s was freed with an operator '
            'cancel_task to put an idle prospect-capable robot beside the '
            'running auction. This did not arise on its own.' % (freed,)
            if freed else
            ' No robot was freed: the fleet presented an idle prospect-capable '
            'robot beside a running auction on its own.')
        print('DEMONSTRATED: emergency %s preempted the in-flight auction for '
              '%s, which returned to the queue with its round refunded; the '
              'emergency was announced with emergency=True on the wire and '
              'assigned to %s.%s' % (injected, victim, assigned, perturbation))
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
