"""Pure-Python assembly of ``selene_msgs/msg/MaterialEvent`` field values.

``agent_node.AgentNode`` publishes one ``MaterialEvent`` per *measured*
mass transfer (deviation D-06 / FR-ISRU-2). Everything about that
message except the ROS ``stamp`` is decided here, with **zero** rclpy,
selene_msgs, selene_hal or skill imports, so the id scheme and the
validation rules can be unit-tested without a ROS install — the same
split ``selene_agent.operator_command`` already uses for the
``SetRobotCommand`` decision tree.

Two things live here:

``MaterialEventIdGenerator``
    Produces the globally unique ``event_id`` the orchestrator dedupes
    on. The orchestrator keeps a bounded set of recently-seen ids and
    ignores repeats, which is what makes TRANSIENT_LOCAL replay of this
    topic idempotent.

``build_material_event_fields``
    Validates and normalises the payload. This is the last place a bad
    number can be caught before it becomes a ledger entry, so it is
    strict rather than forgiving: FR-ISRU-2's acceptance is "no material
    is lost or duplicated", and a silently-corrected mass is exactly how
    that stops being checkable.
"""
from __future__ import annotations

import math

# MaterialEvent.event_type is a lower-case string rather than a uint8
# constant, matching RobotState.fsm_state, FleetAlert.severity and
# SetRobotCommand.command. Each maps to one MaterialInventory call on the
# orchestrator side:
#   extracted -> record_extraction(site_id, robot_id, mass_kg)
#   loaded    -> record_load(robot_id, site_id, mass_kg)
#   unloaded  -> record_unload(robot_id, mass_kg)
MATERIAL_EVENT_TYPES = ('extracted', 'loaded', 'unloaded')


class MaterialEventIdGenerator:
    """Generates ``"<robot_id>:<epoch_ns>:<counter:06d>"`` event ids.

    Three terms, each carrying its own weight:

    * ``robot_id`` — two agents never collide with each other.
    * ``epoch_ns`` — the node's start time in nanoseconds. This is what
      makes an agent *restart* produce fresh ids instead of replaying
      ``:000001`` on top of its own pre-restart history, which a
      TRANSIENT_LOCAL subscriber may still be holding.
    * ``counter`` — a per-event sequence rather than the task id. A task
      that is interrupted and re-auctioned keeps its ``task_id``, so
      keying on the task would make the second attempt look like a
      duplicate of the first and its mass would be silently dropped.

    The counter is zero-padded to six digits for readability only; it is
    not truncated at 999999 and ids stay unique past that width.
    """

    def __init__(self, robot_id: str, epoch_ns: int):
        self._robot_id = str(robot_id)
        self._epoch_ns = int(epoch_ns)
        self._counter = 0

    def next(self) -> str:
        """Return the next id. Never returns the same string twice."""
        self._counter += 1
        return f"{self._robot_id}:{self._epoch_ns}:{self._counter:06d}"

    @property
    def count(self) -> int:
        """How many ids have been handed out. Test/diagnostic aid."""
        return self._counter


def build_material_event_fields(event_id: str, robot_id: str, task_id: str,
                                event_type: str, mass_kg: float,
                                residual_mass_kg: float) -> dict:
    """Validate one transfer and return the ``MaterialEvent`` field values.

    Returns a plain ``dict`` of field name -> value covering every
    ``MaterialEvent`` field **except** ``stamp``, which only the node can
    supply (``self.get_clock().now().to_msg()``).

    Raises ``ValueError`` on:

    * an ``event_type`` outside :data:`MATERIAL_EVENT_TYPES` — the
      orchestrator dispatches on this string, and an unrecognised value
      would be dropped there instead of here, where the caller can still
      be identified;
    * a non-finite mass. This is not defensiveness for its own sake:
      ``max(0.0, float('nan'))`` evaluates to ``0.0`` in Python (every
      comparison against NaN is False, so ``max`` returns its first
      argument), so a clamp written the obvious way would turn "this
      sensor could not be read" into "this transfer moved zero
      kilograms". The skills deliberately propagate NaN for an unread
      fill sensor, and the contract for that sentinel is *publish
      nothing* — see ``agent_node._publish_material_event``.

    A negative mass is clamped to 0.0 rather than rejected: ``mass_kg``
    is documented on the wire as ``>= 0``, and a small negative delta is
    the expected shape of sensor noise around an empty bin. A *large*
    negative delta is a real fault, and clamping hides it — the
    ``residual_mass_kg`` cross-check on the orchestrator side is what
    remains able to see that.
    """
    if event_type not in MATERIAL_EVENT_TYPES:
        raise ValueError(
            f"Unknown MaterialEvent.event_type {event_type!r}; "
            f"expected one of {MATERIAL_EVENT_TYPES}"
        )

    mass = float(mass_kg)
    residual = float(residual_mass_kg)
    for label, value in (('mass_kg', mass), ('residual_mass_kg', residual)):
        if not math.isfinite(value):
            raise ValueError(
                f"MaterialEvent.{label} is {value!r} for event {event_id!r} "
                f"({event_type} by {robot_id} on task {task_id}); a "
                f"non-finite mass means the fill sensor was never read and "
                f"the event must not be published at all"
            )

    return {
        'event_id': str(event_id),
        'robot_id': str(robot_id),
        'task_id': str(task_id),
        'event_type': str(event_type),
        'mass_kg': max(0.0, mass),
        'residual_mass_kg': max(0.0, residual),
    }
