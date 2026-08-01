# Provenance correction for `slope_capability_2026-08-01.json`

This file exists because the as-run artefact carries a **wrong commit id**, and
the artefact must not be edited to fix it: its value is that it is the byte-exact
output of the run, and the SHA-256 fields inside it are the chain that makes it
evidence. Editing it would break that chain. The correction is recorded here
instead, additively.

## What is wrong

    "git_commit":               "ff80ed1c6d8540215d74409afefef92a1cc95412"
    "workspace_source_commit":  "ff80ed1c6d8540215d74409afefef92a1cc95412"
    "git_worktree":             "dirty"

**The campaign did not run against `ff80ed1`.** It ran against the working tree
of `7727ba8` ("Close D-30, D-31, D-34, D-35 and the Resource Knowledge Map").

The mechanism: the WSL2 workspace `~/selene_ws/src/selene` was created as a git
clone at `ff80ed1`, and its *files* were then updated by `rsync` from the Windows
working tree, which excludes `.git`. So the source files were `7727ba8` while
`git rev-parse HEAD` inside that clone still answered `ff80ed1`. The script asked
git, and git answered honestly about a repository nobody had moved.

The `"git_worktree": "dirty"` flag is the one field that hints at this. It is not
sufficient — "dirty" is routine, a wrong commit id is not.

This is the same failure the project's own `scripts/sync_and_build.sh` was written
to avoid: it stamps `.selene_source_commit` from the SOURCE repo at rsync time,
precisely because the rsync excludes `.git` and nothing downstream could work it
out. The campaign was run through an ad-hoc sync instead of that script, and this
is the cost.

## Why the measurement still stands

The commit id is not what the measurement depends on. What it depends on is the
terrain and the world, and the artefact records a SHA-256 for each. **All four
were verified against the committed repository at `7727ba8` on 2026-08-01 and all
four MATCH:**

| input | file | result |
|---|---|---|
| world | `selene_sim/worlds/lunar_psr.sdf` | MATCH |
| relief | `selene_sim/models/lunar_terrain/heightmaps/lunar_surface_513.png` | MATCH |
| contact | `selene_sim/models/lunar_terrain/heightmaps/lunar_collision_129.png` | MATCH |
| datum | `selene_sim/models/lunar_terrain/heightmaps/terrain_datum.json` | recorded |

So the campaign measured the committed terrain, on the committed world, and the
hashes prove it independently of what git was asked. Note in particular that the
world hash matches the **post-fix** `lunar_psr.sdf` — the invalid-XML repair
(D-39) landed before the campaign ran, so the artefact is not from a pre-fix
world.

## One further discrepancy, unresolved

The artefact records `"gz_version": "Gazebo Sim, version 8.10.0"`, taken from
`gz sim --versions`. Asked as `gz sim --version`, the same installation on the
same host answers **8.11.0**. Both readings were taken on 2026-08-01 on
LAPTOP-Hoya. Which number describes the physics engine that produced these
trials has not been established, and the difference is not assumed to be
cosmetic — it is recorded rather than reconciled.

## What to do next time

Run `scripts/sync_and_build.sh` rather than an ad-hoc rsync. It writes
`.selene_source_commit` from the source repository, which is the only place the
answer exists once `.git` has been excluded from the copy.
