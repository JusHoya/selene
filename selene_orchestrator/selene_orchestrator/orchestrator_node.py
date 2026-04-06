"""Fleet orchestrator node for SELENE multi-agent coordination.

Manages task auction, fleet health monitoring, and resource map.
Generates prospect survey waypoints and distributes them via auction.
"""

import time

import rclpy
from rclpy.node import Node

from selene_msgs.msg import (
    BidResponse as BidResponseMsg,
    FleetAlert,
    MissionProgress,
    ResourceMapUpdate,
    RobotState,
    TaskAnnouncement,
    TaskAssignment,
)
from geometry_msgs.msg import Point

from selene_orchestrator.fleet_monitor import FleetMonitor
from selene_orchestrator.task_queue import TaskQueue, TaskStatus
from selene_orchestrator.task_auction import TaskAuction, Bid
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.waypoint_generator import generate_psr_survey_waypoints
from selene_orchestrator.htn_planner import HTNPlanner
from selene_orchestrator.adaptive_survey import AdaptiveSurveyPlanner
from selene_isru.inventory import MaterialInventory


class OrchestratorNode(Node):
    """Central fleet orchestrator with auction-based task allocation.

    Lifecycle
    ---------
    1. On startup, declares ROS parameters, instantiates pure-Python core
       modules (FleetMonitor, TaskQueue, TaskAuction, ResourceMap), and
       generates PSR survey waypoints as prospect tasks.
    2. Subscribes to per-robot ``/<robot_id>/state`` topics and the shared
       ``/orchestrator/bid_response`` and ``/orchestrator/map_update`` topics.
    3. Runs three periodic timers:
       - heartbeat_check (1 Hz): detects timed-out robots, re-queues tasks.
       - auction_tick (2 Hz): starts / resolves auctions for pending tasks.
       - publish_mission_progress (1 Hz): broadcasts aggregate progress.
    """

    def __init__(self):
        super().__init__('orchestrator_node')

        # ---- Parameters ----
        self.declare_parameter('auction_timeout_sec', 5.0)
        self.declare_parameter('heartbeat_timeout_sec', 10.0)
        self.declare_parameter('recharge_threshold', 0.30)
        self.declare_parameter('fleet_state_publish_rate', 1.0)
        self.declare_parameter('resource_map_publish_rate', 0.5)
        self.declare_parameter('map_resolution', 1.0)
        self.declare_parameter('map_width', 500)
        self.declare_parameter('map_height', 500)
        self.declare_parameter(
            'fleet_robot_ids',
            ['scout_01', 'scout_02', 'excavator_01', 'hauler_01'],
        )

        auction_timeout = self.get_parameter('auction_timeout_sec').value
        heartbeat_timeout = self.get_parameter('heartbeat_timeout_sec').value
        fleet_ids = self.get_parameter('fleet_robot_ids').value
        map_w = self.get_parameter('map_width').value
        map_h = self.get_parameter('map_height').value
        map_res = self.get_parameter('map_resolution').value

        # ---- Core modules ----
        self._fleet = FleetMonitor(heartbeat_timeout=heartbeat_timeout)
        self._task_queue = TaskQueue()
        self._auction = TaskAuction(timeout_sec=auction_timeout)
        self._resource_map = ResourceMap(
            width=map_w,
            height=map_h,
            resolution=map_res,
            origin_x=-map_w * map_res / 2,
            origin_y=-map_h * map_res / 2,
        )

        # ---- Phase 4 modules ----
        self._htn_planner = HTNPlanner(self._task_queue, self._resource_map)
        self._adaptive_survey = AdaptiveSurveyPlanner(self._resource_map)
        self._inventory = MaterialInventory()

        # ---- Tracking ----
        self._start_time = self.get_clock().now()
        self._alert_counter = 0

        # ---- Subscribers ----
        # Per-robot state subscriptions
        for rid in fleet_ids:
            self.create_subscription(
                RobotState,
                f'/{rid}/state',
                lambda msg, robot_id=rid: self._on_robot_state(msg),
                10,
            )

        # Bid responses (all robots publish to same topic)
        self.create_subscription(
            BidResponseMsg,
            '/orchestrator/bid_response',
            self._on_bid_response,
            10,
        )

        # Resource map updates from scouts
        self.create_subscription(
            ResourceMapUpdate,
            '/orchestrator/map_update',
            self._on_map_update,
            10,
        )

        # ---- Publishers ----
        self._announce_pub = self.create_publisher(
            TaskAnnouncement, '/orchestrator/task_announcement', 10,
        )
        self._assign_pub = self.create_publisher(
            TaskAssignment, '/orchestrator/task_assignment', 10,
        )
        self._alert_pub = self.create_publisher(
            FleetAlert, '/orchestrator/alerts', 10,
        )
        self._progress_pub = self.create_publisher(
            MissionProgress, '/orchestrator/mission_progress', 10,
        )

        # ---- Timers ----
        self.create_timer(1.0, self._heartbeat_check)           # 1 Hz
        self.create_timer(0.5, self._auction_tick)               # 2 Hz
        self.create_timer(1.0, self._publish_mission_progress)   # 1 Hz
        self.create_timer(1.0, self._htn_advance)                # 1 Hz

        # ---- Generate survey tasks ----
        self._generate_survey_tasks()

        self.get_logger().info(
            f'Orchestrator started | fleet={fleet_ids} '
            f'tasks={self._task_queue.get_total_count()} '
            f'auction_timeout={auction_timeout}s'
        )

    # ------------------------------------------------------------------ #
    #  Subscriber callbacks                                                #
    # ------------------------------------------------------------------ #

    def _on_robot_state(self, msg: RobotState) -> None:
        """Update fleet monitor with incoming robot state."""
        self._fleet.update_robot(
            robot_id=msg.robot_id,
            robot_type=msg.robot_type,
            fsm_state=msg.fsm_state,
            pose_x=msg.pose.x,
            pose_y=msg.pose.y,
            pose_theta=msg.pose.theta,
            battery_level=msg.battery_level,
            current_task_id=msg.current_task_id,
            capabilities=list(msg.capabilities),
            timestamp=time.monotonic(),
        )

        # Detect task completion: robot finished task and returned to idle
        if msg.fsm_state in ('RETURNING', 'IDLE') and msg.current_task_id == '':
            task_id = self._task_queue.get_task_for_robot(msg.robot_id)
            if task_id:
                task = self._task_queue.get_task(task_id)
                if task and task.status in (
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                ):
                    self._task_queue.mark_complete(task_id)
                    self.get_logger().info(
                        f'Task {task_id} completed by {msg.robot_id}'
                    )

        # Detect robot error — interrupt its task and re-queue
        if msg.fsm_state == 'ERROR' and msg.current_task_id == '':
            task_id = self._task_queue.get_task_for_robot(msg.robot_id)
            if task_id:
                task = self._task_queue.get_task(task_id)
                if task and task.status in (
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                ):
                    self._task_queue.interrupt_task(task_id, {
                        'reason': 'robot_error',
                        'robot_id': msg.robot_id,
                    })
                    # Re-queue the interrupted task as PENDING for re-auction
                    self._task_queue.set_status(task_id, TaskStatus.PENDING)
                    self._publish_alert(
                        'WARNING', msg.robot_id,
                        f'Task {task_id} interrupted due to robot error, '
                        f're-queued',
                    )

    def _on_bid_response(self, msg: BidResponseMsg) -> None:
        """Collect bid during an active auction window."""
        if self._auction.is_active():
            self._auction.add_bid(Bid(
                task_id=msg.task_id,
                robot_id=msg.robot_id,
                bid_score=msg.bid_score,
                estimated_arrival_time=msg.estimated_arrival_time,
                energy_after_task=msg.energy_after_task,
            ))

    def _on_map_update(self, msg: ResourceMapUpdate) -> None:
        """Update resource map with a new scout sensor reading."""
        self._resource_map.update(
            x=msg.location.x,
            y=msg.location.y,
            reading=msg.ice_concentration,
            sensor_uncertainty=msg.sensor_uncertainty,
        )

    # ------------------------------------------------------------------ #
    #  Timer callbacks                                                     #
    # ------------------------------------------------------------------ #

    def _heartbeat_check(self) -> None:
        """Check for robot heartbeat timeouts and recover orphaned tasks."""
        timed_out = self._fleet.check_heartbeats()
        for rid in timed_out:
            self._fleet.mark_offline(rid)
            recovered = self._task_queue.recover_tasks_for_robot(rid)
            self._publish_alert(
                'ERROR',
                rid,
                f'Heartbeat timeout. {len(recovered)} task(s) re-queued: '
                f'{recovered}',
            )
            self.get_logger().warn(
                f'Robot {rid} timed out, recovered tasks: {recovered}'
            )

    def _auction_tick(self) -> None:
        """Run the auction state machine: start or resolve auctions."""
        now = time.monotonic()

        # If an auction is active, check for timeout
        if self._auction.is_active():
            if self._auction.is_timed_out(now):
                self._resolve_auction()
            return  # Don't start a new auction while one is running

        # Check for idle robots and pending tasks
        idle = self._fleet.get_idle_robots()
        if not idle:
            return

        next_task = self._task_queue.get_next_ready()
        if next_task is None:
            return

        # Skip virtual tasks — resolved by the HTN planner, not by robots
        if next_task.task_type == 'select_site':
            return

        # Start new auction
        self._task_queue.set_status(next_task.task_id, TaskStatus.AUCTIONING)
        self._auction.start(next_task.task_id, now)
        self._publish_announcement(next_task)
        self.get_logger().info(
            f'Auction started for {next_task.task_id} ({next_task.task_type}) '
            f'at ({next_task.target_x:.0f}, {next_task.target_y:.0f})'
        )

    def _resolve_auction(self) -> None:
        """Select the auction winner and assign the task (or re-queue)."""
        winner = self._auction.select_winner()
        task_id = self._auction.get_task_id()
        bid_count = self._auction.get_bid_count()

        if winner is None:
            # No bids received -- re-queue the task
            self._task_queue.set_status(task_id, TaskStatus.PENDING)
            self.get_logger().info(
                f'Auction {task_id}: no bids ({bid_count}), re-queued'
            )
        else:
            # Assign to winner
            self._task_queue.assign_to_robot(task_id, winner.robot_id)
            task = self._task_queue.get_task(task_id)
            self._publish_assignment(task_id, winner.robot_id, task)
            self._publish_alert(
                'INFO',
                winner.robot_id,
                f'Won auction for {task_id} '
                f'(score={winner.bid_score:.3f})',
            )
            self.get_logger().info(
                f'Auction {task_id}: winner={winner.robot_id} '
                f'score={winner.bid_score:.3f} bids={bid_count}'
            )

        self._auction.reset()

    def _publish_mission_progress(self) -> None:
        """Publish aggregated mission progress metrics."""
        msg = MissionProgress()
        msg.objective_description = 'PSR Ice Prospecting Survey'
        msg.target_quantity = float(self._task_queue.get_total_count())
        progress = self._inventory.get_mission_progress()
        msg.extracted_quantity = float(progress.get('extracted', 0.0))
        msg.in_transit_quantity = float(progress.get('in_transit', 0.0))
        msg.deposited_quantity = float(progress.get('deposited', 0.0))
        msg.fleet_distance_total = 0.0   # TODO: accumulate from odometry
        msg.fleet_energy_total = 0.0
        elapsed = (self.get_clock().now() - self._start_time).nanoseconds / 1e9
        msg.elapsed_sim_time = elapsed
        self._progress_pub.publish(msg)

    def _htn_advance(self) -> None:
        """Advance the HTN planner — resolve virtual tasks, spawn downstream."""
        self._htn_planner.check_and_advance()

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _generate_survey_tasks(self) -> None:
        """Decompose the initial ISRU mission objective via HTN planner."""
        self._htn_planner.decompose_collect_ice(
            zone_center=(-100.0, -150.0),
            zone_radius=60.0,
            quantity_kg=100.0,
            depot=(50.0, 50.0),
        )
        self.get_logger().info(
            f'HTN decomposed mission: {self._task_queue.get_total_count()} tasks'
        )

    def _publish_announcement(self, task) -> None:
        """Publish a TaskAnnouncement to open an auction."""
        msg = TaskAnnouncement()
        msg.task_id = task.task_id
        msg.task_type = task.task_type
        msg.target_location = Point(
            x=task.target_x, y=task.target_y, z=0.0,
        )
        msg.estimated_energy_cost = task.estimated_energy_cost
        msg.required_capabilities = task.required_capabilities
        msg.priority = task.priority
        msg.estimated_duration = task.estimated_duration
        msg.parent_task_id = ''
        msg.deadline = self.get_clock().now().to_msg()
        self._announce_pub.publish(msg)

    def _publish_assignment(self, task_id: str, robot_id: str, task) -> None:
        """Publish a TaskAssignment to the winning robot."""
        msg = TaskAssignment()
        msg.task_id = task_id
        msg.robot_id = robot_id
        msg.task_type = task.task_type if task else 'prospect'
        msg.target_location = Point(
            x=task.target_x if task else 0.0,
            y=task.target_y if task else 0.0,
            z=0.0,
        )
        msg.parameters = []
        msg.assigned_at = self.get_clock().now().to_msg()
        self._assign_pub.publish(msg)

    def _publish_alert(
        self, severity: str, source_robot_id: str, message: str,
    ) -> None:
        """Publish a FleetAlert."""
        self._alert_counter += 1
        msg = FleetAlert()
        msg.alert_id = f'alert_{self._alert_counter:04d}'
        msg.severity = severity
        msg.source_robot_id = source_robot_id
        msg.message = message
        msg.stamp = self.get_clock().now().to_msg()
        self._alert_pub.publish(msg)


def main(args=None):
    """Entry point for the orchestrator node."""
    rclpy.init(args=args)
    node = OrchestratorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info('Orchestrator shutting down')
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
