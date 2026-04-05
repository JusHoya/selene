"""Generate survey waypoints for the PSR zone."""

import math


def generate_psr_survey_waypoints(
    psr_center: tuple[float, float] = (-100.0, -150.0),
    psr_radius: float = 60.0,
    spacing: float = 20.0,
    margin: float = 5.0,
) -> list[tuple[float, float]]:
    """Generate hexagonal grid of prospect waypoints inside the PSR.

    Produces a honeycomb pattern of waypoints within a circular
    Permanently Shadowed Region (PSR), suitable for ice-prospecting
    survey missions. Waypoints are returned sorted by distance from
    the PSR center (closest first) so scouts spiral outward.

    Args:
        psr_center: (x, y) world coordinates of the PSR center in meters.
        psr_radius: Radius of the PSR circle in meters.
        spacing: Distance between adjacent waypoints in meters.
        margin: Inset from the PSR boundary to avoid edge effects.

    Returns:
        List of (x, y) tuples sorted by distance from center.
    """
    cx, cy = psr_center
    effective_radius = psr_radius - margin
    if effective_radius <= 0:
        return []

    waypoints = []

    # Hex grid: rows offset by spacing * sin(60deg)
    row_spacing = spacing * math.sin(math.radians(60))
    rows = int(2 * effective_radius / row_spacing) + 1

    for row in range(rows):
        y_offset = -effective_radius + row * row_spacing
        # Offset odd rows by half spacing for hexagonal packing
        x_shift = spacing / 2 if row % 2 == 1 else 0
        cols = int(2 * effective_radius / spacing) + 1

        for col in range(cols):
            x_offset = -effective_radius + col * spacing + x_shift
            wx = cx + x_offset
            wy = cy + y_offset
            # Check within PSR circle
            dist = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
            if dist <= effective_radius:
                waypoints.append((wx, wy))

    # Sort by distance from center (inner spiral)
    waypoints.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    return waypoints
