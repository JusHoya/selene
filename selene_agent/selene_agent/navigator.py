"""Autonomous navigation stack for SELENE lunar robots.

Provides A* path planning over an occupancy grid, pure-pursuit path
following, and a Navigator facade that ties them together through the
HAL.  Importable without rclpy -- ROS integration is optional.

THE SLOPE LIMIT, AND WHY IT IS A PER-STEP RULE (deviation D-28)
--------------------------------------------------------------
``selene_agent/config/nav_params.yaml`` has declared
``navigation.max_traversable_slope_deg`` since Phase 2 and until 2026-08-01
NOTHING IN PRODUCTION READ IT -- the fifth instance of this repository's
"wired but never called" pattern. ``AStarPlanner`` already had a slope term,
``grid.get_cost(nx, ny) * self._slope_w``, but ``_cost_grid`` was allocated
all-zero and ``set_cost`` had exactly one caller repo-wide, a unit test. The
term was identically zero.

Two things are enforced here now, and they are DIFFERENT things:

  * A REFUSAL. An edge from cell A to cell B is refused when the grade ALONG
    THAT STEP, ``atan(|z_B - z_A| / step_length)``, exceeds the limit. So is a
    goal whose own cell is steeper than the limit, and so is a straight-line
    path simplification that would cross such a step.
  * A COST. Every cell carries ``slope / limit`` in ``_cost_grid``, so among
    admissible routes the planner prefers gentler ground. It never refuses on
    its own -- an expensive cell is still reachable.

PER STEP, NOT PER CELL, AND THE DIFFERENCE DECIDES THE MISSION. A vehicle only
climbs the terrain's fall line if it is pointed at it. A path crossing ground
of slope S at heading theta off the fall line climbs at
``atan(tan(S) * cos(theta))`` along its own direction of travel. The PSR
crater rim is a 34.02 deg minimax barrier, but a route >= 57.4 deg off its
fall line climbs at <= 20 deg for a 1.85x length penalty -- a switchback, and
how the fleet delivered 94.85 kg into that crater on 2026-07-31 while the
capability campaign says it cannot climb 34 deg.

MEASURED over this module's own 500 x 500 / 1.0 m lattice, 8-connected, on the
COLLISION heightmap (re-derived independently on 2026-08-01; the numbers below
are counts of cells mutually reachable from the recharge pad):

    rule                      10 deg      15 deg      20 deg
    per step  |dz|/len        237,727     248,606     250,000   depot: no/yes/yes
    per cell  gradient        depot UNREACHABLE at 10, 15, 20 and 25;
                              reachable only at 34

Enforcing the measured limit PER CELL would refuse the entire mission. That is
why the naive reading of the parameter is not the one implemented.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field as dataclass_field
from enum import IntEnum
from typing import Callable, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Occupancy Grid
# ---------------------------------------------------------------------------

class CellState(IntEnum):
    FREE = 0
    OCCUPIED = 1
    UNKNOWN = 2


#: Default metres a goal must keep clear of the grid edge. The grid spans the
#: terrain exactly (500 x 500 m at 1.0 m from -250, -250 --
#: ``selene_agent/config/nav_params.yaml``), so its edge IS the heightfield edge
#: and a goal on the last cell is a goal at the cliff. Overridden by
#: ``navigation.terrain_margin_m``; the derivation of the 10.0 m is in
#: ``selene_sim/config/world_params.yaml`` beside ``safety_margin_m``, and
#: ``selene_sim/test/test_world_extent_agrees.py`` fails the build if the two
#: files stop agreeing.
DEFAULT_TERRAIN_MARGIN_M: float = 10.0

#: Fall-line grade, degrees, that the fleet is permitted to take in one step.
#: Overridden by ``navigation.max_traversable_slope_deg``; the derivation and
#: everything the figure does NOT cover are in ``nav_params.yaml`` beside it.
DEFAULT_MAX_TRAVERSABLE_SLOPE_DEG: float = 20.0

#: Which of the two committed heightmaps the planner enforces against.
#:
#: ``'collision'`` -- the 129-sample surface a wheel actually contacts, and the
#: surface the Gazebo capability campaign of 2026-08-01 measured the limit ON.
#: Enforcing a limit measured on one surface against the slopes of a different,
#: rougher surface would be a units mismatch, so the two are kept the same.
#:
#: The choice is NOT load-bearing for whether the mission is possible: measured
#: 2026-08-01, a 20 deg per-step limit leaves 250,000 of 250,000 cells mutually
#: reachable on the collision layer and 248,915 on the 513-sample ``'visual'``
#: layer, with the depot, the recharge pad and all ten spawns connected in both.
#: It IS load-bearing at 15 deg, where collision connects the depot (248,606
#: cells) and visual does not (239,231, depot outside).
TERRAIN_LAYER: str = 'collision'


class OccupancyGrid:
    """2-D grid map used for path planning.

    Each cell stores an occupancy state and an optional traversal cost
    (e.g. slope penalty).  World coordinates are continuous (meters);
    grid coordinates are integer cell indices.

    IT ALSO CARRIES THE TERRAIN SAFE AREA. The grid's extent and the simulated
    terrain's extent are the same square, so this class already knows where the
    ground stops; ``terrain_margin`` is how far inside that edge a goal must
    stay. Past the edge there is no collision surface at all -- a robot falls,
    and the falling body's AABB eventually leaves the integer range ODE's
    broadphase converts it into, which aborts the simulator (register D-06's
    successor; see ``selene_sim/config/world_params.yaml``).

    Before 2026-07-31 this bound existed but was applied in the WRONG FRAME:
    every pose reaching the planner was dead-reckoned ``/odom``, so a goal that
    passed ``is_in_bounds`` in odom metres could be 200 m off the map in world
    metres. The frame fix (``selene_sim/selene_sim/world_frame.py``) is what
    makes this bound mean anything; the margin is what makes it survive
    ``PathFollower``'s 1.0 m arrival tolerance.
    """

    def __init__(
        self,
        width: int = 500,
        height: int = 500,
        resolution: float = 1.0,
        origin_x: float = -250.0,
        origin_y: float = -250.0,
        # DEFAULTS TO ZERO, and ``from_config`` defaults to
        # DEFAULT_TERRAIN_MARGIN_M instead. The margin is a property of the
        # DEPLOYMENT — how much of a real heightfield's edge to stay off — and
        # this constructor is a bare geometric object that unit tests build at
        # 20 x 20 m, where a 10 m inset leaves no admissible goal at all. Zero
        # is not "unguarded": the goal is still bounded by the grid extent,
        # which in the shipped configuration IS the terrain extent. Production
        # never reaches this default; every agent builds its grid through
        # ``from_config`` from ``selene_agent/config/nav_params.yaml``.
        terrain_margin: float = 0.0,
    ):
        self._width = width
        self._height = height
        self._resolution = resolution
        self._origin_x = origin_x
        self._origin_y = origin_y
        self._terrain_margin = max(0.0, float(terrain_margin))
        self._grid = np.zeros((height, width), dtype=np.int8)
        self._cost_grid = np.zeros((height, width), dtype=np.float32)
        # THE TERRAIN LAYER, absent until ``load_terrain`` supplies it.
        #
        # None is not "flat": every terrain query below answers "I do not know"
        # (NaN / not-a-refusal) rather than "fine", and the planner's slope
        # enforcement is inert without it. A grid that silently reported zero
        # slope because it had never been given a heightmap would reproduce
        # D-28 exactly -- a system that believes the ground is traversable
        # because it cannot see it.
        self._elevation: Optional[np.ndarray] = None
        self._slope_deg: Optional[np.ndarray] = None
        self._max_slope_deg: Optional[float] = None
        self._step_tan: Optional[float] = None

    # -- Coordinate transforms ------------------------------------------------

    def world_to_grid(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert world (meters) to grid cell indices."""
        gx = int((wx - self._origin_x) / self._resolution)
        gy = int((wy - self._origin_y) / self._resolution)
        return gx, gy

    def grid_to_world(self, gx: int, gy: int) -> tuple[float, float]:
        """Convert grid cell indices to the cell-centre world position."""
        wx = gx * self._resolution + self._origin_x + self._resolution / 2
        wy = gy * self._resolution + self._origin_y + self._resolution / 2
        return wx, wy

    # -- Cell access ----------------------------------------------------------

    def is_in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self._width and 0 <= gy < self._height

    # -- Terrain safe area ----------------------------------------------------

    def terrain_safe_area(self) -> tuple[float, float, float, float]:
        """``(x_min, x_max, y_min, y_max)`` in world metres, margin applied."""
        m = self._terrain_margin
        return (
            self._origin_x + m,
            self._origin_x + self._width * self._resolution - m,
            self._origin_y + m,
            self._origin_y + self._height * self._resolution - m,
        )

    def is_on_terrain(self, wx: float, wy: float) -> bool:
        """True when a world point is safely inside the terrain footprint.

        A non-finite coordinate is OUTSIDE, and checked explicitly rather than
        left to fall out of the comparisons: NaN compares false against
        everything, so the right answer would have been reached by accident, and
        a NaN target is precisely what produces the unbounded collision AABB
        this guard exists to prevent.
        """
        if not (math.isfinite(wx) and math.isfinite(wy)):
            return False
        x_min, x_max, y_min, y_max = self.terrain_safe_area()
        return x_min <= wx <= x_max and y_min <= wy <= y_max

    def get_cell(self, gx: int, gy: int) -> CellState:
        if not self.is_in_bounds(gx, gy):
            return CellState.UNKNOWN
        return CellState(self._grid[gy, gx])

    def set_cell(self, gx: int, gy: int, state: CellState) -> None:
        if self.is_in_bounds(gx, gy):
            self._grid[gy, gx] = int(state)

    def get_cost(self, gx: int, gy: int) -> float:
        if not self.is_in_bounds(gx, gy):
            return float("inf")
        return float(self._cost_grid[gy, gx])

    def set_cost(self, gx: int, gy: int, cost: float) -> None:
        if self.is_in_bounds(gx, gy):
            self._cost_grid[gy, gx] = cost

    # -- Terrain layer (deviation D-28) ---------------------------------------

    def load_terrain(self, lattice, max_slope_deg: float) -> None:
        """Attach an elevation/slope field and the limit enforced against it.

        *lattice* is a ``selene_agent.terrain_slope.SlopeLattice`` -- duck-typed
        on ``width`` / ``height`` / ``resolution`` / ``origin_x`` / ``origin_y``
        / ``elevation_m`` / ``slope_deg`` so this module keeps no import of the
        terrain reader and a test can hand in a synthetic field.

        THE GEOMETRY IS CHECKED, NOT ASSUMED. A lattice on a different origin or
        resolution would index cleanly and answer about the wrong place, which
        is the D-33 defect (a pose read in the wrong frame) with the terrain
        instead of the robot. It raises rather than resampling.

        Two things are written and they are used for different decisions:

          * ``_elevation``  -> the PER-STEP refusal. ``atan(|dz| / step_length)``
            between two adjacent cells is the grade along the direction of
            travel, which is what a vehicle actually climbs.
          * ``_cost_grid``  -> the existing A* slope term, as ``slope / limit``:
            0 on the flat, 1.0 at the limit, ~1.7 on the 34 deg crater rim.
            FINITE EVERYWHERE, deliberately. Making an over-limit cell infinite
            would turn the cost into a second, per-cell refusal, and a per-cell
            refusal at the measured limit disconnects the depot from every spawn
            (measured 2026-08-01: unreachable at 10, 15, 20 and 25 deg).
        """
        limit = float(max_slope_deg)
        if not (math.isfinite(limit) and limit > 0.0):
            raise ValueError(
                f'max_slope_deg must be finite and positive, got {limit!r}')

        for name, mine, theirs in (
            ('width', self._width, int(lattice.width)),
            ('height', self._height, int(lattice.height)),
        ):
            if mine != theirs:
                raise ValueError(
                    f'terrain lattice {name} is {theirs}, this grid is {mine}; '
                    f'the two must describe the same cells')
        for name, mine, theirs in (
            ('resolution', self._resolution, float(lattice.resolution)),
            ('origin_x', self._origin_x, float(lattice.origin_x)),
            ('origin_y', self._origin_y, float(lattice.origin_y)),
        ):
            if abs(mine - theirs) > 1e-9:
                raise ValueError(
                    f'terrain lattice {name} is {theirs}, this grid is {mine}; '
                    f'the two must describe the same square')

        elevation = np.array(lattice.elevation_m, dtype=np.float64, copy=True)
        slope = np.array(lattice.slope_deg, dtype=np.float64, copy=True)
        for name, array in (('elevation', elevation), ('slope', slope)):
            if array.shape != (self._height, self._width):
                raise ValueError(
                    f'terrain {name} is {array.shape}, expected '
                    f'{(self._height, self._width)}')

        self._elevation = elevation
        self._slope_deg = slope
        self._max_slope_deg = limit
        self._step_tan = math.tan(math.radians(limit))
        self._cost_grid[:] = (slope / limit).astype(np.float32)

    @property
    def has_terrain(self) -> bool:
        """True once ``load_terrain`` has supplied an elevation field."""
        return self._elevation is not None

    @property
    def max_slope_deg(self) -> Optional[float]:
        """The enforced limit in degrees, or ``None`` when no terrain is loaded."""
        return self._max_slope_deg

    def elevation(self, gx: int, gy: int) -> float:
        """World z at a cell centre. ``nan`` off the grid or with no terrain.

        NaN rather than 0.0 because a caller comparing an unknown elevation
        against anything must get an answer that propagates as unknown, not one
        that reads as sea level.
        """
        if self._elevation is None or not self.is_in_bounds(gx, gy):
            return float('nan')
        return float(self._elevation[gy, gx])

    def cell_slope_deg(self, gx: int, gy: int) -> float:
        """Terrain gradient of one cell, degrees. ``nan`` when unknown.

        This is the PER-CELL reading -- the steepest slope at that spot in any
        direction. It is used for the GOAL check (a robot has to stop, work and
        start again there, in whatever attitude the ground gives it) and NOT for
        deciding whether a route may cross the cell. See ``step_grade_deg``.
        """
        if self._slope_deg is None or not self.is_in_bounds(gx, gy):
            return float('nan')
        return float(self._slope_deg[gy, gx])

    def step_grade_deg(self, ax: int, ay: int, bx: int, by: int) -> float:
        """Grade in degrees along the step from cell A to cell B.

        ``atan(|z_B - z_A| / step_length)``, where *step_length* is the true
        centre-to-centre distance, so a diagonal is measured over 1.414 cells
        and not over 1. Sign is dropped: a descent this steep is refused too,
        and the campaign measured descent limits (25 deg) close to the ascent
        limits (20 deg) rather than far above them.

        ``nan`` when no terrain is loaded or either cell is off the grid.
        """
        za = self.elevation(ax, ay)
        zb = self.elevation(bx, by)
        if not (math.isfinite(za) and math.isfinite(zb)):
            return float('nan')
        run = math.hypot(bx - ax, by - ay) * self._resolution
        if run <= 0.0:
            return 0.0
        return math.degrees(math.atan(abs(zb - za) / run))

    def is_step_traversable(self, ax: int, ay: int, bx: int, by: int) -> bool:
        """Whether the step A -> B is inside the loaded limit.

        TRUE WHEN NO TERRAIN IS LOADED. This is a guard, and a guard that
        refuses everything it cannot see would stop every unit test that builds
        a bare 20 x 20 grid, and would strand a fleet whose heightmap failed to
        install. The loud version of that failure lives at the load site --
        ``from_config`` raises rather than continuing without terrain -- which
        is the right place for it, because there a human can be told which file
        is missing.
        """
        if self._elevation is None or self._step_tan is None:
            return True
        za = self.elevation(ax, ay)
        zb = self.elevation(bx, by)
        if not (math.isfinite(za) and math.isfinite(zb)):
            return False
        run = math.hypot(bx - ax, by - ay) * self._resolution
        if run <= 0.0:
            return True
        return abs(zb - za) / run <= self._step_tan

    def navigable_mask(self) -> np.ndarray:
        """Boolean ``[gy, gx]`` of cells that are not OCCUPIED.

        The occupancy half of "can a robot be here"; the slope half is per-step
        and therefore a property of edges, not of this array. Used by the
        startup reachability audit.
        """
        return self._grid != int(CellState.OCCUPIED)

    # -- Obstacle helpers -----------------------------------------------------

    def mark_obstacle_circle(self, wx: float, wy: float, radius: float) -> None:
        """Mark all cells whose centres are within *radius* of (*wx*, *wy*)
        as OCCUPIED."""
        cx, cy = self.world_to_grid(wx, wy)
        r_cells = int(math.ceil(radius / self._resolution))
        for dy in range(-r_cells, r_cells + 1):
            for dx in range(-r_cells, r_cells + 1):
                gx = cx + dx
                gy = cy + dy
                if not self.is_in_bounds(gx, gy):
                    continue
                cell_wx, cell_wy = self.grid_to_world(gx, gy)
                dist = math.hypot(cell_wx - wx, cell_wy - wy)
                if dist <= radius:
                    self._grid[gy, gx] = int(CellState.OCCUPIED)

    # -- Factory --------------------------------------------------------------

    @classmethod
    def from_config(cls, config: dict,
                    heightmap_dir: Optional[str] = None) -> "OccupancyGrid":
        """Build an OccupancyGrid from a nav-params config dict.

        Expected keys under ``config["navigation"]``:
            grid_width, grid_height, grid_resolution, origin_x, origin_y

        Optional ``config["static_obstacles"]["rocks"]`` list of
        ``{x, y, radius}`` dicts.  An inflation radius is added from
        ``config["navigation"]["obstacle_inflation_radius"]``.

        THE TERRAIN IS LOADED IFF ``navigation.max_traversable_slope_deg`` IS
        PRESENT, and its absence is the only way to get a grid with no terrain.
        That coupling is deliberate: the key is the whole reason the terrain is
        read, so "there is a limit but no ground to apply it to" is not a state
        this factory can produce. The shipped ``nav_params.yaml`` carries the
        key, so every production agent gets terrain; the unit tests that build
        20 x 20 m grids from a bare geometry dict do not, and their planner
        behaves exactly as it did before D-28.

        IT RAISES RATHER THAN CONTINUING FLAT. ``TerrainDataUnavailable`` from
        the heightmap search propagates untouched. A silent fallback here would
        make every slope zero and every route admissible -- which is not a
        degraded mode, it is D-28 with extra steps, and it would look identical
        to a working system right up until a hauler pinned on a wall.
        """
        nav = config.get("navigation", config)
        grid = cls(
            width=int(nav.get("grid_width", 500)),
            height=int(nav.get("grid_height", 500)),
            resolution=float(nav.get("grid_resolution", 1.0)),
            origin_x=float(nav.get("origin_x", -250.0)),
            origin_y=float(nav.get("origin_y", -250.0)),
            terrain_margin=float(
                nav.get("terrain_margin_m", DEFAULT_TERRAIN_MARGIN_M)),
        )
        inflation = float(nav.get("obstacle_inflation_radius", 0.5))

        rocks = config.get("static_obstacles", {}).get("rocks", [])
        for rock in rocks:
            grid.mark_obstacle_circle(
                rock["x"], rock["y"], rock["radius"] + inflation,
            )

        limit = nav.get("max_traversable_slope_deg")
        if limit is not None:
            # Imported here, not at module scope: ``terrain_slope`` pulls in the
            # PNG decoder and locates the committed heightmap, and this module
            # must stay importable by anything that only wants PathFollower.
            from selene_agent.terrain_slope import TerrainSlopeField
            field = TerrainSlopeField.load(heightmap_dir=heightmap_dir,
                                           layer=TERRAIN_LAYER)
            grid.load_terrain(field.resample_to_grid(grid), float(limit))
        return grid

    # -- Properties -----------------------------------------------------------

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def resolution(self) -> float:
        return self._resolution

    @property
    def origin_x(self) -> float:
        return self._origin_x

    @property
    def origin_y(self) -> float:
        return self._origin_y


