"""Refuse a target that is off the map, before anything drives toward it.

WHY THE ORCHESTRATOR NEEDS THIS AT ALL
--------------------------------------
Fixing the frame (``selene_sim/selene_sim/world_frame.py``) stops the *planner*
from walking a robot off the terrain: survey waypoints, the extraction site and
the depot are now the world coordinates they always claimed to be. It does not
stop an operator. FR-DASH-5 lets an operator inject a task anywhere they click,
FR-DASH-6 lets them send a robot to any coordinate, and neither had any bound on
the number at all -- ``inject_task_logic`` validated ``task_type`` and
``quantity`` and passed ``target_location`` straight through.

Past the terrain edge there is no collision surface. A robot commanded there
drives off a 500 m heightfield and falls; the falling body's AABB eventually
leaves the integer range ODE's broadphase converts it into, and the whole
simulator aborts:

    ODE INTERNAL ERROR 1: assertion "aabbBound >= dMinIntExact &&
    aabbBound < dMaxIntExact" failed in collide() [collision_space.cpp:460]

measured by the operator three times on 2026-07-30/31. That is not one failed
task; it is every robot, every topic and the gate itself, gone at once. A typo
in a coordinate box should not be able to do that.

REFUSE, DO NOT CLAMP -- FOR THE OPERATOR PATH
---------------------------------------------
An operator is present and can be told. Clamping would accept the request and
then quietly do something else, which is the failure mode D-04 was opened for
(a quantity field that was collected and discarded). A refusal names the box and
the offending coordinate, lands in the ``TaskEventLog`` ring beside every other
operator action (D-05), and is rendered by the same toast the operator is
already looking at.

The AGENT clamps nothing either: ``AStarPlanner.plan`` refuses a goal outside
the same box (``selene_agent/selene_agent/navigator.py``). Two guards, and they
are not redundant -- this one exists to explain the refusal to a human at the
moment they can fix it, that one exists to catch every target the human did not
type.

WHERE THE NUMBERS COME FROM
---------------------------
Never from here. The extent is the terrain footprint, which four files already
state independently:

    selene_sim/models/lunar_terrain/heightmaps/terrain_datum.json  world_size_m
    selene_sim/models/lunar_terrain/model.sdf                      <size>500 500 ...
    selene_sim/config/world_params.yaml                world.bounds, safety_margin_m
    selene_agent/config/nav_params.yaml                grid_*, terrain_margin_m

``selene_sim/test/test_world_extent_agrees.py`` fails the build if any of them
drifts, which includes the two orchestrator parameters that feed the defaults
below. This module is the fifth statement of those numbers and it is only safe
because that test exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Half-width of the terrain, metres. ``<size>500 500 ...</size>`` centred on
#: the origin. Overridden by the ``terrain_half_extent_m`` parameter.
DEFAULT_TERRAIN_HALF_EXTENT_M: float = 250.0

#: Metres a target must keep clear of that edge. Derived in
#: ``selene_sim/config/world_params.yaml`` beside ``safety_margin_m``:
#: half a collision cell (1.95) + the largest robot's half-extent (0.59) +
#: ``PathFollower`` arrival slop (3.0) + slack.
DEFAULT_TERRAIN_MARGIN_M: float = 10.0


@dataclass(frozen=True)
class TerrainGuard:
    """The world box a commanded target must lie inside.

    Square and centred on the origin, because the terrain is: the heightmap
    generator's ``WORLD_SIZE`` is a single number and ``model.sdf`` declares
    ``<size>500 500 ...</size>`` with ``<pos>0 0 0</pos>``. A rectangular or
    off-centre world would need this to grow four fields; it is one because
    inventing a generality nothing configures is how a guard acquires a code
    path nobody ever exercises.
    """

    half_extent: float = DEFAULT_TERRAIN_HALF_EXTENT_M
    margin: float = DEFAULT_TERRAIN_MARGIN_M

    @property
    def limit(self) -> float:
        """The largest |x| or |y| a target may have."""
        return max(0.0, self.half_extent - self.margin)

    def contains(self, x: float, y: float) -> bool:
        """True when ``(x, y)`` is inside the safe box.

        A non-finite coordinate is OUTSIDE, checked explicitly. NaN compares
        false against everything so the naive form would reject it anyway, but
        by accident -- and a NaN target is exactly what produces the unbounded
        AABB this guard exists to prevent, so it is rejected on purpose.
        """
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        limit = self.limit
        return -limit <= x <= limit and -limit <= y <= limit

    def describe(self) -> str:
        """The box, for a rejection message an operator has to act on."""
        limit = self.limit
        return (
            f'x and y must both be within +/-{limit:.0f} m '
            f'({self.margin:.0f} m inside the {self.half_extent:.0f} m terrain '
            f'edge)'
        )

    def rejection(self, x: float, y: float, what: str) -> str:
        """One sentence saying what was refused and why. Never a bare 'invalid'.

        Names the coordinate back to the operator because the usual cause is a
        typo in one field, and an operator who is shown ``(-114, -2360)`` sees
        the extra digit immediately.
        """
        return (
            f'{what} target ({x:.1f}, {y:.1f}) is off the terrain: '
            f'{self.describe()}. Beyond the heightfield there is no ground — '
            f'the robot would fall and take the simulator down with it.'
        )


#: The shipped world, for callers that have no configuration to hand: unit
#: tests, and any context object built without an explicit guard. It is a real
#: guard rather than ``None`` on purpose — a guard that disables itself when
#: unconfigured is worse than no guard, because it reads as protection.
DEFAULT_TERRAIN_GUARD = TerrainGuard()
