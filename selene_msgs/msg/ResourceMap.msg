# Fused posterior of the probabilistic ice-concentration grid — FR-MAP-1(e)(f).
#
# Published by the orchestrator on /orchestrator/resource_map at
# resource_map_publish_rate (default 0.5 Hz, orchestrator_params.yaml).
#
# SPARSE SNAPSHOT ENCODING, and why. The grid is width*height cells (default
# 500x500 = 250000), but only cells a scout has actually observed go on the
# wire. Every message is a COMPLETE SNAPSHOT of the observed set, never a
# delta: a subscriber that joins late, or drops a message, is fully correct
# from the next one it receives. A cell whose index does not appear in
# cell_index is still at the untouched prior (prior_mean, prior_variance,
# observation count 0).
#
# MEASURED (ROS 2 Jazzy, rmw_fastrtps_cpp, rclpy.serialization): 88 bytes of
# fixed overhead plus 16 bytes per observed cell. The default 10-waypoint HTN
# survey observes 794 distinct cells — 0.318% of the grid — so a post-survey
# snapshot is 12792 bytes against 3000072 for the equivalent dense float32
# mean+variance+count grid, a 234x reduction. Sparse stays smaller than dense
# until ~187500 cells (75% coverage) are observed.
#
# DDS is NOT what makes the dense form untenable — a 3 MB sample was measured
# delivering cross-process over Fast DDS at 10 Hz without loss. Two other
# things are: rosbridge's message_conversion.extract_values burns ~284 ms of
# GIL-held Python per dense message per client, inside the single process that
# carries every dashboard topic; and roslibjs cannot reassemble the fragments
# rosbridge emits above max_message_size, so oversized messages are dropped
# client-side in silence.

# Acquisition time, and the frame the geometry below is expressed in.
#
# CONVENTION NOTE: the other seven selene_msgs carry a bare
# builtin_interfaces/Time named by role and no frame. A Header is used here,
# and only here, because this is the only message describing a georeferenced
# grid, so frame_id is load-bearing. A Header is exactly {Time stamp; string
# frame_id}, so this is the house convention plus an explicit frame.
std_msgs/Header header

# ---- Grid geometry. Sufficient alone to place every cell in the world, with
# ---- no reference to a parameter server.

# Cell edge length in metres (ResourceMap._resolution, default 1.0).
float32 resolution

# Grid extent in cells along +x and +y (default 500 x 500).
uint32 width
uint32 height

# World position of the LOWER-LEFT (minimum-x, minimum-y) OUTER CORNER of cell
# (0, 0) — ResourceMap._origin_x / _origin_y, default (-250, -250). Same
# convention as nav_msgs/MapMetaData.origin. NOT a cell centre: the centre of
# cell (col, row) is
#     x = origin.x + (col + 0.5) * resolution
#     y = origin.y + (row + 0.5) * resolution
# which is exactly what ResourceMap.grid_to_world() returns. z is unused.
geometry_msgs/Point origin

# ---- Prior. Describes every cell NOT listed in cell_index.

# Posterior of an unobserved cell (ResourceMap prior_mean / prior_variance,
# default 0.0 wt% and 100.0 wt%^2). Carried explicitly so a consumer can fill
# the grid and scatter the observed cells into it without hardcoding the
# orchestrator's defaults. prior_variance is also the datum the FR-MAP-4 alpha
# channel normalises certainty against.
float32 prior_mean
float32 prior_variance

# Sum of the observation count over the WHOLE grid
# (ResourceMap.get_total_readings()). Lets a consumer report total evidence,
# and spot a map reset, without diffing the arrays.
uint32 total_observations

# ---- Observed cells. The four arrays below are PARALLEL: identical length,
# ---- and element i of each describes the same cell. A consumer MUST reject a
# ---- message whose array lengths disagree.

# Flat row-major index of each observed cell, strictly ascending:
#     cell_index = row * width + col
#
# ROW ORDER — READ THIS BEFORE WRITING ANY CONSUMER. Row 0 is the SOUTH
# (minimum-y) edge and row height-1 is the NORTH (maximum-y) edge; rows ASCEND
# with world y. That is the numpy indexing the grid already uses
# (ResourceMap._mean[gy, gx] with gy from world_to_grid), and it is also the
# nav_msgs/OccupancyGrid convention, so converting this message to an
# OccupancyGrid needs no row flip.
#
# It is the OPPOSITE of the image/heightmap convention, where row 0 is the
# NORTH edge. This project has already shipped a mirrored terrain by getting
# that backwards once — see to_image_rows() in
# selene_sim/scripts/generate_heightmap.py, which records the PSR crater
# physically rendering at (-100, +150) instead of the configured (-100, -150).
# Do not "fix" this array with a flipud. Flip at an image boundary, and only
# there.
uint32[] cell_index

# Posterior mean ice concentration, wt%. float32 rather than the grid's
# internal float64: the quantity is bounded near 0..10 wt% and sensor sigma is
# ~0.5 wt%, so float32's ~1e-6 wt% error sits six orders of magnitude below the
# noise floor.
float32[] cell_mean

# Posterior variance, wt%^2. Smaller means more certain. This is the channel
# FR-MAP-4(c) maps to alpha — transparent = uncertain, opaque = confident.
float32[] cell_variance

# Readings fused into this cell (ResourceMap._count). Always >= 1 for a listed
# cell; that is what makes it "observed".
uint32[] cell_observation_count