# ---------------------------------------------------------------------------
# A* Planner
# ---------------------------------------------------------------------------

@dataclass
class PlanResult:
    path: list[tuple[float, float]]
    cost: float
    success: bool
    failure_reason: str = ""


class AStarPlanner:
    """A* path planner on an 8-connected OccupancyGrid.

    ``slope_penalty_weight`` multiplies the per-cell terrain cost the grid
    carries (``slope / limit``, see ``OccupancyGrid.load_terrain``). It biases
    the route toward gentler ground; it never refuses one. The refusal is the
    separate per-step rule in ``_get_neighbors`` and ``_line_of_sight``.

    ``hazard_penalty_weight`` USED TO BE A SECOND CONSTRUCTOR ARGUMENT and is
    deleted rather than defaulted. It was assigned to ``self._hazard_w`` and
    read by nothing, and ``nav_params.yaml`` carried a value for it that reached
    no constructor -- the same "wired but never called" shape as D-28 itself,
    one frame smaller. Keeping it as an ignored keyword would preserve exactly
    the property that made it worthless: something an operator can set that does
    nothing. There is no hazard layer to weight; when there is one, it can be
    added back with a reader.
    """

    SQRT2 = 1.4142135623730951

    def __init__(
        self,
        grid: OccupancyGrid,
        slope_penalty_weight: float = 2.0,
    ):
        self._grid = grid
        self._slope_w = float(slope_penalty_weight)

    # -- Public ---------------------------------------------------------------

    def plan(
        self,
        start_xy: tuple[float, float],
        goal_xy: tuple[float, float],
    ) -> PlanResult:
        """Compute a path from *start_xy* to *goal_xy* in world coords."""
        grid = self._grid
        sx, sy = grid.world_to_grid(*start_xy)
        gx, gy = grid.world_to_grid(*goal_xy)

        # Quick checks
        if not grid.is_in_bounds(sx, sy):
            return PlanResult([], 0.0, False, "start out of bounds")
        if not grid.is_in_bounds(gx, gy):
            return PlanResult([], 0.0, False, "goal out of bounds")

        # THE TERRAIN GUARD, and it sits here because this is the single choke
        # point every commanded motion passes through: Navigator.plan_to() calls
        # it for every skill, for the recharge path and for an operator
        # send_to_location. Refusing rather than clamping, because a plan the
        # caller did not ask for is worse than a named failure the FSM already
        # knows how to handle -- plan_to returns PlanResult.success False and
        # the agent retries or fails the task, with the reason in the log.
        #
        # It is a SECOND line of defence: the orchestrator refuses an
        # out-of-terrain target when the operator injects it, where there is a
        # human to tell. This one catches everything else -- a stale target, a
        # future planner, a NaN -- because past the terrain edge there is no
        # collision surface and the resulting fall aborts the whole simulator,
        # not just the task.
        if not grid.is_on_terrain(*goal_xy):
            x_min, x_max, y_min, y_max = grid.terrain_safe_area()
            return PlanResult(
                [], 0.0, False,
                f"goal ({goal_xy[0]:.1f}, {goal_xy[1]:.1f}) is outside the "
                f"terrain safe area x [{x_min:.1f}, {x_max:.1f}] "
                f"y [{y_min:.1f}, {y_max:.1f}]; driving there would take the "
                f"robot off the heightfield",
            )
        if grid.get_cell(sx, sy) == CellState.OCCUPIED:
            return PlanResult([], 0.0, False, "start is occupied")
        if grid.get_cell(gx, gy) == CellState.OCCUPIED:
            return PlanResult([], 0.0, False, "goal is occupied")

        # THE GOAL SLOPE GUARD, and it is PER CELL where the edge rule below is
        # per step. That is not an inconsistency, it is the difference between
        # crossing ground and stopping on it. A route may traverse a 34 deg wall
        # by switchbacking across it, because the grade along the direction of
        # travel is what a vehicle climbs; but a GOAL is somewhere a robot has
        # to arrive, hold station, run a skill and start again, in whatever
        # attitude the ground gives it, with no choice of heading left. The
        # steepest slope at that spot is the right quantity there.
        #
        # It catches two coordinates that were shipped for four phases:
        # nav_params.yaml's first prospect waypoint at (-60, -120), on 37.24 deg
        # ground, and its mission.recharge_position at (-75, -100), on 33.91
        # (both SAMPLING_RESAMPLED on the collision layer, measured 2026-08-01).
        # Both are now fixed at source; this is what would have said so.
        goal_slope = grid.cell_slope_deg(gx, gy)
        limit = grid.max_slope_deg
        if limit is not None and math.isfinite(goal_slope) and goal_slope > limit:
            return PlanResult(
                [], 0.0, False,
                f"goal ({goal_xy[0]:.1f}, {goal_xy[1]:.1f}) is on "
                f"{goal_slope:.1f} deg ground, over the "
                f"{limit:.1f} deg traversable limit; a robot could not stop, "
                f"work or set off again there",
            )

        # Trivial case
        if sx == gx and sy == gy:
            wx, wy = grid.grid_to_world(sx, sy)
            return PlanResult([(wx, wy)], 0.0, True)

        # A* search
        # open_set entries: (f, counter, gx, gy)
        counter = 0
        open_set: list[tuple[float, int, int, int]] = []
        h0 = self._heuristic(sx, sy, gx, gy)
        heapq.heappush(open_set, (h0, counter, sx, sy))
        counter += 1

        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g_score: dict[tuple[int, int], float] = {(sx, sy): 0.0}
        closed: set[tuple[int, int]] = set()

        while open_set:
            _f, _cnt, cx, cy = heapq.heappop(open_set)

            if (cx, cy) in closed:
                continue
            closed.add((cx, cy))

            if cx == gx and cy == gy:
                # Reconstruct
                grid_path = self._reconstruct_path(came_from, (cx, cy))
                world_path = [grid.grid_to_world(p[0], p[1]) for p in grid_path]
                world_path = self._simplify_path(world_path)
                return PlanResult(world_path, g_score[(cx, cy)], True)

            for nx, ny, move_cost in self._get_neighbors(cx, cy):
                if (nx, ny) in closed:
                    continue
                cost = g_score[(cx, cy)] + move_cost + grid.get_cost(nx, ny) * self._slope_w
                if cost < g_score.get((nx, ny), float("inf")):
                    g_score[(nx, ny)] = cost
                    came_from[(nx, ny)] = (cx, cy)
                    f = cost + self._heuristic(nx, ny, gx, gy)
                    heapq.heappush(open_set, (f, counter, nx, ny))
                    counter += 1

        return PlanResult([], 0.0, False, "no path found")

    # -- Internals ------------------------------------------------------------

    def _heuristic(self, gx1: int, gy1: int, gx2: int, gy2: int) -> float:
        return math.hypot(gx2 - gx1, gy2 - gy1)

    def _get_neighbors(self, gx: int, gy: int) -> list[tuple[int, int, float]]:
        """Return reachable 8-connected neighbours with move costs.

        Diagonal moves are allowed only when both adjacent cardinal
        cells are free (no corner-cutting through obstacles).

        THE PER-STEP SLOPE REFUSAL LIVES HERE (D-28). Every edge is tested with
        ``OccupancyGrid.is_step_traversable`` -- ``|dz| / step_length`` against
        ``tan(limit)`` -- so a neighbour on ground the vehicle cannot climb
        FROM HERE simply is not a neighbour. Two consequences worth naming:

          * The refusal is directional, so a robot that finds itself ON a 34 deg
            wall is not stranded: steps along the contour are admissible even
            though steps up the fall line are not. That is deliberate. A guard
            that refused to plan out of a bad position would convert a recovery
            into a fault.
          * ``cardinal_free`` still means "not occupied", not "not occupied and
            climbable". Corner-cutting is an obstacle rule about clipping the
            corner of a rock; the diagonal's own grade is tested on its own
            edge, which is the step the robot actually drives.
        """
        grid = self._grid
        neighbors: list[tuple[int, int, float]] = []

        cardinal = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        diagonal = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

        # Cardinal
        cardinal_free: dict[tuple[int, int], bool] = {}
        for dx, dy in cardinal:
            nx, ny = gx + dx, gy + dy
            free = (grid.is_in_bounds(nx, ny)
                    and grid.get_cell(nx, ny) != CellState.OCCUPIED)
            cardinal_free[(dx, dy)] = free
            if free and grid.is_step_traversable(gx, gy, nx, ny):
                neighbors.append((nx, ny, 1.0))

        # Diagonal -- only if both adjacent cardinals are free
        for dx, dy in diagonal:
            nx, ny = gx + dx, gy + dy
            if not grid.is_in_bounds(nx, ny):
                continue
            if grid.get_cell(nx, ny) == CellState.OCCUPIED:
                continue
            if not cardinal_free.get((dx, 0), False):
                continue
            if not cardinal_free.get((0, dy), False):
                continue
            if not grid.is_step_traversable(gx, gy, nx, ny):
                continue
            neighbors.append((nx, ny, self.SQRT2))

        return neighbors

    def _reconstruct_path(
        self,
        came_from: dict[tuple[int, int], tuple[int, int]],
        current: tuple[int, int],
    ) -> list[tuple[int, int]]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    def _simplify_path(
        self, path: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """Line-of-sight simplification using Bresenham cell checks.

        A SHORTCUT MUST NOT INCREASE THE PLANNER'S OWN COST, and that condition
        is new with D-28. Without it the slope COST term is real inside the
        search and then discarded on the way out: A* pays a detour to stay off
        19 degree ground, ``_line_of_sight`` finds the direct line perfectly
        drivable -- because it is, the slope cost never refuses anything -- and
        the simplifier puts the robot straight back on the ground the search had
        just bought its way off. Measured on a fixture where a 19 degree
        corridor runs start to goal: the detour A* chose was collapsed back onto
        it and the two weights produced identical paths.

        So each candidate shortcut is priced with the SAME cost function the
        search used -- distance plus ``slope_penalty_weight`` times the terrain
        cost of every cell entered -- and taken only if it is no dearer than the
        run of path it replaces.

        THIS CHANGES NOTHING WITHOUT TERRAIN. Every terrain cost is zero on a
        grid that has none, and a straight segment is never longer than an
        8-connected path between the same two cells, so every shortcut the old
        code took is still taken. That is what keeps the pre-D-28 planner tests
        meaningful rather than merely passing.
        """
        if len(path) <= 2:
            return path

        cells = [self._grid.world_to_grid(wx, wy) for wx, wy in path]
        simplified: list[tuple[float, float]] = [path[0]]
        anchor = 0

        while anchor < len(path) - 1:
            farthest = anchor + 1
            running = self._step_cost(cells[anchor], cells[anchor + 1])
            for probe in range(anchor + 2, len(path)):
                running += self._step_cost(cells[probe - 1], cells[probe])
                if not self._line_of_sight(path[anchor], path[probe]):
                    break
                if self._segment_cost(cells[anchor], cells[probe]) > running + 1e-9:
                    break
                farthest = probe
            simplified.append(path[farthest])
            anchor = farthest

        return simplified

    def _step_cost(self, a: tuple[int, int], b: tuple[int, int]) -> float:
        """What the search charged for the single step ``a -> b``."""
        move = math.hypot(b[0] - a[0], b[1] - a[1])
        return move + self._grid.get_cost(b[0], b[1]) * self._slope_w

    def _segment_cost(self, a: tuple[int, int], b: tuple[int, int]) -> float:
        """What a straight drive from cell *a* to cell *b* would cost.

        Euclidean distance plus the weighted terrain cost of every cell the line
        enters. The robot does not stop at those cell centres, but it passes
        over them, and charging each one is the same approximation the search
        makes -- which is what makes the two numbers comparable at all.
        """
        x0, y0 = a
        x1, y1 = b
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        terrain = 0.0
        while not (x0 == x1 and y0 == y1):
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
            terrain += self._grid.get_cost(x0, y0)
        return math.hypot(b[0] - a[0], b[1] - a[1]) + terrain * self._slope_w

    def _line_of_sight(
        self, p1: tuple[float, float], p2: tuple[float, float]
    ) -> bool:
        """Whether a straight line between two world points is drivable.

        Bresenham over the cells it crosses, refusing an OCCUPIED cell and --
        since D-28 -- refusing any step between consecutive cells that exceeds
        the terrain limit.

        THE SLOPE HALF IS NOT OPTIONAL AND IT IS EASY TO MISS. This is called
        only from ``_simplify_path``, which replaces a run of A* cells with a
        straight segment the PathFollower then drives. Without the slope test
        the search would refuse to climb a wall and the simplifier would
        immediately straighten the switchback back across it -- the guard would
        be perfectly implemented, fully tested at the search level, and defeated
        by the line after it. ``test_navigator_slope_enforcement.py`` mutates
        exactly this: dropping the check re-admits the shortcut.

        The Bresenham loop below can advance x and y in the same iteration, so
        consecutive visited cells are one cardinal OR one diagonal step apart --
        the same set of steps ``_get_neighbors`` offers, measured over the same
        centre-to-centre distances.
        """
        grid = self._grid
        x0, y0 = grid.world_to_grid(*p1)
        x1, y1 = grid.world_to_grid(*p2)

        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            if grid.get_cell(x0, y0) == CellState.OCCUPIED:
                return False
            if x0 == x1 and y0 == y1:
                break
            px, py = x0, y0
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
            if not grid.is_step_traversable(px, py, x0, y0):
                return False

        return True


# ---------------------------------------------------------------------------
# Path Follower  (pure-pursuit style)
# ---------------------------------------------------------------------------

#: ``nav_params.yaml`` key -> ``PathFollower`` constructor argument.
#:
#: THE WHOLE ``path_follower:`` BLOCK HAD NO READER. ``Navigator`` built its
#: ``PathFollower`` with the constructor's own defaults, so all six keys were
#: settable and inert -- the same shape as D-28 and D-13, six names at once.
#:
#: The mapping is EXPLICIT because one name does not survive a mechanical
#: translation: the file says ``stall_timeout_s`` and the constructor says
#: ``stall_timeout``. A ``**block`` splat would have raised TypeError on that
#: one key and silently accepted a typo in any of the other five.
#:
#: WIRING THIS CHANGES NO BEHAVIOUR TODAY, by construction: every value in the
#: shipped file is identical to the constructor default it now overrides
#: (2.0 / 1.0 / 0.5 / 1.5 / 1.0 / 5.0). That is asserted, not asserted about, by
#: ``test_nav_params_are_read.py`` -- so this is the D-13 argument again, and the
#: point is that editing one of those numbers now does something.
PATH_FOLLOWER_KEYS: dict[str, str] = {
    'lookahead_distance': 'lookahead_distance',
    'waypoint_tolerance': 'waypoint_tolerance',
    'linear_kp': 'linear_kp',
    'angular_kp': 'angular_kp',
    'max_angular_speed': 'max_angular_speed',
    'stall_timeout_s': 'stall_timeout',
}


def path_follower_kwargs(config: Optional[dict]) -> dict:
    """Translate a ``path_follower:`` config block into constructor kwargs.

    Unknown keys RAISE. A ``path_follower:`` block whose author misspelled
    ``waypoint_tolerence`` would otherwise be a knob that silently does nothing,
    which is the defect this function exists to remove; catching it at agent
    start, by name, is the whole value of reading the block at all.

    A missing key is not an error -- it means "use the default" -- so the block
    stays optional and a caller with no config gets today's behaviour.
    """
    if not config:
        return {}
    unknown = sorted(set(config) - set(PATH_FOLLOWER_KEYS))
    if unknown:
        raise KeyError(
            f"unknown path_follower key(s): {', '.join(unknown)}. Known keys "
            f"are {', '.join(sorted(PATH_FOLLOWER_KEYS))}. A key nothing reads "
            f"is a knob that does nothing; fix the spelling or delete it.")
    return {PATH_FOLLOWER_KEYS[key]: float(value)
            for key, value in config.items()}


class PathFollowerStatus:
    FOLLOWING = "following"
    GOAL_REACHED = "goal_reached"
    NO_PATH = "no_path"
    STALLED = "stalled"


class PathFollower:
    """Steers a robot along a waypoint list using pure-pursuit logic.

    Reads odometry and commands velocity through the HAL interfaces
    supplied at construction time.
    """

    def __init__(
        self,
        drive_actuator,
        odometry_sensor,
        kinematics,
        lookahead_distance: float = 2.0,
        waypoint_tolerance: float = 1.0,
        linear_kp: float = 0.5,
        angular_kp: float = 1.5,
        max_angular_speed: float = 1.0,
        stall_timeout: float = 5.0,
    ):
        self._drive = drive_actuator
        self._odom = odometry_sensor
        self._kinematics = kinematics
        self._lookahead = lookahead_distance
        self._wp_tol = waypoint_tolerance
        self._lin_kp = linear_kp
        self._ang_kp = angular_kp
        self._max_ang = max_angular_speed
        self._stall_timeout = stall_timeout

        self._path: list[tuple[float, float]] = []
        self._target_idx: int = 0
        self._stall_timer: float = 0.0
        self._velocity_threshold: float = 0.01  # m/s for stall detect

    # -- Public ---------------------------------------------------------------

    def set_path(self, path: list[tuple[float, float]]) -> None:
        self._path = list(path)
        self._target_idx = 0
        self._stall_timer = 0.0

    def update(self, dt: float) -> str:
        """Advance the follower by *dt* seconds.  Returns a status string."""
        if not self._path:
            return PathFollowerStatus.NO_PATH

        # Read current pose
        odom = self._odom.read()
        rx, ry, rtheta = odom.x, odom.y, odom.theta

        # Advance target index past waypoints already reached
        while self._target_idx < len(self._path) - 1:
            wx, wy = self._path[self._target_idx]
            if math.hypot(wx - rx, wy - ry) < self._wp_tol:
                self._target_idx += 1
            else:
                break

        # Find lookahead point
        tx, ty = self._find_lookahead(rx, ry)

        # Check if final goal is reached
        gx, gy = self._path[-1]
        dist_to_goal = math.hypot(gx - rx, gy - ry)
        if dist_to_goal < self._wp_tol:
            self._drive.command_velocity(0.0, 0.0)
            return PathFollowerStatus.GOAL_REACHED

        # Heading error
        desired_heading = math.atan2(ty - ry, tx - rx)
        heading_error = self._wrap_angle(desired_heading - rtheta)

        # Speed modulation based on heading error
        abs_err = abs(heading_error)
        if abs_err > math.radians(45):
            speed_scale = 0.3
        elif abs_err > math.radians(22.5):
            speed_scale = 0.7
        else:
            speed_scale = 1.0

        max_speed = self._kinematics.get_max_speed()
        linear_vel = self._lin_kp * dist_to_goal * speed_scale
        linear_vel = min(linear_vel, max_speed)

        angular_vel = self._ang_kp * heading_error
        angular_vel = max(-self._max_ang, min(self._max_ang, angular_vel))

        self._drive.command_velocity(linear_vel, angular_vel)

        # Stall detection
        speed = math.hypot(odom.linear_velocity, 0.0)
        if speed < self._velocity_threshold and dist_to_goal > self._wp_tol:
            self._stall_timer += dt
            if self._stall_timer >= self._stall_timeout:
                self._drive.command_velocity(0.0, 0.0)
                return PathFollowerStatus.STALLED
        else:
            self._stall_timer = 0.0

        return PathFollowerStatus.FOLLOWING

    def get_distance_to_goal(self) -> float:
        if not self._path:
            return 0.0
        odom = self._odom.read()
        gx, gy = self._path[-1]
        return math.hypot(gx - odom.x, gy - odom.y)

    def is_goal_reached(self) -> bool:
        if not self._path:
            return False
        odom = self._odom.read()
        gx, gy = self._path[-1]
        return math.hypot(gx - odom.x, gy - odom.y) < self._wp_tol

    def stop(self) -> None:
        self._drive.command_velocity(0.0, 0.0)

    def get_current_target_index(self) -> int:
        return self._target_idx

    # -- Internals ------------------------------------------------------------

    def _find_lookahead(self, rx: float, ry: float) -> tuple[float, float]:
        """Return the lookahead point on the path ahead of the robot."""
        # Walk forward from current target to find a point at lookahead dist
        for i in range(self._target_idx, len(self._path)):
            wx, wy = self._path[i]
            if math.hypot(wx - rx, wy - ry) >= self._lookahead:
                return wx, wy
        # Fall back to the last waypoint
        return self._path[-1]

    @staticmethod
    def _wrap_angle(angle: float) -> float:
        """Wrap angle to [-pi, pi]."""
        while angle > math.pi:
            angle -= 2 * math.pi
        while angle < -math.pi:
            angle += 2 * math.pi
        return angle


# ---------------------------------------------------------------------------
# Navigator Facade
# ---------------------------------------------------------------------------

class NavigatorStatus:
    IDLE = "idle"
    NAVIGATING = "navigating"
    GOAL_REACHED = "goal_reached"
    REPLANNING = "replanning"
    BLOCKED = "blocked"


class Navigator:
    """High-level facade that ties planning and path-following together.

    Parameters
    ----------
    hal:
        A ``HalInterface`` instance for the robot.
    grid:
        The shared ``OccupancyGrid`` used for planning.
    ros_node:
        Optional ROS 2 node handle.  When ``None`` (test mode), ROS
        publishing is silently skipped.
    path_publisher:
        Optional pre-built ``nav_msgs/Path`` publisher used by
        ``publish_path()``.  Navigator deliberately does **not** create its
        own publisher: it has no access to the robot id, so any topic it
        created would be an unscoped relative name.  The owning node
        (``AgentNode``) creates the correctly scoped
        ``/<robot_id>/planned_path`` publisher and passes it in.  When
        ``None``, ``publish_path()`` is a no-op.
    slope_penalty_weight:
        Passed straight to ``AStarPlanner``.  IT HAS A CALLER NOW.  Until
        2026-08-01 this constructor built ``AStarPlanner(grid)`` with no
        arguments, so ``navigation.slope_penalty_weight`` in
        ``nav_params.yaml`` reached nothing -- a knob two levels removed from
        the code it named.  ``AgentNode`` now reads the key and passes it here.
    path_follower_config:
        The ``path_follower:`` block of ``nav_params.yaml``, or ``None`` for
        ``PathFollower``'s own defaults.  Six more keys that had no reader; see
        ``PATH_FOLLOWER_KEYS``.
    """

    MAX_REPLAN_ATTEMPTS = 3

    def __init__(self, hal, grid: OccupancyGrid, ros_node=None,
                 path_publisher=None,
                 slope_penalty_weight: float = 2.0,
                 path_follower_config: Optional[dict] = None):
        self._hal = hal
        self._grid = grid
        self._ros_node = ros_node
        self._path_pub = path_publisher
        self._planner = AStarPlanner(
            grid, slope_penalty_weight=slope_penalty_weight)
        self._follower = PathFollower(
            hal.get_actuator("drive"),
            hal.get_sensor("odometry"),
            hal.get_kinematics(),
            **path_follower_kwargs(path_follower_config),
        )
        self._current_path: list[tuple[float, float]] = []
        self._goal: Optional[tuple[float, float]] = None
        self._status: str = NavigatorStatus.IDLE
        self._replan_count: int = 0

    # -- Planning -------------------------------------------------------------

    def plan_to(self, goal_xy: tuple[float, float]) -> PlanResult:
        """Plan a path from the current pose to *goal_xy*."""
        odom = self._hal.get_sensor("odometry").read()
        if not odom.is_valid:
            return PlanResult([], 0.0, False, "odometry not yet available")
        start = (odom.x, odom.y)
        return self._planner.plan(start, goal_xy)

    # -- Following ------------------------------------------------------------

    def start_following(self, path: list[tuple[float, float]]) -> None:
        """Begin following a pre-computed path."""
        self._current_path = list(path)
        self._follower.set_path(path)
        self._status = NavigatorStatus.NAVIGATING
        self._replan_count = 0
        if path:
            self._goal = path[-1]
        self.publish_path()

    def update(self, dt: float) -> str:
        """Tick the navigation loop.  Returns the navigator status."""
        if self._status not in (NavigatorStatus.NAVIGATING,
                                NavigatorStatus.REPLANNING):
            return self._status

        result = self._follower.update(dt)

        if result == PathFollowerStatus.GOAL_REACHED:
            self._status = NavigatorStatus.GOAL_REACHED
        elif result == PathFollowerStatus.STALLED:
            self._status = NavigatorStatus.REPLANNING
            replan = self.replan()
            if not replan.success:
                self._status = NavigatorStatus.BLOCKED
        elif result == PathFollowerStatus.NO_PATH:
            self._status = NavigatorStatus.IDLE

        return self._status

    def replan(self) -> PlanResult:
        """Attempt to find a new path to the current goal."""
        if self._goal is None:
            return PlanResult([], 0.0, False, "no goal set")

        self._replan_count += 1
        if self._replan_count > self.MAX_REPLAN_ATTEMPTS:
            return PlanResult([], 0.0, False, "max replan attempts exceeded")

        result = self.plan_to(self._goal)
        if result.success:
            self._current_path = result.path
            self._follower.set_path(result.path)
            self._status = NavigatorStatus.NAVIGATING
            self.publish_path()
        return result

    # -- Control --------------------------------------------------------------

    def stop(self) -> None:
        self._follower.stop()
        self._status = NavigatorStatus.IDLE
        self._goal = None
        self._current_path = []

    # -- Queries --------------------------------------------------------------

    def get_current_pose(self) -> tuple[float, float, float]:
        odom = self._hal.get_sensor("odometry").read()
        return (odom.x, odom.y, odom.theta)

    def get_distance_to_goal(self) -> float:
        return self._follower.get_distance_to_goal()

    def get_remaining_path(self) -> list[tuple[float, float]]:
        if not self._current_path:
            return []
        idx = self._follower.get_current_target_index()
        return self._current_path[idx:]

    @property
    def status(self) -> str:
        return self._status

    # -- Obstacle update ------------------------------------------------------

    def update_obstacle(self, wx: float, wy: float, radius: float) -> None:
        """Mark a newly-detected obstacle on the shared grid."""
        self._grid.mark_obstacle_circle(wx, wy, radius)

    # -- ROS publishing (optional) --------------------------------------------

    def publish_path(self) -> None:
        """Publish the current path on the caller-supplied Path publisher.

        No-op when no ``path_publisher`` was supplied, when there is no ROS
        node (test mode), or when there is no path.  Navigator does not
        create the publisher itself — see the ``path_publisher`` parameter
        docs on ``__init__``.
        """
        if (self._ros_node is None or self._path_pub is None
                or not self._current_path):
            return
        try:
            from nav_msgs.msg import Path
            from geometry_msgs.msg import PoseStamped

            msg = Path()
            msg.header.frame_id = "map"
            now = self._ros_node.get_clock().now().to_msg()
            msg.header.stamp = now

            for wx, wy in self._current_path:
                ps = PoseStamped()
                ps.header.frame_id = "map"
                ps.header.stamp = now
                ps.pose.position.x = wx
                ps.pose.position.y = wy
                msg.poses.append(ps)

            self._path_pub.publish(msg)
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# Startup reachability audit  (deviation D-28 / D-32)
# ---------------------------------------------------------------------------

#: ``(dx, dy, centre-to-centre length in cells)`` for the eight steps
#: ``AStarPlanner._get_neighbors`` can offer. Kept beside the audit so the two
#: descriptions of "a step" cannot drift; ``test_navigator_slope_enforcement``
#: asserts the audit and the planner agree about which points are reachable.
_STEP_DIRECTIONS: tuple[tuple[int, int, float], ...] = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, AStarPlanner.SQRT2), (1, -1, AStarPlanner.SQRT2),
    (-1, 1, AStarPlanner.SQRT2), (-1, -1, AStarPlanner.SQRT2),
)


def _shift_views(array: np.ndarray, dx: int, dy: int):
    """``(source_view, destination_view)`` for a one-cell shift by (dx, dy).

    The pair lines up cell ``(y, x)`` with cell ``(y + dy, x + dx)`` over the
    overlap, so an elementwise op between them is the same op over every edge
    in that direction at once. Written out rather than using ``np.roll``, which
    wraps -- and a wrapped edge would connect the west rim of the map to the
    east one and report a world more connected than it is.
    """
    height, width = array.shape
    src = array[max(0, -dy):height - max(0, dy),
                max(0, -dx):width - max(0, dx)]
    dst = array[max(0, dy):height - max(0, -dy),
                max(0, dx):width - max(0, -dx)]
    return src, dst


def per_step_components(grid: OccupancyGrid) -> np.ndarray:
    """Label the navigable set under the PER-STEP slope rule.

    Returns an ``int64`` ``[gy, gx]`` array whose value is the smallest flat
    index in that cell's component, and ``-1`` where the cell is OCCUPIED. Two
    cells are in one component iff a chain of admissible single steps joins
    them -- exactly the edges ``AStarPlanner._get_neighbors`` offers.

    THIS IS NOT ``terrain_slope.ComponentLabels``. That one labels the per-CELL
    passable set (``slope <= limit``), which is a different and much more
    pessimistic question: measured 2026-08-01, the per-cell reading leaves the
    depot unreachable from every spawn at 10, 15, 20 AND 25 deg, while the
    per-step rule at 20 deg puts all 250,000 cells in ONE component. Both
    numbers are true; only one of them is the rule this planner enforces.

    HOW, AND WHAT IT COSTS. Iterated minimum-label propagation: every cell
    starts as its own label and repeatedly takes the smallest label among the
    neighbours it can step to, until nothing changes. Measured on the shipped
    500 x 500 lattice: 251 iterations and 2.0 s at 20 deg, 253 and 2.5 s at 15.
    It runs ONCE, at agent start. A BFS in Python costs about the same and a
    pointer-jumping union-find would be an order faster and considerably harder
    to read; this is a startup diagnostic, so the readable one wins.

    With no terrain loaded every step is admissible and the answer is the
    occupancy connectivity alone, which is the honest reading of "no limit is
    being enforced".
    """
    navigable = grid.navigable_mask()
    height, width = navigable.shape
    labels = np.where(
        navigable,
        np.arange(height * width, dtype=np.int64).reshape(height, width),
        -1,
    )

    admissible = []
    elevation = grid._elevation                      # noqa: SLF001 - same module
    step_tan = grid._step_tan                        # noqa: SLF001 - same module
    for dx, dy, length in _STEP_DIRECTIONS:
        src_ok, dst_ok = _shift_views(navigable, dx, dy)
        ok = src_ok & dst_ok
        if elevation is not None and step_tan is not None:
            src_z, dst_z = _shift_views(elevation, dx, dy)
            ok = ok & (np.abs(dst_z - src_z)
                       <= step_tan * length * grid.resolution)
        admissible.append((dx, dy, ok))

    while True:
        previous = labels.copy()
        for dx, dy, ok in admissible:
            src, dst = _shift_views(labels, dx, dy)
            np.minimum(dst, np.where(ok, src, dst), out=dst)
        if np.array_equal(labels, previous):
            return labels


@dataclass(frozen=True)
class ReachabilityAudit:
    """What the slope limit in force does to this robot's world.

    A REPORT AND NEVER A GATE. It cannot refuse to start an agent, and that is
    deliberate: the shipped terrain has been through three different beliefs
    about what is climbable in two days, and a startup check that aborted a
    fleet on the strength of arithmetic over a heightmap would be a worse
    failure than the one it guards against. It exists so that the FIRST time a
    hauler cannot get home, the reason is already in the log from before it set
    off -- rather than being reconstructed afterwards from a pinned robot's
    wheel odometry, which is how D-23 was found.
    """

    limit_deg: Optional[float]
    layer: str
    resolution: float
    total_cells: int
    occupied_cells: int
    over_limit_cells: int
    component_count: int
    start_xy: tuple[float, float]
    start_component_cells: int
    landmarks: dict = dataclass_field(default_factory=dict)
    landmark_reachable: dict = dataclass_field(default_factory=dict)

    @property
    def unreachable_landmarks(self) -> list[str]:
        return sorted(name for name, ok in self.landmark_reachable.items()
                      if not ok)

    def lines(self) -> list[str]:
        """The log block, one string per line. Prefixed so it greps."""
        if self.limit_deg is None:
            return [
                '[TERRAIN] NO TERRAIN IS LOADED and NO SLOPE LIMIT IS BEING '
                'ENFORCED. Every step is admissible, including one up a 34 deg '
                'crater wall. This is deviation D-28 and it is what the '
                'navigation.max_traversable_slope_deg key exists to prevent.',
            ]
        over_pct = 100.0 * self.over_limit_cells / max(self.total_cells, 1)
        marks = ' | '.join(
            f'{name} ({self.landmarks[name][0]:.1f}, '
            f'{self.landmarks[name][1]:.1f}): '
            f'{"REACHABLE" if self.landmark_reachable[name] else "NOT REACHABLE"}'
            for name in sorted(self.landmarks)) or '(none given)'
        return [
            f'[TERRAIN] slope limit {self.limit_deg:.1f} deg, enforced PER '
            f'STEP against the {self.layer!r} heightmap '
            f'(navigation.max_traversable_slope_deg).',
            f'[TERRAIN] {self.total_cells} cells at {self.resolution:.2f} m: '
            f'{self.over_limit_cells} ({over_pct:.1f}%) exceed the limit by '
            f'the per-CELL gradient reading, which is NOT the rule in force, '
            f'and {self.occupied_cells} are occupied by mapped obstacles.',
            f'[TERRAIN] under the per-STEP rule the navigable set is '
            f'{self.component_count} connected component(s); this robot starts '
            f'at ({self.start_xy[0]:.1f}, {self.start_xy[1]:.1f}) in one of '
            f'{self.start_component_cells} mutually reachable cells.',
            f'[TERRAIN] {marks}',
        ]

    def report(self, log: Callable[[str], None]) -> None:
        """Emit the block through *log* -- one call per line."""
        for line in self.lines():
            log(line)


def audit_terrain_reachability(
    grid: OccupancyGrid,
    start_xy: tuple[float, float],
    landmarks: Optional[dict] = None,
    layer: str = TERRAIN_LAYER,
) -> ReachabilityAudit:
    """Measure what the loaded limit excludes, and what this robot can reach.

    *landmarks* is ``{name: (x, y)}`` -- in production the depot and the
    recharge pad, i.e. the two places a robot MUST be able to get to for the
    mission to close. Naming them is the point: "3 components" is a statistic,
    "recharge_pad NOT REACHABLE" is an operator action.

    A start position off the grid is reported as its own component of zero
    cells with every landmark unreachable, rather than raising. This runs in a
    node constructor and an audit that can abort startup is a gate.
    """
    landmarks = dict(landmarks or {})
    height, width = grid.height, grid.width
    total = height * width
    occupied = int(np.count_nonzero(~grid.navigable_mask()))

    if not grid.has_terrain:
        return ReachabilityAudit(
            limit_deg=None, layer=layer, resolution=grid.resolution,
            total_cells=total, occupied_cells=occupied, over_limit_cells=0,
            component_count=0, start_xy=tuple(start_xy),
            start_component_cells=0, landmarks=landmarks,
            landmark_reachable={name: False for name in landmarks},
        )

    limit = float(grid.max_slope_deg)
    slope = grid._slope_deg                          # noqa: SLF001 - same module
    over_limit = int(np.count_nonzero(slope > limit))

    labels = per_step_components(grid)
    live = labels[labels >= 0]
    component_count = int(np.unique(live).size) if live.size else 0

    sx, sy = grid.world_to_grid(*start_xy)
    start_label = int(labels[sy, sx]) if grid.is_in_bounds(sx, sy) else -1
    start_cells = (int(np.count_nonzero(labels == start_label))
                   if start_label >= 0 else 0)

    reachable = {}
    for name, point in landmarks.items():
        gx, gy = grid.world_to_grid(point[0], point[1])
        reachable[name] = bool(
            start_label >= 0 and grid.is_in_bounds(gx, gy)
            and int(labels[gy, gx]) == start_label)

    return ReachabilityAudit(
        limit_deg=limit, layer=layer, resolution=grid.resolution,
        total_cells=total, occupied_cells=occupied,
        over_limit_cells=over_limit, component_count=component_count,
        start_xy=(float(start_xy[0]), float(start_xy[1])),
        start_component_cells=start_cells, landmarks=landmarks,
        landmark_reachable=reachable,
    )
