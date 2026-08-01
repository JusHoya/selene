# Phase 5 Deviation Register

What Phase 5 was scoped to deliver, what was actually delivered, and every place
those differ. Written 2026-07-30 at commit `19d364c`; rewritten the same day at
`bab8af6` when D-01..D-06 and D-10 were fixed; re-verified 2026-07-31 against
the **uncommitted working tree** on branch `phase5-hardening` (base commit
`bab8af6`; nothing staged). Every closure below was re-checked against the code
on that pass rather than taken from the implementers' reports, and four entries
were weakened, three citations corrected and four new deviations opened as a
result. **Amended later the same day** when the adversarial review D-01 and
D-02 had never received was finally run: two more entries weakened, two defects
repaired, D-14 fixed and closed, and four further deviations (D-15..D-18)
opened. Nothing in that amendment was rendered either.

**Rewritten again on the evening of 2026-07-31, and this is the amendment that
changes what the document says about itself.** Between the last revision and
this one the system was run: a ten-robot fleet twice, a four-robot fleet three
times, and `scripts/validate_phase5.sh` twice. Nineteen new deviations
(D-19..D-37) are opened below, eleven of them closed on live evidence. Six
entries that read "implemented, not demonstrated" are upgraded on observations
made in a browser, in Gazebo or on the wire, and named as such. Three figures
this register published as measurements are **superseded** — they were measured
in a frame that has since been proved not to be the frame they claimed. One
theory this register carried, and one the repository's own configuration files
asserted as fact, are **refuted**.

**Amended again on 2026-08-01, and this is the first amendment written after
every entry it inherited as open had been closed.** Four commits landed on
`phase5-hardening` between the last revision and this one — `c4548ce`,
`d390315`, `7727ba8` and `9c1a4d7` — and the exit gate was run a **third** time,
against `9c1a4d7`. **All six deviations this register carried as open (D-28,
D-30, D-31, D-32, D-34, D-35) are closed below**, one of them — D-32 — dissolved
rather than fixed, and one of them — D-31 — diagnosed for the first time. Five
new deviations are opened: **D-38, D-39, D-40 and D-41, each closed or worked
around on the evidence that found it, and D-42, which is OPEN with an UNKNOWN
cause.** The headline measurement is the gate:

    2026-07-31   8 passed / 1 failed / 2 skipped   (exit 1)
    2026-07-31   9 passed / 0 failed / 2 skipped   (exit 2 — a SKIP is not a pass)
    2026-08-01  10 passed / 1 failed / 0 SKIPPED   (exit 1)   at 9c1a4d7

**Zero skips is the finding.** Checks 6 and 9 produced verdicts for the first
time, so PRD exit-gate rows 3 and 4 are **measured at last** rather than
unmeasurable — that is D-34 closed, on the gate's own output. **The gate still
does not pass**, and the reason is new: check 11 failed because the gate chose a
robot reporting 0% battery and never checked that it could perform the
manoeuvre. That robot's 0% is **D-42, and nobody knows what produced it.**

**Provenance, and it changed under this amendment.** Every entry below was
written and verified against the **uncommitted** working tree on branch
`phase5-hardening` at base commit `bab8af6`, which is what the `file:line`
citations point into. Partway through the amendment the branch owner committed
that tree as `30403a8` ("Phase 5 hardening: run the system, and record what
running it found" — 134 files, +29,815 / -1,420), so those citations now point
into committed code on `phase5-hardening` and are more stable than this document
originally claimed. **Nothing here was committed by this register's own
author.**

**Provenance of the 2026-08-01 amendment, which is different again.** Every
citation added or revised on this pass was opened and read against the committed
tree at **`9c1a4d7`**, and every test-lane count in it was re-run on this box
rather than copied from a commit message. The live figures are not this pass's
own: they come from the 2026-08-01 exit-gate run (report regenerated **by that
run** at `$HOME/selene/phase5_validation_report.md`, source commit `9c1a4d7`,
launch log `/tmp/selene_unified_launch.log`, probe JSON
`/tmp/selene_phase5_probe.35401.json`), from the 54-trial slope campaign
committed as `docs/slope_capability_2026-08-01.json`, and from a browser session
whose ROS side was a **rosbridge test double, not the real stack** — that
qualification is repeated in every entry that rests on it, because it bounds
what those observations can prove. CI conclusions cited below were read from the
GitHub Actions API by run id.

**Read "Verification limits" at the bottom before quoting anything here as
evidence.** The 2026-07-30 closures of D-01..D-06 and D-10 were written and
tested on a Windows box with no ROS install. Where an entry says MEASURED it
names what was run and who ran it; everything else is a static argument from
code cited by line, or a unit test in the ROS-free lane. As of this amendment a
majority of the register **is** live evidence — but the boundary between the two
kinds of claim is drawn per entry and must not be smoothed over. The owner of
this document ran the Windows test lanes and read every cited line; the owner
ran **no** ROS node, no Gazebo, and no browser. Every live figure below is
attributed to the run that produced it.

**"Closed" in this document has a narrow meaning, and it is not always
"demonstrated".** For an entry marked **CLOSED — DEMONSTRATED** the acceptance
behaviour was observed on a running system and the observation is named.
For **IMPLEMENTED, NOT DEMONSTRATED** it means only that the defect is gone from
the source and a test that fails without the fix passes with it. The split is
stated per entry and summarised in the table below. **The Phase 5 exit gate has
now been run and it does not pass** — see D-10 and "Recommended disposition".

This document exists because a deviation was being carried by a single line in a
shell script. `scripts/validate_phase5.sh` printed, into its own report footer:

> **Known deviation:** FR-MAP-4 (RViz2 visualization, P1) intentionally skipped
> per plan decision D9 — the dashboard's canvas heatmap satisfies operator
> visualization.

**No decision D9 exists.** Searched exhaustively: `"D9"` appears four times in the
tree and three are downstream citations of the fourth. There is no D-numbered
decision scheme at all — the PRD's decision register is DD-1..DD-6
(`docs/PRD.md:954-963`) and stops at DD-6. `SELENE_Project_Plan_1.md` contains
neither "D9" nor "FR-MAP-4" and still lists RViz2 overlay as in scope
(`SELENE_Project_Plan_1.md:410`). `git log --all --grep=descope` returns nothing;
the line was introduced by `473259a` byte-identical to its current form, and that
commit added no decision document.

So the script that certifies the exit gate was also issuing the waiver for the
criterion it could not meet. That is not a deviation record; it is a self-signed
permission slip. This file replaces it.

---

## Status summary

| Requirement | Priority | Deviation | Disposition | Evidence |
|---|---|---|---|---|
| FR-DASH-1 Fleet Map View | P0 | D-01, D-16 | **Closed — demonstrated** | rendered and confirmed in Chrome (operator, 2026-07-31); D-16 fixed and Jest-covered |
| FR-DASH-2 Resource Heatmap | P0 | D-02, D-15, D-17, D-18 | **Closed — demonstrated** | rendered in Chrome; D-17's 2-D swatch confirmed rendering; D-15/D-18 fixed, Jest / pytest covered. **No RViz2 side-by-side was performed** |
| FR-DASH-3 Task Queue Panel | P0 | D-03 | **Closed — demonstrated** | rendered and confirmed in Chrome (operator) |
| FR-DASH-4 Robot Detail Panel | P1 | — | Delivered | — |
| FR-DASH-5 Manual Task Injection | P1 | D-04 | **Closed — demonstrated** | injected over the rosbridge websocket in the exit gate, twice, and announced + assigned under its own id in the launch log |
| FR-DASH-6 Robot Override | P2 | D-05 | **Implemented; half demonstrated** | both overrides reached the FSM live (gate checks 7, 8, 11); the override's row in the rendered task history was never itemised |
| FR-DASH-7 Mission Progress | P1 | D-06, D-11, D-31 | **Closed — demonstrated; one published field was wrong** | 5 deliveries, `deposited_quantity` 94.85 kg, `unaccounted_quantity` exactly 0.0, on a 30-minute ten-robot run. `fleet_distance_total` on that same run was 2.21× the truth — diagnosed and fixed 2026-08-01 (D-31), **sufficiency not established**. (This row read "D-28" until 2026-08-01; that was a typo — D-28 is the slope limit and has nothing to do with mission progress.) |
| FR-SIM-7 Launch & Config (full) | P0 | D-07 | **Closed — demonstrated** | measured on WSL2 / Jazzy; re-exercised at 4/3/3 twice since, and at 2/1/1 in the 2026-08-01 gate run |
| FR-MAP-4 RViz2 Visualization | P1 | D-08 | **Closed — implemented, overlay never seen** | published and machine-paired live; **its 2026-07-30 hot-cell figure is SUPERSEDED** (odom frame); **no RViz2 has ever rendered it, and that is still true on 2026-08-01** |
| FR-MAP-1(e)(f) fused map on the wire | P0 | D-09 | **Closed — demonstrated** | largest live `ResourceMap` websocket frame 362 B (gate check 3, all three runs) |
| Navigation slope limit | P1 | D-28, D-32 | **Closed 2026-08-01 — measured, enforced, demonstrated** | 54-trial capability campaign (`docs/slope_capability_2026-08-01.json`); limit 20°, enforced **per step**; every agent in the 2026-08-01 gate run logged depot and recharge pad **REACHABLE** |
| Phase 5 exit gate itself | — | D-10, D-29, D-34, D-35, D-42 | **Run, three times. DOES NOT PASS** | 8/1/2 (exit 1), then 9/0/2 (exit 2), then **10 passed / 1 failed / 0 skipped (exit 1)** on 2026-08-01 at `9c1a4d7`. **Zero skips**: rows 3 and 4 measured at last. The remaining failure is D-42, cause unknown |

All nine Phase 5 requirements are **code-complete**, every deviation this
register named against them has a fix in the tree, and as of the evening of
2026-07-31 most of them have been **observed working on a running system**. What
has not happened is a green exit gate: the gate has now been run **three** times
and returned exit 1, exit 2 and exit 1. **Phase 5 cannot be recorded as
closed.** See "Recommended disposition".

**The implemented / demonstrated distinction is load-bearing and this register
will not collapse it**, even now that most entries have crossed it. Two things
in the table above are still short of their PRD acceptance method and say so in
place: the RViz2 overlay has never been rendered by RViz2 and the side-by-side
comparison `docs/PRD.md:1504` asks for has never been performed; and PRD row 7
(dashboard frame timing) is NOT COVERED by construction. **PRD rows 3 and 4 are
no longer on that list** — they were unmeasured in both 2026-07-31 runs for the
reason recorded as D-34, and on 2026-08-01, with D-34 fixed on both sides, they
produced verdicts and both PASSed.

**Thirty-two deviations have been opened since this register's first draft —
D-11 through D-42.** D-11..D-18 came from verifying the 2026-07-30 closures
rather than accepting them. **D-19..D-37 were opened on the evening of
2026-07-31**, and they divide into three groups worth naming separately:

- **Four defects that had been quietly costing the mission for phases**
  (D-19..D-22): an orphaned `recharge_threshold` that made the fleet recharge
  after every task at ~90% charge, an auction with no backoff that re-announced
  one task 261 times, a dead simulator that degraded the fleet in silence, and an
  HTN planner that sent the hauler to the excavator's exact coordinate. All four
  are fixed and all four were observed fixed.
- **Five things nobody had looked at, found by looking** (D-23..D-27): the PSR
  crater is a 34° bowl and every ice deposit is inside it, so **no haul in this
  system had ever been physically possible**; dead reckoning was the mission's
  only position estimate and its error was unbounded (166 m measured); nothing
  could see a robot whose wheels turn while its body does not; `ros2 launch`
  outlived the simulator; and the FR-ISRU-2 overdraw alarm fired on every healthy
  haul.
- **Ten items the runs surfaced and did not close** (D-28..D-37), of which seven
  were open at the close of 2026-07-31. **Six of those seven are closed on
  2026-08-01** — D-28, D-30, D-31, D-32, D-34 and D-35 — leaving the one that
  matters most: **the cause of the ODE abort is unknown** (D-37), untouched by
  this amendment.

**Five more were opened on 2026-08-01** (D-38..D-42), and four of them came from
running something nobody had ever run:

- **D-38**, the dashboard lockfile: CI's newest job could not install the
  dashboard **at all**, and nothing had noticed because that job had never
  fired on this branch. Its first firing failed on its own configuration.
- **D-39**, two world files that were **invalid XML** — and, one line below the
  failure that says so, a check that printed a green line for lunar gravity
  **against an empty value**.
- **D-40**, the Resource Knowledge Map: **the animation loop was never started**,
  reported by the operator and invisible to every test the project owns.
- **D-41**, a `gz sim -s` segfault in the depth-camera render path, which
  **counterfeited four "cannot climb" results** in the slope campaign and would
  have set the fleet's slope limit far too low.
- **D-42**, OPEN: a scout reported **"Battery critical (0.0%)" 6.15 s after its
  agent started**, three times, and took check 11 down with it. **The cause is
  unknown.** Several candidate mechanisms are eliminated in the entry; none of
  them explains it.

Two lists remain required reading: "Open items carried forward" for what a
closure deliberately does not cover, and "Verification limits" for what nobody
has checked.

**Two deviations are open as of 2026-08-01: D-37 and D-42, and neither has a
known cause.** Everything else this register has ever opened is closed.

**A process failure is recorded in D-01 and D-02 themselves.** Every other
2026-07-30 closure in this register was put through an adversarial review and
then repaired. D-01 and D-02 were not: the reviewer assigned to them **died
mid-stream with an API error**, and both entries were written as
"IMPLEMENTED … NOT DEMONSTRATED" on the strength of the implementer's own
report alone. That asymmetry was itself unrecorded until 2026-07-31, when the
missing review was run under two independent lenses. It found nine defects
between them, two of which were repaired and four of which are now
D-15..D-18. **This is the D9 failure mode in miniature** — a claim carried
without an independent check behind it — and it is why the provenance of a
closure, not only its content, belongs in this file.

---

## D-01 — FR-DASH-1: robot state is not colour-coded by FSM state — CLOSED 2026-07-31, DEMONSTRATED IN A BROWSER

> **Status changed 2026-07-31 (evening).** This entry read "IMPLEMENTED
> 2026-07-30, NOT DEMONSTRATED" for a day and a half. The operator opened the
> dashboard in Chrome against a live rosbridge on 2026-07-31 and **confirmed
> D-01 rendering**, along with D-02, D-03 and D-04. That is the observation this
> entry was missing and it is recorded on the operator's authority, not this
> document owner's — no browser was opened here.
>
> **What that confirmation does not cover, stated so it is not over-read.** It
> was recorded as a single line naming four deviations. It did not itemise the
> nine state hues against the nine `AgentState` values, the abbreviation channel,
> the label-collision behaviour at the depot cluster, or the legibility of the
> glyph at minimum zoom. Those remain arithmetic (below), now with a browser
> having disagreed with none of them. **D-16, the open remainder of this entry,
> is fixed and closed** — see that entry; the marks are now planned by measured
> width and the plan covers every mark drawn, pinned by 39 Jest tests in
> `selene_dashboard/src/__tests__/` (there was no JS test runner in the tree when
> this entry was written; open item 5 is closed).

**Specified** (`docs/PRD.md:486-494`): robot icons colour-coded by type, with a
state indicator colour-coded by FSM state.

**Was**: the icon was coloured by type and nothing else carried state. Of nine
FSM states only three had any map encoding — a glow for `WORKING`, a ring for
`ERROR`, reduced alpha for `RECHARGING`. `STATE_COLORS` existed in
`src/utils/colors.js` and was never imported by `FleetMap.jsx`. An operator
could not tell `IDLE` from `NAVIGATING` from `SURVEYING` on the map. Separately,
the robot-ID label and the battery gauge were suppressed below
`LABEL_MIN_SCALE = 0.9` px/m, and the gauge was gated on the label having been
placed, so both vanished when zoomed out.

**Now**: FSM state gets **two** independent channels, and the icon keeps its
type encoding.

- A filled state dot in `STATE_COLORS`, drawn after the icon's `restore()` so it
  sits outside the heading rotation and outside the `RECHARGING` alpha halving
  (`FleetMap.jsx:595-626`).
- A three-character abbreviation beside the id label, in the same colour
  (`STATE_ABBREV`, `colors.js:27`; drawn at `FleetMap.jsx:650-665`).
- `ASSIGNED` was given its own hue (`#f472b6`, `colors.js:9`). It had shared
  `#a855f7` with `BIDDING`, so two of the nine states were not separable by
  colour at all.

**A separate mark rather than recolouring the icon**, because `STATE_COLORS` and
`TYPE_COLORS` collide in three places — `NAVIGATING`/scout `#00d4ff`,
`RETURNING`/excavator `#ffc107`, `RECHARGING`/hauler `#00e676`. Recolouring the
icon would have destroyed the type encoding the same PRD clause requires.

`LABEL_MIN_SCALE` is **deleted**, and the battery gauge no longer depends on the
label having been placed. The gate's stated reason did not survive checking:
`drawRobots` runs inside a `scale(scale, -scale)` world transform, the label
block applies a second `scale(1, -1)` giving a net uniform `scale`, and the font
is set to `${9 / scale}px` — so the glyph is 9 CSS pixels at **every** zoom
level including the minimum. What the gate was reaching for is already done, and
done better, by the label collision planner.

**Not executed.** There is no JS test runner in this repository and none was
added, and no browser was opened. Every claim above is read off the source. The
legibility arithmetic in particular is a static argument from the transform
chain, not an observation — see Verification limits item 5.

### Provenance: this entry had no adversarial review until 2026-07-31

Recorded because it is the kind of fact this register exists to carry, and
because omitting it made D-01 look better-checked than it was.

D-03..D-06 and D-10 were each reviewed adversarially on 2026-07-30 and then
repaired — that is where D-03's IN_PROGRESS regression, D-06's three
delivered-path defects and D-10's five gate defects came from, and each of
those entries says so. **D-01 and D-02 got no such review.** The reviewer
assigned to the pair terminated mid-stream with an API error, and both entries
were written to "IMPLEMENTED 2026-07-30, NOT DEMONSTRATED" on the strength of
the implementer's own report and nothing else. Nobody recorded that at the
time, so the two entries read as if they had been through the same process as
their neighbours.

The missing review was run on **2026-07-31** under two independent lenses — one
on rendering correctness (geometry, the row flip, the alpha axis,
cross-language colour parity), one on acceptance clauses, prop plumbing,
message size and regression. Its D-01 findings are below; its D-02 findings are
in that entry. Neither lens could render anything either, so nothing here
upgrades D-01 past "not demonstrated".

### What the 2026-07-31 review found in D-01, and what remains

**Cleared, by arithmetic executed rather than by reading.** All nine
`AgentState` values in `selene_agent/fsm.py:18-26` get two distinct channels —
nine distinct dot hues and nine distinct three-character abbreviations, none
missing, no two states rendering identically. The three `STATE_COLORS` /
`TYPE_COLORS` collisions this entry names are real, which is what justifies the
separate mark. The `LABEL_MIN_SCALE` deletion holds on its own terms: worked at
scale 0.3 / 0.9 / 4.3 / 20 px/m, every offset in the robot glyph is
(screen px)/`scale` under a net-uniform transform, so the glyph stays 9 CSS px,
the dot 3.5 px and the gauge 16-19 px below centre at every zoom. The gate's
stated reason genuinely did not survive.

**Not cleared.** The review found that D-01 fixed one mark-placement defect and
introduced three more of the same species: the collision window is narrower
than the label it now guards, the battery gauge was freed from the label but
never added to the collision plan, and the colour-blind-safe state
abbreviation is still gated on the label having been placed — the exact
coupling D-01 removed from the gauge. **All three were tracked as D-16, and
all three are now fixed — D-16 is closed.** They were not folded into this
entry because they were new defects, not an incomplete fix of the old one: the
FSM-state encoding D-01 was opened for is delivered.

---

## D-02 — FR-DASH-2: the heatmap's confidence axis carries no information — CLOSED 2026-07-31, DEMONSTRATED IN A BROWSER

> **Status changed 2026-07-31 (evening),** on the same operator observation as
> D-01: the heatmap was confirmed rendering in Chrome against a live rosbridge.
> **D-15, D-17 and D-18 — the three open defects this entry's late review
> opened — are all fixed and closed**, and D-17's replacement legend, a 2-D
> swatch evaluated through the same `posteriorCellRGBA…` function the raster
> applies, was itself confirmed rendering in Chrome. It replaced a legend whose
> three labels collided on screen into the string `unsure5 wt% shownconfident`,
> which is worth recording because it is the first defect in this whole family
> that **only** a browser could have found: no arithmetic in this register
> predicted it.
>
> **Two things are still not demonstrated and this closure does not claim them.**
> (a) `docs/PRD.md:1504` asks for a **side-by-side comparison with RViz2**. No
> RViz2 has been run. What exists is machine parity — the exit gate recomputes
> the marker array from the `ResourceMap` message and asserts point-and-colour
> equality (check 10, PASS on both runs) — which is a stronger statement about
> the *data* and no statement at all about two pictures. (b) Whether the
> compressed alpha band the shipped fleet actually produces reads as a confidence
> gradient against dark terrain is a judgement nobody has recorded making.

**Specified** (`docs/PRD.md:496-504`): opacity proportional to confidence; colour
ramp gray → blue → red.

**Was**: `α = clamp(0.7 × (1 − sensor_uncertainty), 0.05, 0.7)`, where
`sensor_uncertainty` traced back to a **constant** `noise_stddev: 0.5`
(`selene_hal/config/scout.yaml:16`) via `prospect.py:137-157`. Every reading
produced the identical α = 0.35, so the opacity axis was inert. The ramp was
dark-blue → blue → cyan → yellow → red with no gray tier. And the whole map was
built client-side from raw per-reading `ResourceMapUpdate` messages rather than
from the orchestrator's fused posterior.

**Now**: the dashboard subscribes to `/orchestrator/resource_map`
(`rosTopics.js:31`) — the sparse fused posterior that has been on the wire since
D-09 — and renders it as an offscreen `ImageData` raster blitted into world
space (`FleetMap.jsx:171-289`). The confidence axis is real because the
posterior carries a real per-cell variance:

- alpha is `varianceToCertainty(variance, priorVariance)` mapped into
  `[ALPHA_MIN, ALPHA_MAX]`, log-scaled against the map's own prior variance;
- the gray tier the PRD asks for is a **lerp toward `LOW_CONFIDENCE_GRAY`**
  `(90, 96, 110)` as certainty falls, rather than a fifth ramp segment at the
  bottom. A cell observed once is desaturated *toward* cool gray whatever its
  mean, which is the statement "we do not know this yet" — a bottom segment
  would instead have said "we know this is low". **This sentence used to say a
  once-observed cell "is desaturated toward cool gray"; measured, it gets at
  most halfway there, and full gray is unreachable on the shipped fleet
  entirely. See correction 1 below.**

The raster is rebuilt only when `resourceMap.revision` changes, not per frame:
at 0.5 Hz against a 30 fps draw loop, rebuilding on object identity would have
rewritten a 500×500 `ImageData` sixty times for every one time it changed.

**The RViz2 overlay got the same gray rule** (`resource_map_viz.certainty_to_rgb`),
so the two renderers stay the verbatim pair D-08 made them. `MAX_CONCENTRATION_WT`,
`ICE_FLOOR_RGB`, the three segment thresholds and the per-channel outputs are
machine-checked across the language boundary by
`selene_orchestrator/test/test_dashboard_colour_parity.py`, which parses
`colors.js` from Python and sweeps 0–12 wt% at 0.01.

**MEASURED here, and it changed the code**: that parity sweep initially found
**5 of 1201 samples** differing by 1 in one channel, because JS `Math.round`
rounds half away from zero and Python `round()` is banker's rounding — 0.25 wt%
gives `(18, 50, 161)` in JS and `(18, 50, 160)` in Python. `resource_map_viz`
now uses `_js_round(x) = floor(x + 0.5)` (`:92`) and the test asserts **exact**
per-channel equality. This was reproduced independently while writing this
entry.

**Not executed**: the raster itself. Nothing rendered it. The row-order flip
(`ResourceMap` row 0 is minimum y, `ImageData` row 0 is the top of the image,
`FleetMap.jsx:250`) is reasoned from the two stated conventions and is the
single change here most likely to be **silently wrong** — a north–south mirror
looks entirely plausible on screen. See Verification limits item 4.

### Provenance: this entry had no adversarial review until 2026-07-31

The same omission recorded under D-01, and for the same reason: the reviewer
assigned to D-01 and D-02 terminated mid-stream with an API error on
2026-07-30, so this entry was written to "IMPLEMENTED … NOT DEMONSTRATED" on
the implementer's own report alone while D-03..D-06 and D-10 were each reviewed
and then repaired. That asymmetry went unrecorded until the missing review was
run on 2026-07-31 under two independent lenses. **Everything in the four
corrections below exists because that review was finally run** — including the
discovery that this entry's own central claim about the gray tier was wrong.
A closure written on the same day as its implementation, by the implementer, is
not evidence; this entry is the demonstration.

### Four corrections added 2026-07-31 by two adversarial reviews

Neither review could render anything either. Everything below is arithmetic
that was **executed** against the shipped modules and configuration files, on
the same Windows box, with no ROS and no browser. Every figure in corrections 1,
2 and 4 was independently re-executed while writing this section — the
0.2494 / 0.9926 variance span, the 0.5008 / 0.6508 certainty span, the
0.4506 / 0.5706 alpha span, and the round trip over 36,000 cells with zero
mismatches — and all of them reproduce.

1. **The gray tier and the bottom ~55% of the alpha ramp cannot be produced by
   the shipped fleet, and the certainty legend teaches a range no cell can
   have.** A cell is emitted only once `count >= 1`, i.e. once at least one
   Bayesian update has run against it. The sigma that reaches
   `ResourceMap.update` is the RCDL's `noise_stddev`, and `0.5` in
   `selene_hal/config/scout.yaml:16` is the **only** `noise_stddev` on a
   `scalar_field` sensor in the tree — `prospect.py`'s `inf` sentinel for "no
   usable sigma" never gets there, because `agent_node._publish_map_update`
   (`agent_node.py:997-1005`) drops any non-finite or non-positive sigma
   before it is published. **MEASURED** by running the shipped
   `ResourceMap.update()` at a cell centre with the shipped defaults: one
   reading takes the 81 cells of its footprint to variance 0.2494 (centre) to
   0.9926 (edge), i.e. certainty **0.6508 down to 0.5008** and alpha **0.5706
   down to 0.4506**. So `ALPHA_MIN = 0.05` and full `LOW_CONFIDENCE_GRAY` are
   the anchors of the mapping and **not values any pixel or cube will have**;
   at 3.5 wt% a once-observed cell renders `rgb(45,99,183)` at its footprint
   edge and `rgb(31,100,204)` at the centre. FR-DASH-2(b)'s "no data" tier is
   therefore delivered **entirely by the cell that is not emitted at all** —
   transparent, drawn by neither renderer — and not by the gray lerp.
   **Deliberately not recalibrated.** Moving the certainty datum off
   `prior_variance` would orphan the `prior_variance` field
   `ResourceMap.msg` publishes for exactly that purpose (the failure mode of
   D-09), invalidate D-08's measured alpha figures, and make a rendering
   judgement — where a barely-observed cell should sit against dark terrain —
   in an environment where nothing can be rendered. The limitation is recorded
   instead, in `resource_map_viz.variance_to_certainty`'s docstring, beside
   `ALPHA_MIN` and `LOW_CONFIDENCE_GRAY` in both languages, in
   `ResourceLegend.jsx` where the sweep is drawn, and here. It is **pinned**,
   not left to prose:
   `test_the_shipped_scout_cannot_reach_zero_certainty`
   (`selene_orchestrator/test/test_resource_map_viz.py`) re-derives
   0.5008 / 0.6508 / 0.4506 from `selene_hal/config/*.yaml` through the real
   `ResourceMap`, so changing a sensor's noise or the mapping fails the build
   and forces all four documents to be re-derived together.
   `test_a_noisier_sensor_would_reach_the_gray_end` sits beside it so
   "unreachable" is never read as "the mapping is broken": at sigma 2.0 one
   edge reading lands at certainty 0.2148.
2. **A documented figure was wrong by 2.8x, in both languages and in two test
   docstrings.** `variance_to_certainty` / `varianceToCertainty` both said
   "the first reading at a cell takes variance from 100 to ~0.09". Measured,
   the first reading gives 0.2494 at best; **0.09 is roughly where the third
   reading lands** (0.0833). It is the number a reviewer would use to
   sanity-check the alpha axis, and it was the number this register's own
   D-08 clause (c) quoted. Corrected in `resource_map_viz.py`, `colors.js`,
   `test_resource_map_viz.py` (two docstrings; the assertions were always
   about the value, not the reading count) and in D-08 below.
3. **The certainty half is now machine-checked across the language boundary.**
   This entry used to end "the gray-lerp and certainty functions are pinned by
   a table on the Python side and a mirrored comment on the JS side: a
   reviewer aid, **not** a check. If those two drift, nothing fails." Both
   reviews re-derived the two ports by hand, found them in agreement, and
   both said the same thing: nothing in CI would catch a future drift.
   `test_dashboard_colour_parity.py` now parses `LOW_CONFIDENCE_GRAY`,
   `VARIANCE_FLOOR`, `ALPHA_MIN` and `ALPHA_MAX` out of `colors.js`, rebuilds
   `varianceToCertainty` and the gray lerp from **those** numbers, sweeps 401
   log-spaced variances plus the degenerate inputs and 45 × 10 (mean,
   variance) pairs against the Python with **no tolerance on the channels**,
   and recomputes all 14 rows of the pinned table in `colors.js` instead of
   leaving them to be diffed by eye. Mutation-checked: perturbing `ALPHA_MAX`,
   one channel of `LOW_CONFIDENCE_GRAY`, or one channel of one pinned row each
   fails the suite. **What it still cannot see** is a change to a JS function
   *body* that leaves the constants alone; there is no JS test runner (open
   item 5) and adding one would put Node in front of the orchestrator's Python
   lane.
4. **The row-order flip is correct.** Recorded because this entry names it as
   "the single change here most likely to be silently wrong". Two independent
   reviews executed the round trip outside the browser — producer flat index,
   consumer decode, the `translate`/negative-`scale` blit — and both
   reproduced `ResourceMap.grid_to_world()` exactly, one of them over all
   250,000 cells with zero mismatches, including D-08's measured hot cell at
   world (-80.5, -140.5). The flip happens once in the index and is undone by
   the north-west anchor; the two do not compound into a mirror. **Still not
   rendered.** This is arithmetic agreeing with arithmetic, not an observation
   of pixels, and Verification limits item 4 stands.

### The same defect was still live in the sibling resource view

`ResourceGraph.jsx` — the "Resource Knowledge Map", one click away on
`Header.jsx:36-45` — computed node opacity as
`Math.max(0.15, Math.min(1.0, 1.0 - uncertainty * 0.8))` from
`ResourceMapUpdate.sensor_uncertainty`: **the identical inert-alpha-from-a-
constant defect this deviation was opened for**, in a file
`git diff` shows this change set never touched. Every node drew at
`1 - 0.5*0.8 = 0.6`, forever. The docstring also called the input a "0–1"
fraction when it is a standard deviation in wt% with no upper bound, so a
fleet declaring `noise_stddev: 2.0` would have clamped every node to alpha
0.15 — the same fraction-vs-unit confusion as D-06 break 1 — and the detail
tooltip rendered the scout's 0.5 wt% noise floor to the operator as **"50%"**.

**Fixed by deleting the axis rather than repointing it.** The modulation is
replaced by a named constant `NODE_ALPHA = 0.6`, which is bit-identical to
what the old expression produced under the shipped RCDL (`1.0 - 0.5 * 0.8 ===
0.6` exactly in IEEE 754 — executed in Node), so **nothing on that screen
changes today**; the tooltip now reads `±0.50 wt%` against the label "Sensor
sigma". This view is deliberately the per-**reading** picture — individual
samples and their agreement — and a raw reading carries no confidence to
encode; the fused posterior, where per-cell confidence exists, is the fleet
map's raster. Pulling `state.resourceMap` in here would have made it a second,
worse heatmap. The comment left in its place records what to do if a fleet
ever ships scouts with differing `noise_stddev`.

**Not executed**: nothing in `ResourceGraph.jsx` was rendered. `npx eslint src`
is clean and `CI=true npx react-scripts build` compiles (85.12 kB gzipped,
39 B smaller than before the deletion), which proves it compiles and nothing
about how it draws.

### Three of the review's findings were not repaired and got their own numbers (all now closed)

The two reviews raised nine findings between them. Two were repaired (the
unreachable-gray documentation-and-pinning above, and the `ResourceGraph`
inert alpha). Four minor ones are in "Open items carried forward" as items
15-18. The remaining three are defects of a different class — each can put a
wrong picture on screen with no error anywhere — and are tracked separately:

- **D-15** — the raster cache key collides across a rosbridge reconnect, so the
  previous backend session's heatmap can keep drawing for one publish period
  while the legend already reports the new session's counts.
- **D-17** — the concentration legend is drawn at certainty 1.0, a colour no
  cell on a nominal survey ever renders, so an operator cannot invert a map
  cell against the bar.
- **D-18** — the "verbatim pair" diverges on a non-finite cell mean: the JS
  renders the ramp floor, the Python raises inside the ROS publish timer.

~~**D-02 stays "implemented, not demonstrated".**~~ **All three were fixed and
closed on 2026-07-31, and the heatmap was rendered in Chrome** — see this
entry's status block at the top. Nothing was rendered by the implementation, by
either review, or by the repair; the browser came afterwards, and it immediately
found a defect none of the three reviews had: the legend's labels collided into
`unsure5 wt% shownconfident` (D-17). **The question this paragraph named is
still unanswered**: whether the alpha band the shipped fleet actually produces —
0.451 to about 0.73 over a real survey — is legible as a confidence gradient
against dark terrain is a judgement nobody has recorded making, and the Chrome
pass did not itemise it.

---

## D-03 — FR-DASH-3: task status is inferred, and two statuses are unreachable — CLOSED 2026-07-31, DEMONSTRATED IN A BROWSER

> **Status changed 2026-07-31 (evening).** Confirmed rendering in Chrome by the
> operator in the same pass as D-01, D-02 and D-04. Separately, the backend half
> ran: the exit gate's check 9 polls `/orchestrator/task_queue` for the injected
> task in ASSIGNED, and the message type was present and the publisher live on
> both runs. **Check 9 nonetheless SKIPped both times, and that is not this
> entry's defect** — the gate could not observe the FSM passing through IDLE,
> which is D-34. So the task-queue **latency** row of the PRD gate
> (`docs/PRD.md:1505`) is still unmeasured, and this closure is about the queue's
> content and reachable statuses, not about its 1-second budget.

**Was**: no task-status topic existed at all. The whole panel was reconstructed
client-side from `RobotState.current_task_id` transitions. The reducer could
only ever write PENDING / ASSIGNED / IN_PROGRESS / COMPLETED, so the `FAILED`
and `INTERRUPTED` states the UI can render were unreachable. A **cancelled**
task therefore rendered as completed — the orchestrator re-queued it as PENDING,
the dashboard saw the id drop off the robot and marked it COMPLETED — and any
completion happening across a page reload was never recorded.

**Now**: the orchestrator publishes `/orchestrator/task_queue`
(`selene_msgs/msg/TaskQueueState`) at `task_queue_publish_rate`, default 2.0 Hz,
chosen against `docs/PRD.md:1505` ("within 1 second") to leave a worst-case
500 ms publish latency before transport. (This document previously cited
`docs/PRD.md:1506` for that row. 1506 is "Operator-injected task enters auction
and gets assigned"; the row quoted here is 1505. Corrected 2026-07-31 after
re-reading the table.) It is a **complete snapshot**, never a
delta — the same choice, for the same reasons, as `ResourceMap.msg` — so a
browser loaded mid-mission is correct from the next message with no durability
negotiation. It deliberately uses default **volatile** QoS: transient-local
latching is the part of ROS QoS rosbridge handles least predictably, and a 2 Hz
snapshot needs none of it. About 75 lines of client-side lifecycle inference
were deleted; `useFleetState.js` now projects the snapshot.

**`FAILED` became reachable**, and this was the deeper half of the defect. It
was not a dashboard bug: `agent_node._handle_working` fired
`FSMEvent.TASK_COMPLETE` on skill **failure** as well as on success, so the
orchestrator saw RETURNING/IDLE with an empty `current_task_id` and called
`mark_complete()`. A failed excavate was recorded as a COMPLETED task in the
orchestrator's own queue, and no dashboard change could have fixed that. The fix
is a new `selene_msgs/msg/TaskResult` from the agent, which is authoritative for
termination; `_on_robot_state`'s heuristic is demoted to a fallback that skips
any task already terminated by a `TaskResult`. **The FSM event was deliberately
left alone** — firing `FSMEvent.FAULT` instead would route the robot to ERROR
and change fleet recovery behaviour under any transient skill failure. The agent
keeps its recovery semantics and simply tells the orchestrator what happened.

**`INTERRUPTED` became a resting status** — a behaviour change, not only a bug
fix. `interrupt_task()` no longer has its result immediately overwritten with
PENDING; `get_next_ready()` re-auctions from `REQUEUEABLE_STATUSES =
(PENDING, INTERRUPTED)` (`task_queue.py:28`). INTERRUPTED previously existed for
microseconds and appeared in no snapshot. It now means "was started, was
stopped, awaiting re-auction", which is how a cancelled task is told apart from
a completed one.

### The first attempt at this fix reintroduced the defect it was closing

Recorded because it is the most instructive thing that happened here, and
because it was caught by adversarial review after the entry above had already
been written as closed.

Moving task status from client inference to orchestrator truth **dropped a state
the client used to produce**. `git show HEAD:selene_dashboard/src/hooks/useFleetState.js`
marked a task `IN_PROGRESS` the moment a robot picked it up, and the old
`TaskQueue.jsx` drew a live progress bar off it. After the rewrite, an AST walk
of every status-mutating call across all five Python packages found **17 call
sites writing AUCTIONING, ASSIGNED, COMPLETED, FAILED, INTERRUPTED and PENDING —
and none writing IN_PROGRESS**. The only write anywhere was in
`test_e2e_integration.py`'s own harness, which manufactured the transition and
so kept the suite green over a state nothing could reach.

The consequence was precisely the failure class D-03 exists to name: a running
task published ASSIGNED for its whole life; `TaskQueue.jsx:120,173-182` draws the
bar solely for `IN_PROGRESS`, so the **`TaskStatus.progress` field added by this
very change** reached the browser and was discarded; and the `RUN` badge and
`--in-progress` style became dead code. A published enum value that no producer
can emit is the same shape of defect as `resource_map_publish_rate` under D-09.

**Fixed** by promoting the task rather than deleting the status:
`apply_robot_progress` (`orchestrator_node.py:288-325`) holds both the progress
mirror and the promotion, gated on the robot naming *that* task in
`current_task_id` — a free-running `prospect_<n>` survey or an
`override_goto_<n>` must not promote whatever the robot last won — and on
`fsm_state` being in `WORKING_FSM_STATES`. **One correction to the review that
found it**: it proposed `WORKING / SURVEYING / NAVIGATING`, but `SURVEYING` does
not exist — `selene_agent/fsm.py` declares nine states and none is that. The set
is `{NAVIGATING, WORKING}`; `ASSIGNED` and `RETURNING` are excluded, the latter
because the completion fallback reads it as "finished". Routed through
`set_status` so the transition also reaches the `TaskEventLog`, and `set_status`
no-ops on an unchanged status so it fires exactly once per task.
`test_robot_state_progress.py` (12 tests) drives it from a `RobotState`-shaped
input rather than by calling `set_status` directly, which is what the harness was
doing wrong.

Covered in the ROS-free lane by `test_task_feed.py`, `test_task_queue.py` and
`test_robot_state_progress.py`, and end to end in `test_e2e_integration.py` (a
`TaskResult(success=False)` marks the task FAILED, not COMPLETED). **The reducer
rewrite itself was not executed** — no JS test runner, no browser — so that the
progress bar now renders is an argument from `TaskQueue.jsx:120`, not an
observation.

**Still open in this requirement.** Two smaller items found by the same review
and deliberately left: every operator `TaskEvent` from the override service is
emitted with `task_id=''` even when the override interrupted a known running
task, so the history joins an override to its task only through a separate status
row; and a task requeued as `preferred_robot_absent` rests in INTERRUPTED though
it was never started, which is the reading `TaskStatus.msg` gives that status.
Both are open items 9 and 10 below.

---

## D-04 — FR-DASH-5: the quantity field is discarded, and a targeted task skips the auction — CLOSED 2026-07-31, DEMONSTRATED

> **Status changed 2026-07-31 (evening),** on two independent observations.
> (a) The form was confirmed rendering in Chrome by the operator with D-01..D-03.
> (b) The exit gate injected a task **over the rosbridge websocket** — the
> dashboard's own transport, not the rclpy fallback — on both runs, and the
> service returned `task_id=manual_0000` queued (check 5, PASS twice). The launch
> log then shows the whole path this entry exists for:
>
>     [scout_01] NAVIGATING --(OPERATOR_CANCEL)--> IDLE
>     [scout_01] IDLE --(TASK_ANNOUNCED)--> BIDDING
>     [scout_01] Bid on manual_0000: score=0.915 eta=53.8s
>     [orchestrator_node] Auction manual_0000: winner=scout_01 score=0.915 bids=1
>     [scout_01] BIDDING --(AUCTION_WON)--> ASSIGNED
>
> **The gate reported that row as SKIP anyway.** Check 6 could not sample the
> 0.247 s IDLE window through a 0.5 Hz… 2 Hz state topic and returned a
> "did not reach IDLE" string while the system was doing exactly what the row
> asserts. That is D-34, a defect in the measuring apparatus, and the log above is
> the evidence the gate failed to capture. **The quantity field's survival
> through the injection is not covered by either observation** — no injected task
> in either run carried a non-default `quantity_kg`.

**Was**: quantity was collected by the form and carried in
`selene_msgs/srv/InjectTask.srv`, but `inject_task_logic` never read
`request.quantity` and `TaskQueue.add_task` had no such parameter. The control
was dead end to end. And "enters the auction" held only for the unassigned path:
with a robot selected, the orchestrator force-assigned and published a
`TaskAssignment` directly — no auction ran.

**Now**, the quantity is live along its whole length: validated in
`inject_task_logic` (negative or non-finite rejected; 0.0 accepted as
*unconstrained*, which is exactly the pre-existing behaviour; non-zero on
`prospect` accepted with the response saying it was ignored), stored on
`TaskEntry.quantity_kg`, announced on `TaskAnnouncement.quantity_kg`, assigned
on `TaskAssignment.quantity_kg`, and honoured by `ExcavateSkill` as a
`quota_met` stop condition beside the existing hopper-full and timeout
conditions (`excavate.py:251`). The orchestrator does **not** clamp it — it has
no HAL and no RCDL; the agent clamps against `selene_hal/config/<type>.yaml`
(`excavate.py:134`).

**A targeted injection is now a constrained auction, not a force-assign. This is
a behaviour change, and it is deliberate.** `assigned_robot_id` becomes
`TaskEntry.preferred_robot`: the task enters the auction like any other, the
preference decides the winner only when that robot actually bids, and after
`inject_preferred_robot_max_rounds` (default 3) auctions without it the
preference is dropped with a WARNING alert and the auction opens up
(`resolve_auction_winner`, `task_feed.py:162`).

The old path was not merely impolite, it was broken: it re-PENDed the target
robot's current task and then published a `TaskAssignment` that
`agent_node` **discards** for any robot not in BIDDING or ASSIGNED — i.e.
exactly the busy robot it was meant to serve. Pre-empting a busy robot is now
done with `OverrideRobot 'cancel_task'` first, which works and is logged in the
task history (D-05).

`test_inject_task_handler.py` was **rewritten, not deleted**: its previous
assertions encoded the force-assign behaviour this change removes. It now
asserts the task stays PENDING, `preferred_robot` is set, no `TaskAssignment` is
published, and the target robot's current task is not pre-empted. ROS-free lane;
no live auction was run.

**Amended 2026-07-31 — an injected task used to reach the ledger and vanish.**
Making the quantity live exposed that `inject_task_logic` created manual
excavate and haul tasks with **no `site_id`** (`TaskEntry.site_id` defaults to
`''`). `material_event_logic`'s site-resolution step then dropped every
`MaterialEvent` those tasks produced and published a WARNING alert about it. An
operator who injected "excavate 12 kg" got a robot that really drilled 12 kg, a
task that completed, an alert that reads like a fault, and a progress bar that
did not move — the FR-DASH-5 quantity control working perfectly into a numerator
that ignored it. `_InjectTaskContext` now carries `site_id`, sourced from
`HTNPlanner.get_site_id()` (`orchestrator_node.py:1821`), excavate and haul
injections are stamped with it, and an injection made **before** SelectSite has
resolved is now **refused** rather than queued siteless. The response names the
credited site, because the ledger keys on `site_id` and never on position, so an
operator's clicked coordinates and the site their mass is credited to can
legitimately differ (see D-08's odom-frame note). Covered by
`test_inject_task_handler.py::TestLedgerSite`, one of whose cases drives the real
`material_event_logic` against a real `MaterialInventory` and asserts the event
is **applied, not dropped**.

**Deliberately still permissive**: an operator-named `quantity_kg > 0` on a haul
is honoured **unclamped** even against a site with nothing in it, because
FR-DASH-5 says the operator asked for that number. It is not silent —
`record_load` clamps the accepted mass to the site balance, banks the excess in
`get_unaccounted_kg()`, and `MissionProgress.unaccounted_quantity` puts it on the
wire. That is a judgement, not a verified behaviour; no operator has ever done it
on a running system.

Verified 2026-07-31 that `scripts/phase5_probe.py` injects only `prospect`
tasks, which need no site, so the new refusal cannot change the exit gate's
behaviour.

---

## D-05 — FR-DASH-6: overrides are not visible in the task history — IMPLEMENTED; HALF DEMONSTRATED 2026-07-31

> **Partially upgraded 2026-07-31 (evening), and deliberately not closed.** Both
> operator overrides were exercised live by the exit gate, twice: `force_recharge`
> was accepted and `scout_01` reported `fsm_state=RECHARGING` 0.5 s later (checks
> 7 and 8, PASS on both runs), and `send_to_location` replanned to a path ending
> **0.50 m** from the commanded target (check 11, run 2). So the override
> *mechanism* is demonstrated end to end, which is more than this entry could
> claim before.
>
> **What this entry is actually about is not demonstrated.** D-05 is about the
> override appearing as a row in the rendered task history, and no run report
> itemises the event ring on screen. The operator's Chrome pass named D-01..D-04
> and D-17 and did not name D-05. The `TaskEvent` ring is therefore still
> "implemented, not demonstrated", and open item 9 — that operator `TaskEvent`s
> carry `task_id=''` unconditionally, so the join to the task is implicit — is
> unchanged and still open.

**Specified** (`docs/PRD.md:536-544`): override actions logged and visible in the
task history.

**Was**: overrides landed in three places, none of them the task history — a
`FleetAlert`; a five-entry in-memory "Recent Actions" list wiped whenever the
operator selected a different robot; and a task queue that **deliberately
excluded** ids prefixed `override_`. The mechanism itself worked and was covered
by the exit gate; only its visibility was missing.

**Now**: every operator action — **accepted or rejected** — is appended to a
bounded `TaskEventLog` ring (`task_feed.py:41`, capacity
`task_queue_event_history`, default 32) and replayed in full in every
`TaskQueueState`. `inject_task` (`orchestrator_node.py:1873`) and every
`OverrideRobot` command (`:1955`) both append, with `detail` set to the **exact**
`response.message` the operator's own toast shows, so the history and the
feedback cannot disagree.

**A rejection is often the more interesting record** — "robot in ERROR, override
rejected" — which is why `accepted` is a field rather than a filter.

`TaskEvent` exists separately from `TaskStatus` because a status snapshot cannot
express two things: a transition that does not rest (INTERRUPTED → re-auction →
COMPLETED leaves no trace in the final row), and an operator action that touches
**no task at all** — `force_recharge` on an idle robot, `send_to_location` —
which FR-DASH-6(d) still requires to be visible and which has no task to hang
itself on. The ring is replayed whole in every snapshot, so a client dedupes on
`TaskEvent.seq`; `events_dropped` is on the wire because a browser that joined
late cannot derive it, and the dashboard must say the list is not exhaustive
rather than imply it is.

This survives both failure modes the old design had: a page reload (the ring is
replayed from the orchestrator) and a robot re-selection (`App.jsx:289`'s `key=`
stays exactly as it is — it exists for the battery rolling window and the
pending-confirmation panel; the fix was to move override history into reducer
state, not to remove the key).

Also closed here: `FleetAlert.source_robot_id` is now populated for operator
alerts (`orchestrator_node.py:1854-1861`); it was `''` for every one of them.

Ring semantics (eviction, `dropped`, `seq` monotonic and never reused) are
covered by `test_task_feed.py` in the ROS-free lane. The rendering of the
history list was **not executed**.

---

## D-06 — FR-DASH-7: the mission progress bar has a structurally zero numerator — CLOSED 2026-07-31, DEMONSTRATED END TO END

> **Status changed 2026-07-31 (evening). This is the entry that changed most,
> and it took two live runs and a root cause nobody had looked for.**
>
> The chain ran whole on a ten-robot fleet for 1817.6 s and delivered material
> five times. Final `MissionProgress`, verbatim:
>
>     target_quantity:          100.0
>     extracted_quantity:        94.87446594238281
>     in_transit_quantity:        0.025999069213867188
>     deposited_quantity:        94.8479995727539
>     at_site_quantity:           0.0004711151123046875
>     unaccounted_quantity:       0.0
>     material_events_applied:   15
>
> `at_site + in_transit + deposited − extracted` = **+3.815e-06 kg**
> (recomputed here from those five printed values in float64, not taken from the
> run report). Five deliveries at 174 s spacing, 18.94–19.00 kg each.
> **`unaccounted_quantity` is exactly 0.0 and there were zero overdraw
> WARNINGs** — the alarm that used to fire on every healthy haul is D-28.
>
> **`deposited_quantity` was non-zero for the first time in this project's
> history.** That is FR-DASH-7's actual acceptance criterion and no run before
> 2026-07-31 had ever produced it.
>
> **Read the earlier attempt before believing this one, because the earlier one
> looked identical and was worthless.** An instrumented run at midday on
> 2026-07-31 also reported a clean ledger — 19.01 kg extracted, conservation
> closing to float64 zero, `Haul complete: delivered=19.0kg to depot (50.0, 50.0)`.
> The hauler was **241.577 m from that depot** at the moment it unloaded, pinned
> at −35° pitch on the crater rim with its wheels turning at the commanded
> 0.395 m/s for 320.7 s while its body moved 6.6 cm. The ledger was arithmetically
> perfect about an event with no physical referent. **A conservation identity
> cannot tell you where the mass went**, and this register nearly recorded that
> run as a delivery. The two defects underneath it are D-23 (the depot was on the
> far side of a 34° crater wall, so no haul had ever been physically possible) and
> D-25 (nothing could see wheels turning while the body did not move).
>
> What makes the second run different is a **ground-truth check that is not part
> of the ledger**: at the moment of delivery, Gazebo reported `hauler_02` at
> (−98.669, −149.228) against a `depot` marker at (−100.000, −150.000, −13.860) —
> **1.539 m**. The mass arrived where the marker is.
>
> **The identity itself is still not the interesting check, and this entry says
> so.** `extracted == at_site + in_transit + deposited` is an algebraic invariant
> of `MaterialInventory` (`selene_isru/selene_isru/inventory.py:106-167`):
> `record_extraction` adds to both sides, `record_load` moves mass from `at_site`
> to `in_transit`, `record_unload` moves it to `deposited`, and overdraw is routed
> to `_unaccounted_kg`, which sits **outside** the identity. It can only fail on
> float drift. `MissionProgress.msg` already says this in its own comment. The
> check that can fail is `unaccounted_quantity`, and the number to quote is that
> it came back **exactly 0.0** — not that conservation held.

**Specified** (`docs/PRD.md:546-554`): progress bar reflects material deposited at
the depot; ice extracted / deposited, fleet distance, energy, uptime.

**Was**: `MaterialInventory` had **zero production callers** for `register_site`,
`record_extraction`, `record_load` and `record_unload`. It was constructed and
read, so `extracted_quantity` / `in_transit_quantity` / `deposited_quantity`
were permanently 0.0. The dashboard detected this and printed "delivered mass
not instrumented" rather than a false 0 % — honest, but not the acceptance
criterion.

### It was seven independent breaks, not the two this entry used to name

The original entry named the missing ledger callers and the `mass_kg`/unit
defect. Implementing it found **seven** separate breaks along one chain, any one
of which alone produces a permanent 0.0. Two of them appeared in no register
entry at all before today.

1. **The unit contract was violated in both sim nodes.** `hopper_node` published
   **kilograms** into a field documented as a 0–1 fraction and compared against
   `FILL_THRESHOLD = 0.95` — the hopper reported "full" at 0.95 kg of 20.
   `bin_load_node` had the identical defect against a 50 kg capacity.
2. **The hauler's load cell was subscribed to a topic nothing published.**
   *(Now tracked in its own right as **D-11**.)* `selene_hal/config/hauler.yaml:27`
   declares the load cell on `sensors/load_cell` and `gazebo_hal.py` builds
   `/{robot_id}/{sd.topic}`, but `bin_load_node.py` published
   `/{robot_id}/sensors/bin_load`, which had **zero subscribers** repo-wide. So
   `haul.py` read the `is_valid=False` default forever and every haul reported
   delivering 0.0 kg — for two phases, with no error anywhere and a green suite.
3. **`mass_kg` was never populated by either HAL.** Both built a
   `FillLevelReading` without it, so the skills computed `0.0 - 0.0`.
4. **`GazeboTransferActuator` never reports completion.** `_complete` is set
   `True` only in the constructor and in `cancel_transfer`; `trigger_load` and
   `trigger_unload` set it `False` and nothing sets it back. `haul.py` gated
   both phases on `is_transfer_complete()`, so under the real HAL every haul
   would stall in LOADING until `LOAD_TIMEOUT`. The suite missed it because
   `StubTransferActuator` returns `True` unconditionally.
5. **The haul task targeted the depot instead of the site.**
   `HTNPlanner._generate_cycles` put the depot in `target_location`, while
   `agent_node` read `target_location` as the **pickup** and used the robot's own
   recharge station as the drop-off. A haul drove to the depot, "loaded" a bin
   full of nothing, drove to its charger and dumped it there — never visiting the
   extraction site.
6. **There was no material handoff at all.** `/{rid}/actuators/hopper_cmd` was
   declared in the RCDL since Phase 1 with **zero subscribers**, so an
   excavator's hopper could never empty. The second excavate on the same robot
   would have started already above `FILL_THRESHOLD` and completed in one tick
   reporting 0 kg.
7. **No message on the wire carried mass**, and **`check_conservation()` stated
   the wrong invariant** — it asserted `extracted == in_transit + deposited`,
   omitting mass lying at a site, so it could only ever pass as `0 == 0 + 0` and
   would have failed the moment an excavator ran ahead of a hauler, which is the
   normal state of the pipeline.

### Now: one chain, with a test at every hop (and no live run of the whole)

    sim FillModel.fraction            (0..1, published on the RCDL's own topic)
      -> HAL FillLevelReading.mass_kg (= level * capacity_kg, derived once)
      -> skill delta                  (peak minus initial, a measurement)
      -> MaterialEvent                (agent -> orchestrator, the only mass carrier)
      -> material_event_logic         (dedupe, resolve site from task_id)
      -> MaterialInventory            (register_site/record_extraction/load/unload)
      -> MissionProgress              (real masses + uptime + per-robot energy)
      -> MissionProgress.jsx          (renders them)

**One capacity number, one place.** `capacity_kg` lives in
`selene_hal/config/<type>.yaml` (excavator hopper 20 kg, hauler bin 50 kg) and
is read by exactly two consumers — the HAL, and the sim node via the same
`rcdl_path`. `HOPPER_CAPACITY_KG` survives in `htn_planner` **only** as a
planning heuristic for cycle sizing, which is an assumption and honest as such;
it no longer fabricates a delivered mass.

**Mass is never estimated.** A skill that cannot read its fill sensor publishes
**nothing** rather than a zero — a missing event is honest, a zero is a false
measurement. `MaterialEvent` carries no position field, deliberately: a site is
keyed by an orchestrator-allocated `site_id` resolved from `task_id`, because a
position here would be a dead-reckoned `/odom` pose (see D-08) and two robots at
the same physical place report different coordinates. Keying on position would
silently split one deposit into several and break conservation with nothing
logged.

**Break 2 cannot recur.** `selene_sim/test/test_sensor_topic_coverage.py`
AST-parses `create_publisher` calls out of every `selene_sim` node plus the
`ros_gz_bridge` remappings, and cross-checks both directions against every
sensor declared in `selene_hal/config/*.yaml`. A topic mismatch is invisible in
ROS 2 by construction — a subscription with no publisher is an ordinary state of
the graph during startup, not an error — so nothing can catch it at runtime. Its
allow-lists are themselves checked for rot: an allow-listed entry that somebody
later fixes fails the test and must be removed. It does **not** catch a right
tail under a wrong namespace; that limit is stated in the test.

**Also closed in this requirement.** Fleet uptime is now a real field,
`fleet_uptime_sec`, fed by `FleetMonitor.get_uptime_sec()` — which had had no
production caller. Energy now uses **per-robot** capacity, reported by the robot
on `RobotState.battery_capacity_wh` from its own RCDL (scout 50, excavator 80,
hauler 65) and falling back to 50 Wh for an agent that does not report it; the
single hardcoded 50 Wh understated an excavator by 37.5 % and a hauler by 23 %.
`check_conservation()` now states `extracted == at_site + in_transit +
deposited` and has a real cross-instrument companion, `get_unaccounted_kg()`,
banking every kilogram a hauler's load cell claimed beyond what any excavator
reported extracting — which is exactly what FR-ISRU-2's "no material is lost or
duplicated" means. Both are called in production (`register_site` at
`orchestrator_node.py:1833`, `check_conservation()` at `:798`).
`material_events_applied` is on the wire so the dashboard can tell "nothing
reported yet" from "not instrumented"; its old heuristic — is any mass > 0 — is
also true of a correctly instrumented mission for its first minute of drilling.

**`use_sim_time` is explicitly DEFERRED, not fixed.** `elapsed_sim_time` keeps
its name (renaming a published field breaks the dashboard and PRD MSG-7) and now
carries a comment saying plainly that it is orchestrator wall clock. See open
item 1 below for why a partial fix would be worse than none.

**What was executed**: the whole orchestrator and ISRU half, the HAL unit
arithmetic, the `FillModel` arithmetic, the skill deltas and the topic-coverage
test, all in pytest on this box. Break 4 in particular is demonstrated in the
ROS-free lane by a transfer-actuator double whose `is_transfer_complete()`
returns `False` forever, against which the haul still advances off the load
cell. **What was not**: anything against Gazebo or DDS. Break 4's *live*
behaviour — that a real haul would time out at 30 s — remains a static argument
from the four cited lines; no haul was run to watch it. The fill and drain
timings are arithmetic from the RCDL, not observations, and whether 20 kg and
50 kg correspond to any geometry in `selene_sim/models/*/model.sdf` is
unverified.

### Three further defects, on the delivered path, found after this entry first read "closed"

All three were found by adversarial review of the closure, all three were
reproduced by execution rather than by reading, and all three are fixed. They are
recorded because two of them **re-created the exact behaviour this deviation
exists to remove** — mass appearing from nowhere, and a conservation alarm firing
on a healthy system — which is a stronger argument than any amount of prose that
a closure written on the same day it was implemented is not evidence.

1. **The unload stop condition was a fraction; the fault tolerance was a mass.**
   `HaulSkill.EMPTY_THRESHOLD = 0.02` against the hauler's 50 kg bin is 1.0 kg,
   while `material_residual_tolerance_kg` defaults to 0.5. **MEASURED** by
   co-simulating the shipped `selene_sim.fill_model.FillModel` (capacity and
   `transfer_rate` read from `selene_hal/config/hauler.yaml`, driven at the
   agent's real 10 Hz tick) against the shipped `HaulSkill`: an authorised
   19.0 kg delivered 18.0 kg and reported 1.0 kg residual **on a bin that was
   physically empty**, and 20 of 40 hauls stepped by 0.37 kg reported a residual
   above the tolerance. Every one of those would have emitted an FR-ISRU-2
   instrument-disagreement WARNING against correct behaviour, and left up to
   1 kg per cycle permanently stuck in `in_transit`. The unit suite could not see
   it: its driver jumped the fill level straight to the target instead of
   stepping through the sample the real drain lands on. Fixed by requiring empty
   in **both** units — `EMPTY_MASS_KG = 0.1` beside the existing fraction gate,
   the fraction retained because a sensor whose RCDL declares no `capacity_kg`
   reports `mass_kg = 0.0` for the process lifetime and a kilogram-only test
   would call a full bin empty on the first tick. `ExcavateSkill` was checked and
   **not** changed: 0.02 of a 20 kg hopper is 0.4 kg, inside the tolerance — which
   is arithmetic on the capacity, not a property of the threshold, so it is now
   pinned by a test rather than left to luck.
   `selene_agent/test/test_haul_against_fill_model.py` (13 tests) drives the whole
   ROS-free chain and takes every number from the config files. Mutation-checked:
   restoring the old condition fails 9 of its 10 relevant assertions.

2. **`0.0` meant both "unconstrained" and "authorise nothing".**
   `TaskAssignment.quantity_kg` documents 0.0 as *fill to the robot's own RCDL
   capacity*, and the orchestrator's authorisation helper returned 0.0 for a haul
   against an unregistered or empty site — with a comment saying it was
   authorising nothing. **Executed against the shipped modules**: an authorised
   0.0 made the bin load **50.0 kg**, which fed to `MaterialInventory` gave
   accepted 0.0, unaccounted 50.0 and `check_conservation()` False. Material from
   nothing, plus a bogus conservation breach — the two failure modes D-06 was
   written to eliminate, reachable by three routes (an excavate whose fill sensor
   was unreadable, any of the six drop branches in `material_event_logic`, or a
   haul re-auctioned after its `loaded` event). Fixed by **withholding** the
   assignment instead: `authorise_task_quantity` returns a block reason
   (`haul_no_site` / `haul_no_material`) that doubles as the task's
   `status_reason`, and three gates enforce it — the auction never announces a
   blocked haul, `_resolve_auction` re-checks before assigning (catching a drain
   during the auction), and `_publish_assignment` refuses outright. Alerting is
   latched one-per-(task, reason) so a permanently blocked haul does not warn at
   2 Hz. **The honest cost, and it is a real behaviour change**: a haul whose
   excavate produced no measured mass now **stalls the HTN excavate→haul chain**,
   visibly and with a named reason, instead of fabricating a bin. Nobody has
   watched that stall happen.

3. **Operator-injected excavate and haul tasks reached the ledger with no site.**
   Same defect, same fix, described under D-04.

**This was the deviation that propagated.** It blocked Phase 6 Integration
Demo 1 step 3 (`docs/PRD.md:895`) and SC-1, and it meant FR-ISRU-2's acceptance
could not be demonstrated at all. Those are now unblocked **in code**; the demo
itself has still not been run.

**What "implemented, not demonstrated" cost here specifically, and what running
it then found.** The three defects above were all on the nominal path, all
invisible to a green suite, and all found only because someone re-derived the
chain by executing it. Two existed for a few hours; break 2 (D-11) existed for
two phases. This paragraph used to end "the chain … has never been run end to
end, and the only way to know whether a fourth defect of this shape is sitting
in it is to run it."

**It was run, and there were three more.** D-19: nothing on this chain could
ever start, because the agent recharged after every task and `SelectSite` never
resolved. D-23: nothing on it could ever finish, because the depot was on the
far side of a 34° crater wall. D-27: the conservation alarm at the end of it
fired on every healthy haul, below its own printing precision. **All three were
invisible to the same green suite**, and none of them is a defect in the ledger
code this entry describes — they are in the parameter wiring, the world file and
a tolerance constant. That is what running a chain end to end buys, and it is
the argument for item 4 of the disposition having been the right thing to worry
about most.

---

## D-07 - FR-SIM-7: robot counts and world files not configurable - CLOSED 2026-07-30

**Was**: `simulation.launch.py` declared `num_scouts` / `num_excavators` /
`num_haulers` and then built the fleet from literal `range(2)`, `range(1)`,
`range(1)`. The arguments existed and did nothing. Worse than a no-op:
`unified_sim.launch.py` honours the same arguments for the orchestrator and the
agents and passes them down, so `num_scouts:=3` started a third agent that
registered with the fleet, bid on tasks and won them, with no Gazebo model behind
it. It presented as a coordination bug. The world file and deposit layout were
hardcoded, so clause (d) was unmet too.

**Now**: the file is an `OpaqueFunction`, which is what allows the counts to be
read at all -- a `LaunchConfiguration` cannot be resolved at description time,
which is why the literals were there. Spawn, bridge and sensor nodes are built
from a single fleet list that cannot disagree with itself. `world`,
`ice_config` and `spawn_config` are launch arguments, and
`unified_sim.launch.py` passes all six through.

**No procedural spawn fallback.** Asking for more robots than
`spawn_positions.yaml` describes fails the launch with a message naming the
shortfall and how to survey another pose. Every z in that file is a measured
collision surface plus 0.30 m; inventing one puts a robot inside the terrain,
which is the defect this project spent months on.

So `spawn_positions.yaml` now describes a ten-robot fleet (4 scouts, 3
excavators, 3 haulers), because a configurable count is useless if the config
describes four robots. That is what NFR-1.1 and NFR-1.4 ("up to 10 robots")
need. The six new poses were geometry-checked before being measured -- that
pre-check rejected two candidates at 9.4 m and 8.2 m from the depot, inside its
10 m radius -- then surveyed with `check_terrain.sh` in the same run as the
original four.

**MEASURED, and the first measurement was wrong.** Requesting 4/3/3 initially
reported 5 of 10 models in Gazebo while all ten create nodes logged "Entity
creation successful" -- the signature of querying the wrong server. A leftover
`gz sim` from the previous probe was answering. Re-run with each launch in its
own `GZ_PARTITION` and a straggler check first:

    2/1/1 -> 4 models    scout_01 scout_02 excavator_01 hauler_01
    4/3/3 -> 10 models   all ten, correctly named

`num_scouts:=9` exits 1 naming the file and the shortfall.
`world:=/nonexistent` exits 1 saying so. `check_terrain.sh` reads every entry,
so it now gates all ten poses -- all pass at +0.30/+0.31 m -- and
`check_drive.sh` on `scout_03`, a new pose, drives 98.0% of command and settles
downward.

## D-08 - FR-MAP-4: RViz2 resource-map visualization - CLOSED 2026-07-30

**Was**: nothing existed. `visualization_msgs` had zero occurrences repo-wide;
`selene_sim/rviz/selene_sim.rviz` had two displays (Grid, TF); rviz2 was
launched only from `simulation.launch.py:214-221` behind `rviz:=true`
defaulting false, and `unified_sim.launch.py` - the file the exit gate launches
- had no rviz node. It was also blocked on D-09: no fused posterior existed on
the wire to display.

**Now**: the orchestrator publishes `/orchestrator/resource_map_markers`, a
`visualization_msgs/MarkerArray` holding one `CUBE_LIST` marker with per-cell
`ColorRGBA`, at the same rate and from the same snapshot as the posterior.

Against the four clauses of `docs/PRD.md:451`:

| clause | how |
|---|---|
| (a) OccupancyGrid **or** Marker array | Marker array. `nav_msgs/OccupancyGrid` carries one `int8` per cell, so colour and alpha would both be functions of the same scalar and cannot encode two independent quantities - clause (c) is unrepresentable in it. Verified against the shipped RViz2 library, which exports exactly three compiled-in palettes and one global alpha property. |
| (b) blue (low) to red (high) | A verbatim port of the dashboard's ramp, so the overlay and the dashboard heatmap render the same posterior the same colour - which is what `docs/PRD.md:1504`'s side-by-side comparison requires. Ported, not reinvented. **See the two annotations below: it was not quite verbatim, and the citation moved.** |
| (c) alpha encodes certainty | `variance_to_alpha()`, log-scaled against the map's own prior variance. Log rather than linear because the first reading at a cell takes variance 100 -> **0.2494 at the footprint centre and 0.9926 at its edge** (this cell said "~0.09"; corrected 2026-07-31, see D-02 correction 2 — 0.09 is about where the *third* reading lands); on a linear map those are certainty 0.9975 and 0.9901, and every later reading is lost in the last fraction of a percent of the range. **The bottom of this axis is unreachable with the shipped scout** — see D-02 correction 1. |
| (d) updates in real time | One timer at `resource_map_publish_rate`; measured live at exactly 0.500 Hz. |

**Measured on the running system** (2026-07-30, ROS 2 Jazzy, full
`unified_sim.launch.py`, 256 readings shaped like `ice_deposits.yaml`):
frame_id `map`, CUBE_LIST, ADD, 3779 points and 3779 colours, scale
(1.0, 1.0, 0.2), `pose.orientation.w = 1.0`, per-point alpha 0.453-0.662, ramp
spanning 233 red-dominant and 3546 blue-dominant cubes. **The acceptance
criterion "matches underlying data" is met concretely: the hottest cell,
7.877 wt%, decodes row-major to world (-80.5, -140.5) - 0.7 m from the
`ice_deposits.yaml` deposit centred (-80, -140) with peak 8.0 wt%.**

> ### SUPERSEDED 2026-07-31: the hot-cell figure was measured in the wrong frame
>
> **The "-80.5, -140.5, 0.7 m from the deposit" result above is withdrawn as
> evidence of anything physical.** It was correct arithmetic on a map whose
> indices came from `ResourceMapUpdate.location`, which came from `/odom` — the
> robot's dead-reckoned pose from its own spawn point, rotated by nothing.
> `scripts/check_drive.sh` was run on 2026-07-31 and measured the odom frame to
> be a **full SE(2)**, not the translation the repository had assumed
> (bearing(world) − bearing(odom) = −2.3678 rad against a spawn yaw of −2.3300;
> a translation-only model was off by 2.3678 rad). So the map was self-consistent
> and 133° away from the ground it claimed to describe. The frame is now fixed —
> see **D-33** — and the map is genuinely world-indexed, which means this figure
> describes a coordinate system that no longer exists.
>
> **The replacement figure is not a fleet survey and must not be quoted as one.**
> The exit gate's reworked check 10 (D-29) seeds the map itself, through the real
> `/orchestrator/map_update` fusion path, and the live result on both runs was:
> 1556 observed cells, 1556 cubes, 1556 matching colours, one header stamp,
> frame `map`; hottest cell **7.833 wt%** at flat index **55169**, decoding
> row-major to world **(-80.5, -139.5)**, **0.707 m** from the seeded peak. That
> 0.707 m is the half-diagonal of a 1.0 m cell and it reproduces the offline
> prediction pinned in the probe's own docstring exactly. It demonstrates that
> fusion, sparse encoding and marker publishing are correct. It demonstrates
> **nothing** about robots surveying deposits: the baseline
> `total_observations` was **0** on both runs after ~90 s of real fleet
> operation, and the 3920 observations that produced the number were the probe's
> own.
>
> **And the overlay has still never been rendered.** No RViz2 has been started in
> any run recorded in this document. What check 10 does is recompute the marker
> array from the `ResourceMap` message through `resource_map_viz` and assert
> point-and-colour equality — which shares a module with the publisher, so a
> defect *inside* `resource_map_viz` is invisible to it.

Three traps this had to avoid, each of which fails silently:

- RViz2 ignores the per-point `colors` array entirely when its length differs
  from `points`, falling back to the flat `marker.color` with no error. The
  publisher asserts the lengths are equal.
- That fallback `marker.color` defaults to `(0,0,0,0)` - transparent black - so
  a mismatch would have made the overlay *disappear*. It is set to an opaque
  blue so the failure mode is visibly wrong rather than invisible.
- Per-point alpha blending only engages once some colour has `a != 1.0`, and an
  all-zero-alpha CUBE_LIST raises a marker warning. Alpha is clamped to
  [0.05, 0.85].

**Frames.** Nothing in this repo publishes TF - `/tf` and `/tf_static` have
zero publishers. RViz2 can still transform a message whose `frame_id` is
identical to its fixed frame, so the overlay is published in `map` and
`selene_sim/rviz/selene_sim.rviz` now sets `Fixed Frame: map` (it said `odom`,
which no publisher used - the navigator's `nav_msgs/Path` is already stamped
`map`, so that display would not have rendered either). Expect a yellow TF row
in RViz while the tree is empty; the overlay renders regardless.

~~**Still open, and not an overlay defect**: `ResourceMapUpdate.location` comes
from `/odom`, which DiffDrive dead-reckons from each robot's spawn pose rather
than world coordinates.~~ **CLOSED 2026-07-31 — see D-33.** The prediction in
this paragraph that fixing it would have "knock-on effects on
`battery_node._is_in_psr()` and navigation" was right, and that is exactly what
was done: the conversion happens once in `world_odometry_node`, and
`battery_node`, `hopper_node`, `extraction_node` and
`neutron_spectrometer_node` all moved to `/<rid>/odom_world` together with the
HAL's odometry sensor in all three RCDLs. The frame this paragraph describes no
longer reaches any consumer.

### Three annotations added when D-02 landed

**The port's citation moved, and this register carried the stale one.** Clause
(b) above used to name `iceConcentrationColor()` at
`selene_dashboard/src/utils/colors.js:52-77`. D-02 factored the ramp arithmetic —
unchanged line for line — into `iceConcentrationRGB()`, now at `colors.js:113-135`,
because the dashboard's `posteriorCellRGBA()` needed integer channels rather than
an `rgba(...)` string; `iceConcentrationColor()` at `colors.js:138-141` is a
wrapper around it. The **values** did not change: old and new were compared over
64,010 samples with zero mismatches. Only the pointer was wrong, in this file and
in `resource_map_viz.py`'s own docstring, and both are corrected (2026-07-31).

**The measured cube-colour figures above predate the certainty desaturation.**
Per-point alpha 0.453-0.662 and the 233 red-dominant / 3546 blue-dominant split
were measured against the colour rule **as it stood on 2026-07-30 before D-02**:
hue from `concentration_to_rgb(mean)` alone, alpha from `variance_to_alpha`.
D-02 then added the gray tier FR-DASH-2(b) requires, so `marker_colours` now
routes hue through `certainty_to_rgb`, which lerps toward
`LOW_CONFIDENCE_GRAY (90, 96, 110)` as certainty falls. Alpha is unchanged and
those figures still hold; the **hue** figures describe the superseded rule. The
overlay and the dashboard were changed together and remain a matched pair -
that is the point of the pairing - but the numbers above were not re-measured
after the change, and no run has been made since.

**"A verbatim port" was not exact, and the divergence was real.** JS
`Math.round` rounds half away from zero; Python's built-in `round()` is banker's
rounding. **MEASURED on the Windows box while closing D-02**: sweeping 0-12 wt%
at 0.01, **5 of 1201 samples** differed by 1 in one channel - 0.25 wt% gives
`(18, 50, 161)` in JS and `(18, 50, 160)` in Python, and likewise at 0.75, 1.25,
2.25 and 4.25 wt%. Invisible on screen, and exactly the kind of drift a
"verbatim port" claim is supposed to exclude. `resource_map_viz` now uses
`_js_round(x) = floor(x + 0.5)` and
`selene_orchestrator/test/test_dashboard_colour_parity.py` asserts **exact**
per-channel equality by parsing the constants out of `colors.js`. Before that
test existed, `test_resource_map_viz.py` pinned four boundary values, all of
which happened to be exact, and never read `colors.js` at all.

## D-09 - FR-MAP-1(e)(f): the fused resource map is never published - CLOSED 2026-07-30

**Was**: the orchestrator had exactly four publishers;
`resource_map_publish_rate` was declared (it is now `orchestrator_node.py:880`), set in
`orchestrator_params.yaml`, and never read by anything; `ResourceMap.msg` did
not exist; and the `ResourceMap` class had no serialisation of any kind.

**Now**: `selene_msgs/msg/ResourceMap.msg` exists and the orchestrator
publishes it on `/orchestrator/resource_map` from a timer whose period is
`1.0 / resource_map_publish_rate` - the first timer in the file driven by a
parameter rather than a literal. A rate <= 0 disables publishing with a warning
instead of dividing by zero.

**Sparse snapshot encoding, chosen by measurement.** The grid is 250,000 cells
but only observed ones go on the wire, and every message is a complete snapshot
rather than a delta, so a late or lossy subscriber is correct from the next
message. Measured: 88 bytes of overhead plus 16 bytes per observed cell. A
10-waypoint survey observes ~0.3% of the grid, giving ~12.6 kB against ~3.0 MB
for the equivalent dense float32 grid - a 237x reduction, confirmed by
serialising the real message on Jazzy.

DDS is not what makes the dense form untenable; a 3 MB sample was measured
delivering cross-process over Fast DDS without loss. Two other things are:
rosbridge's `extract_values` burns ~284 ms of GIL-held Python per dense message
per client, in the single process carrying every dashboard topic; and roslibjs
cannot reassemble the fragments rosbridge emits above `max_message_size`, so
oversized messages are dropped client-side in silence. Sparse inverts past ~75%
coverage, which this mission does not approach.

**Anti-regression.** `selene_orchestrator/test/test_no_orphan_parameters.py`
parses `orchestrator_node.py` and fails on any parameter declared but never
read. This requirement was not descoped by anyone - it evaporated because a
parameter existed with nothing behind it and nothing noticed for two phases.
The test carries an explicit allow-list of the two remaining orphans
(`recharge_threshold`, `fleet_state_publish_rate`) so they stay visible.

**Not delivered**: FR-MAP-1(b)'s per-cell last-update timestamp. `ResourceMap`
tracks three grids (mean, variance, count) and no per-cell time, and a per-cell
time array would add ~1 MB per message for a field nothing reads.
`header.stamp` is the map-level acquisition time. That clause remains open.

> **Re-confirmed live 2026-07-31 (evening), on the transport that mattered.**
> The sparse-encoding argument above was measured against DDS and arithmetic
> against rosbridge. The exit gate's check 3 now measures it **through
> rosbridge**, on both runs: the largest `ResourceMap` websocket frame observed
> was **362 bytes**, against a `max_message_size` of 10,000,000. The fragment
> reassembly failure roslibjs would have hit above that limit is not reachable at
> this coverage, which is what the sparse choice was for. Note the frame is small
> partly because the fleet's own map was empty — see the superseded-figure note
> under D-08 — so treat 362 B as a floor, not a typical load.

## D-10 — the exit gate tests less than its report implies — RUN THREE TIMES. THE GATE DOES NOT PASS

> **FOUR CHANGES TO THE GATE, 2026-08-01 (late), after D-42 was root-caused.**
> None of them widens a threshold and none makes a failing measurement pass; two
> of them make the gate refuse to run rather than report a number it should not
> have taken.
>
> 1. **CHECK 11 NO LONGER COMMANDS A ROBOT IT CAN SEE CANNOT OBEY.** The subject
>    was chosen positionally — `eligible[1]`, which at the default 2/1/1 fleet is
>    always `scout_02` — filtered only on `fsm_state not in ('OFFLINE','ERROR')`.
>    On the third run that robot was reporting **0.0 % battery** and was already
>    in **RETURNING** under the energy-critical rule; the gate commanded it, the
>    FSM accepted `OPERATOR_GOTO`, the rule countermanded it 6 ms later, and
>    check 11 reported that as a `send_to_location` failure. It measured the
>    autonomy rule, not the override.
>    **Both facts were in the probe's own recording at the moment it chose.**
>    `select_goto_robot` now picks the first robot in fleet order whose own state
>    says it can obey, against **the agent's own `energy_critical_threshold` read
>    live off `/agent_<rid>`** plus a derived 5-point margin — never a literal,
>    which would be the gate asserting its assumptions (D-12).
>    **THIS IS A PRECONDITION, NOT A RETRY**, and the distinction is D-35's:
>    re-rolling a stimulus after a failure until one passes is forbidden and
>    `run_send_to_location` still refuses to retry a bearing that planned and
>    then failed to move. Choosing a fit subject *before* issuing any stimulus is
>    the opposite move. **PRD row 5 names no robot.**
>    When nothing is fit the check **FAILS LOUDLY** — "NO ROBOT WAS IN A STATE TO
>    ACCEPT THE OVERRIDE" — rather than SKIPping, because a fleet that cannot
>    accept an override is a statement about the system and sends the reader
>    there; the one exception is a probe that can see no state at all, which is a
>    blind instrument and says so (the D-34 rule). 26 ROS-free tests pin all of
>    it, including a replay of the 2026-08-01 fleet that now selects
>    `excavator_01` instead of `scout_02`.
> 2. **THE SEVENTH "WIRED BUT NEVER CALLED", AND THE FIRST INSIDE THE
>    APPARATUS.** `_make_state_cb` captures `battery_level` on every RobotState
>    sample. Its only reader in the entire probe was a `0.0 <= x <= 1.0` range
>    assertion in **check 4**, which `0.0` satisfies — so **check 4 PASSED on a
>    robot reporting zero charge, on the same run whose check 11 that robot took
>    down, and said nothing.** The datum was there the whole time.
> 3. **PORT PRE-FLIGHT, exit 3.** `GZ_PARTITION` isolates this run's Gazebo
>    transport; **nothing isolates TCP**. A rosbridge left behind on 9090 means
>    this run's own bridge never binds — OBSERVED on this box on 2026-08-01,
>    `Unable to start server: [Errno 98] Address already in use`, retrying
>    forever — and checks 3, 5 and 9 then measure a bridge attached to a graph
>    the gate did not start. `missing_nodes()` cannot see it: it tests only for
>    the ABSENCE of expected nodes, so a stale `/rosbridge_websocket` satisfies
>    check 1. That is D-07's "querying the wrong server" on the two transports
>    the partition does not cover, and **it presents as a clean PASS** — the one
>    outcome this entry exists to prevent. The gate now refuses to start, and
>    separately warns (naming the processes) when SELENE nodes are already
>    running, because an orphaned `battery_node` publishes a clamped 0.0 % for as
>    long as it lives (D-42).
> 4. **THE SHELL TIMEOUT WAS SMALLER THAN THE PROBE'S OWN WORST CASE.** Summing
>    every declared ceiling inside the probe gives ~411 s against `timeout 420`,
>    and check 11's 120 s budget was tested only at the TOP of its bearing loop,
>    so one more full bearing could start at 119.9 s and add ~53 s. **There is no
>    SIGTERM handler**, so `timeout` killed the process before the `finally:`
>    that emits, and all ten probe-owned rows came back as "the probe did not
>    report this check" — failing closed, correctly, while destroying the run's
>    information. The budget is now tested again before each motion window and
>    the ceiling is **540 s**.
>
> **Third run, 2026-08-01, and the shape of the failure changed.** Run against
> `9c1a4d7` on ROS 2 Jazzy / Ubuntu 24.04.4 at `2/1/1`
> (`num_scouts:=2 num_excavators:=1 num_haulers:=1`), on a workspace built by
> `scripts/sync_and_build.sh` whose `.selene_source_commit` reads `9c1a4d7`:
>
> | | Run 1 `221355Z` | Run 2 `222000Z` | Run 3 `2026-08-01 00:29:59 CDT` |
> |---|---|---|---|
> | Summary | `8 passed, 1 failed, 2 skipped` | `9 passed, 0 failed, 2 skipped` | `10 passed, 1 failed, 0 skipped` |
> | Exit code | **1** (a FAIL) | **2** (a SKIP) | **1** (a FAIL) |
>
> **ZERO SKIPS IS THE RESULT.** Checks 6 and 9 SKIPped on both earlier runs and
> cost PRD exit-gate rows 3 and 4 outright. On this run both produced verdicts
> and both PASSed — **check 6** with the injected task `manual_0000` announced
> **0.71 s** and assigned to `scout_01` **11.21 s** after injection, target
> matched to 1e-3; **check 9** with a websocket transport latency of **5 ms,
> median of 554 samples**. Those two rows have never been measured before. That
> is D-34 closed, and it is closed on the gate's own regenerated report rather
> than on a unit test.
>
> **The gate still does not pass, and the reason is not the system and not the
> instrument's aim.** Check 11 FAILed: `scout_02`'s planned path ended **4.54 m**
> from the commanded target, and it ended there because the robot the gate picked
> was reporting **0.0% battery**, so the energy-critical rule overrode the
> operator command **six milliseconds** after the FSM accepted it. **That 0% is
> D-42 and its cause is unknown.** What check 11 is missing is a precondition —
> it never asks whether the robot it selected can perform the manoeuvre — and
> that is a real gap in the gate, distinct from D-35's aim problem, which this
> run shows was fixed.
>
> **D-35's repairs are visible inside the failure line itself**, which is the
> cleanest evidence available that they are in force: the bearing was chosen at
> `+45 deg off heading 0.691 rad` rather than due east, and the window was
> `11.0s derived at 0.50 m/s from .../selene_hal/share/selene_hal/config/scout.yaml`
> rather than a hard 12 s. Both of D-35's unrepaired reporting defects are also
> repaired: the FAIL message now carries the `path_note` (`planned_path ends
> (-29.50, -99.50), 4.54 m from the commanded target`), which run 1 withheld, and
> the PRD coverage column now states that the displacement is read off
> `/<rid>/odom_world` carrying the simulator's **true world pose** rather than
> repeating the stale "STILL DEAD-RECKONED" caveat.
>
> **The report was regenerated BY that run**, to
> `$HOME/selene/phase5_validation_report.md`, source commit `9c1a4d7`. It is not
> hand-edited and it is not green, so it prints no green-run paragraph.
> `docs/phase5_validation_report.md` **in the repository is still the superseded
> eight-check gate at `251e84d`** and must not be quoted; committing the new one
> is not this document owner's file to commit.
>
> **One thing check 6 measured is worth reading before the PASS is over-read.**
> The probe still could not find a naturally IDLE prospect-capable robot: it
> waited its full **60 s**, no robot became IDLE in that window, and it then
> freed `scout_01` with an operator `cancel_task` and measured on the robot it had
> perturbed — which the report says in the row. **That is fleet behaviour, not a
> sampling defect**: all four robots were genuinely busy. What D-34's fix bought
> is that the IDLE the cancel produced was *observable*: `scout_01` sat in IDLE
> for **0.220 s** (`297.9157` → `298.1354` in the launch log) and the gate
> recorded an IDLE state sample inside it. A 0.5 s timer alone catches a 0.220 s
> window less than half the time, so this is consistent with publish-on-transition
> carrying it and is **not by itself proof** that it did.

The 2026-07-31 status block follows, unchanged, because it is the record of the
first two runs and of what they cost.

> **Status changed 2026-07-31 (evening), and this is the headline of the whole
> amendment.** The rewritten gate had never been executed. It has now been
> executed twice, identically (`2/1/1`, `prebuilt:=true`), on ROS 2 Jazzy /
> gz-sim 8.11.0 / Ubuntu 24.04.3 against a workspace that built 6 packages with 0
> errors. Two runs rather than one, because one run cannot separate a sampling
> race from a deterministic defect — and it was necessary, because the two runs
> disagree.
>
> | | Run 1 `221355Z` | Run 2 `222000Z` |
> |---|---|---|
> | Summary | `8 passed, 1 failed, 2 skipped` | `9 passed, 0 failed, 2 skipped` |
> | Exit code | **1** (a FAIL) | **2** (a SKIP) |
>
> **Neither run is green, and by the gate's own contract exit 2 is not a pass.**
> Checks 6 and 9 SKIPped on both runs; check 11 FAILed on run 1 and PASSed on
> run 2. Diagnoses are **D-34** (the gate cannot observe an FSM state shorter than
> its sampling period; both SKIPs are this, on a system that satisfied the row)
> and **D-35** (check 11 is a coin flip; 33 cm of x-displacement separated the two
> outcomes). **Both are defects in the measuring apparatus, not in the system,
> and neither was patched** — altering the instrument until it stops reporting a
> problem is the move this register exists to prevent.
>
> **Two claims this entry made are now settled by having run it.** The two
> "unaudited structural assumptions" below — that `GZ_PARTITION` reaches the
> launch's `gz sim`, and that an rclpy `MultiThreadedExecutor` on a background
> thread coexists with a tornado IOLoop in one process — both held: the probe ran
> to completion, recorded 23 nodes and drove the websocket, on both runs.
> `tornado` was importable. **The five review-found defects were all in a gate
> that then behaved as described**, which is worth recording as the one case in
> this repository where pre-run review of a gate paid off directly.
>
> **The prior claim of "11/11 twice" is superseded.** Two earlier passing runs
> are recorded in this workstream's ground truth. Both passed check 10 on a map
> with `total_observations = 0` — the assertion never executed. That is D-29,
> now fixed and demonstrated. **A gate that passed vacuously is worse evidence
> than a gate that fails honestly**, and this entry treats the 8/1/2 and 9/0/2
> results as the first real readings the gate has produced.
>
> **`docs/phase5_validation_report.md` is still stale.** Both runs wrote their
> report to a run directory under `/root`, and the committed copy was
> deliberately not overwritten from a non-green run by a document owner who does
> not own that file. It still describes the superseded eight-check gate at commit
> `251e84d`. Regenerating it is item 1 of the disposition.

**Was**: eight checks, all passing. One of the PRD's seven exit-gate rows
(`docs/PRD.md:1499-1509`) had a real end-to-end check — and it tested a
different override than the row it was credited against. Three rows had weak
liveness proxies: check 1 was `kill -0` on the launch PID, which `ros2 launch`
satisfies with Gazebo dead because no launch file converts a child exit into a
shutdown; check 4 counted topic *names* ending `/state` and asserted nothing
about content, rate or the dashboard; check 2 was `curl` returning 200, which a
static file server satisfies with a broken bundle. Three rows had no check at
all. The report footer nonetheless read as a pass, and it also carried the
self-signed FR-MAP-4 waiver this document exists to replace.

**Now**: eleven checks, evaluated by one long-lived rclpy probe
(`scripts/phase5_probe.py`) with a continuous ~32 s recording window into which
the inject and override stimuli are issued at known offsets, so rate, freshness
and latency become measurable — none of which is possible with
`ros2 topic echo --once`. Coverage against the PRD's rows:

| PRD exit-gate row | Checks | Coverage |
|---|---|---|
| Dashboard shows all robots with correct real-time state | 4 | content, freshness and rate on every `/{rid}/state`: rate as `(n-1)/(t_last-t_first)` so discovery settling does not bias it, `fsm_state` against `AgentState` **imported** from `selene_agent.fsm` rather than a copied literal list, and the publisher set required to **equal** the derived fleet, not merely cover it. Plus `/rosapi/topics_for_type` over the websocket — the actual code path `useFleetDiscovery.js` uses, and the closest headless proxy to "the dashboard shows" that exists. |
| Resource heatmap matches RViz2 visualization | 10 | the posterior and the marker array are paired by their byte-identical `Header` stamp (one `Header` is built and assigned to both), and the marker is **recomputed independently** from the `ResourceMap` message alone through `resource_map_viz`. Asserts point and colour equality, the `len(colors) == len(points)` condition whose failure D-08 documents as silent, and `frame_id` equal to both the parameter and the `Fixed Frame` in the `.rviz` file. **No image is compared and no RViz2 is run.** |
| Task queue reflects orchestrator state within 1 second | 9 | two latencies off the assignment check 6 already causes: transport (WS arrival minus the message's own `stamp`, < 250 ms) and reaction (first `TaskQueueState` showing the task ASSIGNED, minus the DDS observation of its `TaskAssignment`, < 1.0 s). **Bounds the row from below only** — the 2 Hz snapshot carries up to 500 ms of quantisation and the React reducer plus canvas draw are unmeasured. It can prove a FAIL; it proves a PASS only up to the rendering step. |
| Operator-injected task enters auction and gets assigned | 5, 6 | the injected `task_id` is now **correlated**: announcement and assignment must carry that exact id, `target_location` must match the injected point to 1e-3, and the winner must hold the required capability. Injection goes over the **rosbridge websocket** — the transport the dashboard uses — falling back to the ROS service and naming the transport in the report row rather than degrading silently. |
| Robot override (send-to-location) works | 11 | the row's own override, at last. Service success, `NAVIGATING` within 3 s, pose displacement > 0.2 m with a positive dot product against the target bearing, and `/{rid}/planned_path`'s last pose equal to the commanded target — that last one is what proves the *target* was honoured independently of the odom-frame problem. |
| Single launch command starts full system | 1, 2, 3 | three independent authorities instead of a PID: the derived node set present; **Gazebo actually stepping** (`sim_time` increasing across two reads, plus `gz model --list` containing every robot); and required topics with publisher count >= 1. Check 2 now requires a real compiled bundle (content-type, size, not `<!doctype`, and the `ws://localhost:9090` and `/orchestrator/inject_task` literals present). Check 3 requires rosbridge to **speak the protocol** — subscribe and receive a `publish` frame — and records the `ResourceMap` frame size against `max_message_size`, a live regression guard for D-09's sparse encoding. |
| Dashboard renders at 1 Hz with 4 robots without lag | none | **NOT COVERED**, with the reason generated into the report: frame timing and dropped frames are visible only in devtools, and no browser is started anywhere in this gate. **Check 2 must not be read as a proxy for it.** |

Checks 7 and 8 (`force_recharge` and its FSM consequence) cover no PRD row and
are listed as such in `EXTRA_CHECKS`, kept because check 8 was the one
end-to-end path the pre-D-10 gate had.

**PASS / FAIL / SKIP, and the exit code carries the lesson.** A SKIP is a
measurement that could not be taken and is never counted as a pass. Exit 0 only
when every PRD row is PASS or an explicitly listed NOT COVERED row; 1 on any
FAIL; **2 on any SKIP**. The old two-way `check()` had no way to say "the fleet
never went idle, so this row was not tested" and would have had to choose
between a false PASS and a misleading FAIL.

### Five defects in the new gate, found by review before it was ever run

The rewritten gate was reviewed as adversarially as the code it certifies, and
every one of the five findings was the same species as D-10 itself: a claim — in
a check, in the report, or in a comment — that outran what the gate actually
does. All five are fixed. They are listed because a gate whose whole purpose is
to stop a report overstating its evidence has to survive being read that way
itself.

1. **PRD row 3 would have SKIPped on a correct system, and blamed the wrong
   thing.** Check 9 sampled the websocket buffer once, ~0.2 s after the
   assignment, while `/orchestrator/task_queue` is published only from a 2 Hz
   timer with no publish-on-change — so roughly 40% of healthy runs would have
   SKIPped, exit 2, with text blaming a missing message type for what was a probe
   timing bug. It now polls to
   `assigned_at + MAX_QUEUE_REACTION_SEC + QUEUE_POLL_MARGIN_SEC` and **FAILs**
   on timeout; the message-type-absent case is passed in explicitly from `main`
   and is the only remaining SKIP.
2. **PRD row 4 raced the orchestrator's own auction tick.** The probe freed a
   robot and *then* injected, so a survey task at priority 5.0 could win the
   freed scout before the priority-10.0 injected task existed, failing the row on
   a healthy fleet. The order is now inverted — inject first, free second — and
   `correlate_injection`'s budget starts when a robot is known idle, with the
   latency still reported from the injection and the idle wait stated separately.
3. **The generated coverage table printed a bare `PASS` for rows whose PRD method
   was never performed** — a regression against the very table in this register
   it replaced, which had a qualitative Coverage column. `ROW_COVERAGE_KIND` is
   now a fourth, index-aligned array printed as a fourth column, and
   `test_phase5_gate_coverage.py` requires every row to declare `end-to-end`,
   `proxy: <what is and is not measured>` or `not covered`. Rows 1, 2 and 5 read
   as proxies naming their unmeasured half.
4. **The report's "Does mean" paragraph was a hardcoded literal** printed on
   every run regardless of result, and it asserted two things the checks do not
   prove: that the resource map stayed under `max_message_size` (check 3 PASSes
   with that guard explicitly unexercised when no map frame arrives in the
   window) and that the injection used the dashboard's transport (check 5 falls
   back to the rclpy service). It is now generated from the probe's own JSON
   record and withheld entirely unless the run is clean.
5. **The probe's provenance header contradicted four measurement claims inside
   the same file.** It said "NOT EXECUTED ANYWHERE YET" while four comments
   recorded HTTP measurements. Resolved by *running the half that could be run* —
   check 2 standalone against `python -m http.server` over
   `selene_dashboard/build` — and splitting the header: the ROS half has never
   been executed, the HTTP half was, on 2026-07-30. That run corrected two of the
   four claims (the bundle is 282,106 bytes, and the content-type came back
   `application/javascript`, not `text/javascript`); the load-bearing part, that
   `http.server` sends `Content-type` with a lower-case "t" so a
   `dict(headers)['Content-Type']` lookup misses it, survives and is now sourced
   to CPython's literal.

**The footer is generated, not written.** `PRD_ROWS` (verbatim from
`docs/PRD.md:1503-1509`), `ROW_CHECKS`, `ROW_COVERAGE_KIND`,
`NOT_COVERED_REASONS`, `EXTRA_CHECKS` and `CHECK_CATALOG` live in the script, and
every coverage statement in every report it writes is produced from them.
`selene_orchestrator/test/test_phase5_gate_coverage.py` — ROS-free, importing
nothing from `selene_orchestrator` — asserts the row text matches `docs/PRD.md`
byte for byte, that every PRD row is mapped (`none` being legal and explicit),
that every mapped check number is actually emitted by a `check` call, that no
emitted check is unmapped, and that every row states its coverage kind. **This is
to D-10 what `test_no_orphan_parameters.py` is to D-09**: the specific failure was
a gate covering less than its report implied with nothing connecting the two, so
the connection is now executable.

~~**The gate was NOT RUN.**~~ **It was, on 2026-07-31 — see the status block at
the top of this entry.** The paragraph that stood here is kept in outline
because its list of unknowns is now a list of answers. Everything above was the
script as written, verified by reading it and by the ROS-free coverage test;
`validate_phase5.sh` needs WSL2 with ROS 2 Jazzy, Gazebo, rosbridge and a built
colcon workspace, none of which existed on the box the closure was written on.
Node names as they appear in `ros2 node list` were derived from launch-file
source, not observed — **they are now observed**: 23 expected nodes present on
both runs, and the orchestrator appears as `/orchestrator_node`, which is the
spelling D-12's fix produced and which `EXPECTED_NODES` asserts. The two
structural assumptions called "unaudited and must be validated on the WSL2 box
before this gate is trusted" — `GZ_PARTITION` inheritance, and an rclpy
`MultiThreadedExecutor` beside a tornado IOLoop in one process — **both held**,
and `tornado` was importable. The timing figures in the script were estimates and
two of them turned out to be wrong in the direction that matters: see D-34 and
D-35.

Two further things about the gate that cannot be checked here, added
2026-07-31:

- **`shellcheck` is not installed on this box.** `.github/workflows/ci.yaml`
  runs `shellcheck -S warning scripts/*.sh`, and that job's outcome for the
  rewritten `validate_phase5.sh` is therefore **unknown**. An earlier report in
  this workstream claimed a clean run at shellcheck 0.11.0; that claim could not
  be reproduced (`which shellcheck` is empty) and is not repeated here. CI's apt
  shellcheck is 0.8.0 in any case. `bash -n` and `python -m py_compile` are what
  was actually run, and both are clean.
- **Every `file:line` citation inside the probe and the shell script points into
  files that were being edited concurrently.** They were swept and re-verified
  against the working tree, but they are citations into uncommitted code and will
  drift again if any owner touches those files before this branch is committed.

**`docs/phase5_validation_report.md` was deliberately left untouched.** It is
the output of a real run and must be regenerated by one, not hand-edited — a
hand-written validation report is precisely the failure this deviation exists to
name. The committed copy is therefore **stale in three ways** and should be read
as a historical artifact until a WSL2 run replaces it: it predates D-07, D-08
and D-09; it carries the false FR-MAP-4 footer, which D-08 closed; and it
describes the old eight-check numbering, which no longer exists.

**Correction to the record.** This document previously stated the gate "passes
8/8 on three consecutive runs". That is wrong, and it was wrong when written:
`docs/phase5_validation_report.md` records **one** run, at commit `251e84d`,
timestamped 2026-07-30 10:18:10 CDT. There is no evidence in-tree of a second or
third.

---

## D-11 — the hauler's load cell was subscribed to a topic nothing published — CLOSED 2026-07-31, DEMONSTRATED BY CONSEQUENCE

Given its own number on 2026-07-31. It was already recorded as "break 2" inside
D-06 and is fixed by that same change, but it deserves a number because **it is
the single reason the haul path delivered nothing for two phases**, and because
the failure mode is one this repository will meet again.

**Was**: `selene_hal/config/hauler.yaml:27` declares the load cell with
`topic: sensors/load_cell`, and `GazeboHal` builds a subscription on
`/{robot_id}/{sd.topic}` — so `/hauler_01/sensors/load_cell`. But
`selene_sim/selene_sim/bin_load_node.py` published `/{robot_id}/sensors/bin_load`.
The two names never met. `HaulSkill` therefore read the `is_valid=False`
dataclass default on every tick for the life of the mission, and every haul
reported delivering 0.0 kg.

**Why nothing caught it, and this is the part worth keeping.** A ROS 2
subscription with no publisher is not an error — it is the ordinary state of the
graph during startup, and it is indistinguishable from "the publisher has not
come up yet" forever. Nothing logs it, nothing times out, `ros2 topic list` shows
both names as real topics, and the fill sensor's own interface reports a valid
dataclass with `is_valid=False` rather than raising. The unit suite could not see
it either: it exercised the skill against a stub sensor supplied by the test,
never against a topic name. So a green suite, a clean launch and a running fleet
were all consistent with a hauler whose load cell had never once been read.

**Now**: `bin_load_node.py:73-74` publishes `/{robot_id}/sensors/load_cell`, and
the identical class of defect elsewhere in the tree is closed by an executable
check rather than by care. `selene_sim/test/test_sensor_topic_coverage.py`
AST-parses the `create_publisher` calls out of every `selene_sim` node together
with the `ros_gz_bridge` remappings and cross-checks **both directions** against
every sensor declared in `selene_hal/config/*.yaml` — a declared sensor with no
publisher fails, and a published sensor topic no RCDL declares fails. Its
allow-lists are themselves rot-checked: an allow-listed entry somebody later
fixes fails the test and must be removed.

**Fails-before was demonstrated, not assumed**: run against `git show HEAD`
copies of the sim nodes, the parser reported the published tails as
`['battery_state', 'extraction/rate', 'extraction/total', 'sensors/bin_load',
'sensors/hopper_fill', 'sensors/neutron_spec']` — no `sensors/load_cell` — and
the test failed in both directions.

**Still open in this shape, and allow-listed rather than fixed**: `sensors/depth`
and `sensors/imu` are declared by all three RCDLs and published by nothing on any
robot type. Any skill that reads them gets `is_valid=False` forever, exactly as
the load cell did. Pre-existing, out of D-06's scope, and now at least visible —
see open item 11.

~~**Not demonstrated.**~~ **DEMONSTRATED 2026-07-31 (evening), by the only
evidence that could settle it.** The topic name was checked by an AST test and
by no running graph. It has now been exercised implicitly and unambiguously:
five hauls completed on a live ten-robot run, each logging
`Haul complete: loaded=19.0kg delivered=…`, and `HaulSkill` reports a **measured
delta from the load cell** or publishes nothing at all. A non-zero `loaded` is
only reachable if `/hauler_02/sensors/load_cell` had a publisher and the
subscription matched it. Before this fix every haul reported 0.0 kg for exactly
this reason.

**Still not directly observed**: no `ros2 topic info` has been run against the
topic, and the AST test still does not catch a correct tail published under a
wrong namespace — a limit stated in its own docstring. What was observed is the
consequence, not the topic.

---

## D-12 — `orchestrator_params.yaml` is never applied to the orchestrator — CLOSED 2026-07-31, DEMONSTRATED BY PERTURBATION

Found 2026-07-31 while verifying D-10. Pre-existing; not introduced by this
work; **latent today and live the moment anyone tunes a value**.

The parameter file's top-level key is `orchestrator_node:`
(`selene_orchestrator/config/orchestrator_params.yaml:1`), but the launch file
starts the node under a different name — `name='orchestrator'`
(`selene_orchestrator/launch/orchestrator.launch.py:25`) — and ROS 2 matches a
parameter file against the node's **runtime** name. The file is loaded
(`orchestrator.launch.py:28`) and then matches nothing in it, so every parameter
falls back to its `declare_parameter` default.

**Verified programmatically here**, because it matters whether this is a live
bug or a trap: every key in that file that the orchestrator declares currently
holds a value **identical to its declared default**, so behaviour today is
correct by coincidence. The file is documentation that looks like configuration.
The first person to change a number in it will find the change silently ignored,
and will have no signal of any kind — no warning, no error, no log line.

~~**Not fixed here.**~~ **FIXED AND DEMONSTRATED 2026-07-31.**

**Now**: `name='orchestrator'` is **deleted** from
`selene_orchestrator/launch/orchestrator.launch.py`, so launch_ros leaves the
node's own name alone and the runtime name is `orchestrator_node` on every entry
path — `ros2 run`, this launch file, and `unified_sim.launch.py` which includes
it. The alternative fix, renaming the YAML key to `orchestrator`, was rejected
for a reason worth keeping: `scripts/start.sh` passes the same file to `ros2 run`
with no name remap and therefore **did** match it, so that fix would have
repaired the launch path and broken `start.sh` in exactly the same silent way.
Two entry points, two node names, one file that could only ever match one of
them. The module docstring records the whole argument.

**MEASURED, by perturbation, which is the only measurement that proves it.**
`resource_map_max_marker_cells` was set to a deliberately absurd `12345` in the
params file and the running node was queried: it **held 12345**. Before the fix
the same perturbation would have been silently ignored and the node would have
held its declared default, with no warning, no error and no log line. The node
appears in `ros2 node list` as `/orchestrator_node` on both exit-gate runs,
which is what `EXPECTED_NODES` asserts.

**Anti-regression**: `selene_orchestrator/test/test_params_files_are_applied.py`
parses the launch file and the YAML and fails if the top-level key and the
runtime name ever disagree again. **`test_no_orphan_parameters.py` still cannot
catch this class** — it detects declared-but-never-read, which is the orthogonal
failure — and that is precisely why a second, differently-shaped test was needed
rather than an extension of the first.

---

## D-13 — three bid weights configure nothing where they sit — FIXED 2026-07-31, NOT DEMONSTRATED BY PERTURBATION

Found 2026-07-31 with D-12; same file, different defect, also pre-existing.

`bid_weight_distance`, `bid_weight_energy` and `bid_weight_capability` sit in
`selene_orchestrator/config/orchestrator_params.yaml:6-8`, which only the
orchestrator loads — and the orchestrator **never declares them**. Verified here
by parsing every `declare_parameter` call out of `orchestrator_node.py` and
diffing against the file's keys: those three are the entire set present in the
YAML and absent from the node. ROS 2 drops undeclared overrides rather than
erroring, so they are inert.

Bidding is scored on the **agent** (`selene_agent/agent_node.py:629-641`, from
parameters declared at `:114-116`), and `agent.launch.py` passes the agent an
inline parameter dict with no file — so the agents always use their own hardcoded
defaults. The values happen to be identical, which is why this has produced no
symptom.

~~Recorded here rather than moved, because moving live tuning values between
packages without being able to run either node is not a safe edit from this
box.~~ **FIXED 2026-07-31.**

**Now**: the three weights sit in `selene_agent/launch/agent.launch.py:87-89`,
in the inline parameter dict that reaches the agent, which is the node that
declares them (`agent_node.py:145-147`) and reads them when it scores a bid
(`:717-719`). They are gone from `orchestrator_params.yaml`, which keeps a
comment at the point they used to occupy so that the next person to look for
them finds out where they went and why. The values are unchanged (0.4 / 0.35 /
0.25), so no behaviour moved with them — this fix makes a knob turn, it does not
turn one.

**Not demonstrated the way D-12 was.** Auctions ran live and produced real scores
(`score=0.996`, `score=0.915`, `score=0.872` among many), so the scoring path is
exercised — but **nobody perturbed a weight and read it back from a running
agent**, which is the only thing that would prove the launch dict reaches the
parameter the way D-12's `12345` proved it for the orchestrator. Fixed and
argued from the code; not measured.

---

## D-14 — the ROS-free stubs broke any pytest process that spans two packages — FIXED 2026-07-31, RECORDED 2026-07-31, NOT DEMONSTRATED UNDER ROS

**Introduced by this work.** Found 2026-07-31 by executing the command
`README.md:236` documents, which had not been run since the stub was added.

`selene_orchestrator/test/conftest.py` installs process-global fake ROS modules
into `sys.modules` so the orchestrator can be imported with no ROS present. D-06
needed it to grow an `rclpy.qos` stub, because `orchestrator_node` now builds an
explicit QoS profile for the two ledger topics. pytest imports the conftest of
every initial argument's directory **before** collection, so that stub is in
place before any other package's tests are imported — and it is incomplete
relative to real `rclpy`, which exports `ReliabilityPolicy` / `DurabilityPolicy`
as aliases of the `QoS*` names. `selene_hal/selene_hal/gazebo_hal.py:32` imports
exactly those aliases.

The result is that `pytest.importorskip` in
`selene_hal/test/test_gazebo_fill_level.py` no longer sees a missing module — it
sees a module that exists and raises `ImportError` — and the run **aborts at
collection** instead of skipping.

**MEASURED, both sides:**

    working tree, README's own command  -> Interrupted: 1 error during collection
    same command against `git archive HEAD` -> 314 passed

Both orders of the four suites fail identically, so this is not an ordering
effect. It reproduces with any invocation naming both `selene_orchestrator/test`
and `selene_hal/test` in one process.

**It was not a one-line fix**, which is why it was first recorded rather than
patched: adding the two `rclpy.qos` aliases in a scratch copy moved the failure
one import further, to `std_msgs.msg.Float32`, which the same conftest also
stubs incompletely. The stubs are shaped for the orchestrator's needs and the
HAL needs a different subset.

**What it did and did not break.** No CI job ran a cross-package pytest
invocation: the e2e job runs one file, the gate-coverage job runs one file, and
`colcon test` runs each package in its own process. The per-package commands in
this register's "Verification limits" were unaffected and all passed. What was
broken is the documented developer workflow, and the claims at `README.md:147`
and `README.md:207` that the suite runs all four packages in one process in
either order — true at `bab8af6`, not true between then and the fix.

### The fix: the stubs are scoped, not completed

**The diagnosis that mattered is that "missing name" was never the invariant
being violated.** The stub set is closed only over `orchestrator_node`'s
imports; the repository's full ROS import surface also includes
`std_msgs.msg.{Float32,Bool,String}`, `sensor_msgs.msg.{Image,Imu,BatteryState}`,
`nav_msgs.msg.{Odometry,Path}` and `geometry_msgs.msg.{Twist,Pose2D,PoseStamped}`.
Chasing names would have been endless. The defect is that a stub shaped for one
package was visible to every other package in the process.

So the **installation** is scoped rather than the stub set completed
(`selene_orchestrator/test/conftest.py`, rewritten). The stub objects are still
built once, eagerly, at conftest import — pure stdlib, no third-party import,
which the `gate-coverage` CI job needs since it installs pytest and nothing
else. Only their entry into `sys.modules` is confined, to two `try`/`finally`
windows, both filtered to this conftest's own directory:

1. `pytest_make_collect_report` as a hook wrapper, filtered on `collector.path`
   — that hook is where `Module.collect()` runs a test module's top-level
   `from selene_orchestrator.orchestrator_node import ...`;
2. an autouse fixture, which in a conftest applies to that directory only —
   needed because `test_conftest_mirrors_msgs.py` reads
   `sys.modules['selene_msgs.msg']` at *call* time and would otherwise degrade
   to vacuous passes.

`install_ros_stubs()` became `build_ros_stubs()`; `pytest_sessionfinish` is kept
as a no-op backstop. The conftest docstring gains rule 4, "never visible outside
this directory", and carries an explicit comment saying the
`ReliabilityPolicy` / `DurabilityPolicy` aliases are omitted **on purpose** —
completing them would let `selene_hal`'s Gazebo tests run against hand-written
fakes in one invocation and skip in another, which is a worse defect than the
one being fixed and is the same species as `StubTransferActuator` hiding D-06
break 4.

**Guarded by a test and by CI.** `selene_hal/test/test_ros_stub_isolation.py`
(3 tests) asserts that no module in `sys.modules` carries
`__selene_test_stub__`, runs a real cross-package pytest **subprocess** (the
defect is a property of pytest startup and cannot be reproduced in-process), and
pins the cross-file skip message so the subprocess assertion cannot rot into a
tautology. `selene_hal/test/test_gazebo_fill_level.py` gains a module-level
`pytest.skip(..., allow_module_level=True)` when `sys.modules['rclpy']` carries
the stub marker — a seatbelt that turns a future leak from "zero tests run" into
one skip, and which the regression test asserts never fires. A new
`cross-package-tests` job in `.github/workflows/ci.yaml` runs all five packages
in one process in **both orders** on a `pytest_spec: ['pytest<8', 'pytest']`
matrix, independent of `e2e-integration` for the same reason `gate-coverage` is:
a guard must not sit behind a gate that does not run.

**MEASURED here on 2026-07-31, pytest 9.1.1, by this register's owner rather
than taken from the fixer's report:**

    PYTHONPATH="selene_orchestrator;selene_isru;selene_hal;selene_agent" \
      python -m pytest selene_orchestrator/test selene_isru/test \
                       selene_hal/test selene_agent/test -q
      -> 542 passed, 1 skipped in 1.71s

    ... same four, reversed order                 -> 542 passed, 1 skipped in 1.70s

    all five packages, one process                -> 604 passed, 1 skipped in 2.19s

Those three figures are a **record of that moment**, not the current baseline.
Re-measured on the evening of 2026-07-31 they are 826/1, 120/1 and 947/1; see
Verification limits item 19, and note the two-package lane regression below.

The single skip is the honest one (`selene_hal`'s Gazebo backend needs a real
`rclpy`). These figures are **six higher** than the fixer's report records
(536 / 598) because the D-02 repair landed six further tests between the two
runs; the invariant is that the combined run completes and matches across
orders, not the absolute number.

**The pytest-version claim that was untested is now tested, and it went the
other way.** This entry used to say the `pytest<8` pin CI uses "may skip rather
than abort" and that this "was not tested". It was subsequently measured against
the pre-fix conftest: pytest 9.1.1 aborts at collection, pytest 7.4.4
**silently skips** the victim module. So on the CI pin the bug was invisible
rather than absent — which is why the new CI job runs a matrix over both
versions rather than one. That measurement was made by the fixer, not
reproduced here; only one pytest (9.1.1) is installed on this box.

**Not demonstrated under ROS.** The branch of the conftest where the real
`rclpy` and `selene_msgs` win — `_stub_module` returns `None`, `_STUB_MODULES`
stays `{}` and both windows become no-ops — is reasoned from the code, not
executed. ~~`colcon test` has not run.~~ **`colcon build` has now run** — six
packages, zero errors, on ROS 2 Jazzy, repeatedly, on 2026-07-31. `colcon test`
still has not, and neither has `actionlint` or `shellcheck` against the new
workflow job.

> **REGRESSION FOUND 2026-07-31 (evening), while re-measuring these lanes: the
> two-package lane this entry certifies is RED again, for a different reason.**
>
>     PYTHONPATH="selene_orchestrator;selene_isru" \
>       python -m pytest selene_orchestrator/test selene_isru/test -q
>       -> 1 failed, 518 passed
>
> `selene_orchestrator/test/test_terrain_guard.py:343` does a bare
> `from selene_agent.navigator import OccupancyGrid` inside a test body, with no
> `importorskip` and no guard, so the lane fails rather than skips when
> `selene_agent` is not on the path. **The lane that broke is the one this
> register calls "THE GATE LANE"** and lists in Verification limits, and it is
> the lane the CI `e2e-integration` job's `PYTHONPATH` describes. It is D-36, and
> it is D-14's own lesson arriving from the other direction: D-14 was a
> single-package assumption breaking a cross-package run; this is a
> cross-package assumption breaking a single-package run. **Neither the CI
> cross-package job nor the operator's Windows lane can see it**, because both
> put every package on the path.

---

## D-15 — the heatmap raster cache key collides across a rosbridge reconnect — CLOSED 2026-07-31, FIXED AND MACHINE-CHECKED

> **Status changed 2026-07-31 (evening).** The fix took the first of the two
> designs this entry named: a monotonic counter that lives **outside**
> `resourceMap` and that `RESET` does not zero. `initialState.resourceMapRevision`
> is 0 (`useFleetState.js:37`), `UPDATE_RESOURCE_MAP` issues
> `state.resourceMapRevision + 1` (`:314`) and stores it back on the state root
> (`:317`), and `case 'RESET'` explicitly carries it through
> (`:380 — resourceMapRevision: state.resourceMapRevision`) with a comment saying
> why: it is a cache key, not session data.
>
> **The "Monotonic and O(1)" comment this entry blamed is corrected in place.**
> That claim was the thing that made the old code look safe, and it is now
> replaced by a comment that states the failure mode it used to hide.
>
> **Machine-checked, and this is new for the dashboard.**
> `selene_dashboard/src/__tests__/fleetState.resourceMapRevision.test.js` drives
> the real reducer across a RESET and asserts that no revision value is ever
> issued twice in a tab's lifetime. There was no JS test runner in this
> repository when this entry was written — that was open item 5, now closed. The
> suite runs 39 tests across two files and I ran it here: **39 passed**.
>
> **Still not observed.** No browser was reconnected to a restarted orchestrator.
> The reducer is executed by a test; the raster it protects is not.

**Introduced by D-02.** Found 2026-07-31 by both lenses of the review D-02
never had, independently, and confirmed here against the shipped reducer and
component.

`FleetMap.buildPosteriorRaster` short-circuits on
`if (store.revision === map.revision) return store.canvas;`
(`FleetMap.jsx:221`). That is the right idea — rebuilding a 500x500 `ImageData`
on object identity would redo it sixty times per snapshot — but the counter it
compares is **not session-unique**:

- `revision` is `(state.resourceMap?.revision || 0) + 1`
  (`useFleetState.js:285`), whose comment asserts "Monotonic and O(1): the only
  correct trigger for rebuilding the raster";
- `case 'RESET'` returns `{ ...initialState, ... }` (`useFleetState.js:330-335`)
  and `initialState.resourceMap` is `null` (`:30`), so after a reconnect the
  next accepted snapshot is **revision 1 again**, carrying entirely different
  cells;
- `rasterRef` is a `useRef` inside `FleetMap` (`FleetMap.jsx:899-906`) and
  `App.jsx` renders `FleetMap` with no `key` tied to the connection, so the
  component does not remount and `store.revision` survives the RESET.

If exactly one snapshot had been rasterised before the drop, `store.revision`
is 1, the new session's first `map.revision` is 1, and the rebuild is
**skipped**: the canvas keeps blitting the previous backend session's cells
while `ResourceLegend` already reports the new snapshot's `observedCells` and
`totalObservations` (`FleetMap.jsx:1347-1348`). The two disagree on screen with
nothing surfaced. The dimension guard at `:210` cannot catch it — width and
height are unchanged — and it resets `store.revision` to `-1` only when they
differ.

**Bounded, and that is the only mitigating fact**: one publish period, ≤ 2 s at
`resource_map_publish_rate` 0.5 Hz, after which snapshot #2 has revision 2 and
rebuilds. But within that window a restarted orchestrator with an empty map can
be shown as a fully surveyed one.

**Not fixed here**, because the fix is a choice between two designs and this
register's owner does not own either file: keep a monotonic counter outside
`resourceMap` that RESET does not zero (`resourceMapRevision`), or clear
`rasterRef.current.revision = -1` in an effect keyed on the `resourceMap` prop
transitioning to null. Either way the "Monotonic" comment at
`useFleetState.js:283-284` must be corrected — it is the claim that made this
look safe.

**Not observed.** No browser, no rosbridge, no reconnect. This is read off the
reducer and the component; the reducer's RESET behaviour was executed by one
lens against the real reducer, not by this pass.

---

## D-16 — D-01's mark-placement plan does not cover every mark D-01 draws — CLOSED 2026-07-31, FIXED AND MACHINE-CHECKED

> **Status changed 2026-07-31 (evening). All three faces are fixed, each by the
> remedy this entry named rather than by a bigger guess.**
>
> **(a)** The collision window is **measured, not estimated**. `FleetMap.jsx:105`
> and the planner at `:514-525` now derive the reserved slot from the drawn
> string's own width, which is the "measurement hoist" this entry asked for. The
> comment that computed an 86 px label against a 64 px window and drew no
> conclusion is gone.
>
> **(b)** The battery gauge is in the plan: `plan.gaugeRect` is reserved by
> `planRobotLabels` and consumed by `drawRobots` (`:703`, `:1007`).
>
> **(c)** `STATE_ABBREV` is **no longer gated on `labelPlaced`** (`:752`,
> `:954`). The colour-blind-safe channel survives the case it exists for — robots
> clustered at the depot, where the label is exactly what gets dropped.
>
> **Machine-checked**: `selene_dashboard/src/__tests__/fleetMap.marks.test.js`,
> part of the 39-test Jest suite I ran here. **Rendered**: the fleet map was
> confirmed in Chrome (D-01's status block) — but that confirmation did not
> itemise label overlap at a depot cluster, so the specific arithmetic this entry
> contains has still not been checked against pixels.

**Introduced by D-01.** Three findings from the 2026-07-31 review, kept
together because they are one defect wearing three faces: the collision planner
reserves space for the label alone, while D-01 changed what is drawn beside it.

**(a) The collision window is narrower than the label it now guards, and D-01
made the shortfall worse.** `planRobotLabels` collides on
`Math.abs(p.x - x) < sepX` with `sepX = LABEL_SEP_PX_X / scale`
(`FleetMap.jsx:490`), where `p.x` is the **robot's** x — but the label is
centred on the robot (`ctx.fillText(idText, -totalWidth / 2, 0)` after
`ctx.translate(x, labelY)`, `FleetMap.jsx:661-666`). Two centred labels of
width *w* overlap iff their separation is below *w*, so the window must be at
least the widest label. It is not, and **the file's own comment computes the
shortfall without drawing the conclusion**: `FleetMap.jsx:42-49` states that
`'excavator_01 NAV'` is 16 characters at a 0.6 em advance on 9 px glyphs, "so
~86 px for that id", and then sets `LABEL_SEP_PX_X = 64` because "64 px sits
between them". Two such labels 64-86 px apart therefore pass the collision test
and still overlap by up to 22.4 px.

It is a regression, not an inherited flaw: before D-01 the window was 52 px
against an unsuffixed `'excavator_01'` at 64.8 px — a 12.8 px shortfall, 20% of
the label. After D-01 it is 64 px against 86.4 px — 22.4 px, 26%. The window
grew 23% while the text grew 33%. Robust to the font assumption: even at a
0.5 em advance 16 characters is 72 px, still over 64; the window would need an
implausible ≤ 0.444 em to be correct. And `FleetMap.jsx:679-684` establishes
that at the default framing (~4.3 px/m) every robot parked at the 10 m depot
falls inside one window, which is exactly where two excavator labels sit.

The honest fix is not a bigger guess. `drawRobots` already calls
`ctx.measureText` on the drawn strings (`:661-662`); hoisting that measurement
into `planRobotLabels` would make the reserved slot the drawn width instead of
an estimate the comment already admits is one.

**(b) The battery gauge was freed from the label but never added to the plan.**
`planRobotLabels` records only labels — `placed.push({ x, y: labelY })`
(`:514`) — while `drawRobots` now draws a 20x3 px gauge for every robot with a
numeric `battery_level`, unconditionally, anchored to the icon (`:685-708`).
Two robots within 20 px in x and 3 px in y draw superimposed gauges, and a
robot 10 px below a neighbour puts its gauge inside the neighbour's label band.
Two overlaid 20x3 px bars are indistinguishable, so an operator can read one
robot's charge as another's. **The trade is still net-positive** — D-01 fixed a
gauge that vanished entirely — but it created a class of overlap that did not
exist when the gauge was gated on the label.

**(c) The colour-blind-safe state channel is gated on the label, which is the
coupling D-01 removed from the gauge.** The three-character `STATE_ABBREV` is
drawn inside `if (labelPlaced)` (`FleetMap.jsx:639-668`), and
`planRobotLabels` returns `null` for any non-selected robot still colliding
after `LABEL_MAX_ATTEMPTS` nudges (`:510-513`). `colors.js:20-26` calls
`STATE_ABBREV` "the colour-blind-safe channel of the state encoding", and
D-01's own comment at `:678-684` computes that robots clustered at the depot
lose their labels. So the channel that exists for an operator who cannot rely
on the dot's hue disappears **precisely when robots cluster** — leaving state
encoded by hue alone, for the reader who cannot use hue. D-01 decoupled the
gauge from `labelPlaced` for exactly this reason and did not decouple the
abbreviation.

**Nothing here was rendered**, and it cannot be from this box. Every figure is
arithmetic over the transform chain and the constants — the same class of
argument as D-01 itself, which is why Verification limits item 5 still stands.
Not fixed: (a) needs a measurement hoist, (b) and (c) need the planner to
reserve every mark rather than the droppable one, and the whole family is a
rendering judgement made where nothing renders.

---

## D-17 — the concentration legend teaches a colour no map cell can have — CLOSED 2026-07-31, DEMONSTRATED IN A BROWSER

> **Status changed 2026-07-31 (evening), and this entry got the outcome it asked
> for rather than the minimum one.** It proposed "a small 2-D swatch —
> concentration on x, certainty on y, evaluated through `posteriorCellRGBA`" and
> called that a visual design decision the box it was written on could not make.
> That is what shipped: `ResourceLegend.jsx` now paints every pixel of a 56 px
> swatch through `posteriorCellRGBAAtCertainty` (`:161`) — the same function
> `posteriorCellRGBA` reduces to once it has turned a variance into a certainty.
> **The legend is now literally the function the raster applies**, so a map cell
> can be inverted against it.
>
> **And it was seen.** The operator confirmed the swatch rendering in Chrome.
> That observation also produced the only defect in this entire family that no
> arithmetic in this register predicted: the legend it replaced had **three
> labels collapsing into each other on screen**, reading
> `unsure5 wt% shownconfident`. Nothing static caught that. It is the clearest
> argument in this document for why "implemented" and "demonstrated" are
> different words.
>
> **The related note stands**: at `ALPHA_MIN` 0.05 the low-confidence end
> composites to about 1.6% of full scale over the legend's own backdrop. It costs
> nothing on the map, because D-02 correction 1 established that certainty 0 is
> unreachable with the shipped scout, and it is now on an axis a reader can see
> the rest of.

Found 2026-07-31 by the rendering lens; **confirmed by execution here** through
the shipped `resource_map_viz`, the Python half of the pair.

`ResourceLegend` builds its primary bar from `iceConcentrationColor(value, 1.0)`
(`ResourceLegend.jsx:55`) — the pure ramp at certainty 1.0. The map does not
draw the pure ramp: `posteriorCellRGBA` composes hue and certainty
multiplicatively, lerping toward `LOW_CONFIDENCE_GRAY` as certainty falls.
Measured on this box against the real `ResourceMap`:

    a cell observed once at 5.0 wt%, footprint centre
      -> posterior mean 4.9875, variance 0.2494, certainty 0.6508
      -> renders rgb(31, 199, 204)
    the pure ramp near there
      4.5 wt% -> (0, 204, 255)   5.0 -> (0, 255, 255)   5.5 -> (51, 255, 204)

`(31, 199, 204)` is on **no** point of the bar — r is non-zero while b is not
255 — so an operator cannot invert a map cell against the legend. Reaching the
bar's colours needs certainty 1.0, i.e. variance ≤ `VARIANCE_FLOOR` 0.01, which
I measured takes **25 readings** at a footprint centre with the shipped
0.5 wt% scout. `orchestrator_params.yaml:101` already records that survey
`min_spacing` (8.0) exceeds `ResourceMap` `footprint_radius` (5.0), so
footprints do not overlap and most observed cells get exactly one reading.

This is the same species as D-02 correction 1 and was found by the same pass,
but it is a distinct defect and survives that correction's repair: correction 1
documented the unreachable *certainty* axis and pinned it, and the certainty bar
now carries that note in code (`ResourceLegend.jsx:94-105`). The
**concentration** bar was not touched, and it only partly helps that the
certainty bar exists — it is drawn at a single fixed
`CERTAINTY_REFERENCE_WT = 5.0` (`:16`).

**Not fixed.** The right answer is probably a small 2-D swatch — concentration
on x, certainty on y, evaluated through `posteriorCellRGBA` over an opaque
backdrop — so the legend is literally the function the raster applies. That is a
visual design decision, and this box cannot see the result of one. The
minimum honest alternative is a line on the legend saying cells are desaturated
toward gray by certainty and the bar shows the fully-confident limit.

**Related, and recorded rather than numbered**: at `ALPHA_MIN` 0.05 the
`LOW_CONFIDENCE_GRAY` swatch composites to a delta of 4.0 / 4.1 / 4.2 per
channel over the legend's own `#0a0e1a` backdrop (executed here) — about 1.6%
of full scale, at or below a just-noticeable difference on a dark surface — so
the left end of the certainty bar is a black smear. The weakest **reachable**
alpha, 0.4506, gives 36.0 / 36.9 / 37.9. Since D-02 correction 1 established
that certainty 0 is unreachable on the shipped fleet, this costs nothing on the
map itself and only makes the legend's unreachable half doubly uninformative.

---

## D-18 — the "verbatim pair" diverges on a non-finite cell mean — CLOSED 2026-07-31, FIXED SYMMETRICALLY

> **Status changed 2026-07-31 (evening).** The fix is the symmetric one this
> entry specified, and it went slightly further in a defensible direction.
> `resource_map_viz.concentration_to_rgb` **clamps a non-finite mean to 0.0**
> instead of raising out of `_js_round` → `math.floor` (`:134-152`), and
> `variance_to_certainty` returns 0.0 on a non-finite variance or prior
> (`:211-217`). Beyond mirroring the JS `|| 0`, a non-finite **mean** now forces
> certainty 0 as well (`:255`, `:276`), so such a cell renders as pure
> `LOW_CONFIDENCE_GRAY` rather than as a confident dark blue — the two channels
> cannot come from two different certainties. The overlay timer can no longer be
> stopped by one poisoned cell.
>
> **Still latent, and still not upstream.** No path is known that produces a
> `NaN` reading, and `orchestrator_node._on_map_update` still passes
> `msg.ice_concentration` through without a finiteness check, unlike
> `agent_node._publish_map_update`, which validates and drops a non-finite
> `sensor_uncertainty`. The renderer is now safe; the ingest is not guarded.
> That remainder is open item 19.

Found 2026-07-31 by the rendering lens as its one speculative finding;
**the divergence is confirmed by execution here on both sides**, the
reachability is not.

D-08 makes the two renderers a "verbatim pair", and D-02 correction 3 now
machine-checks that pair over the finite domain. Neither covers a non-finite
mean, and there the two halves do different things:

    node, colors.js (export stripped, run in a vm context):
      posteriorCellRGBA(NaN, 1, 100) -> [55, 76, 130, 0.45]
    python, resource_map_viz:
      certainty_to_rgb(nan, 1.0, 100.0)
        -> ValueError: cannot convert float NaN to integer

The JS silently renders the `ICE_FLOOR_RGB` end of the ramp, because
`iceConcentrationRGB`'s `Math.max(value || 0, 0)` turns `NaN` into 0 — `NaN` is
falsy. The Python raises out of `_js_round` -> `math.floor`, and
`marker_colours` is called from `_publish_resource_map`
(`orchestrator_node.py:1414`) **inside the `resource_map_publish_rate` timer
callback**, so one poisoned cell stops the RViz2 overlay publishing rather than
colouring it. So the same map would show a plausible dark-blue patch on the
dashboard and nothing at all in RViz2 — a divergence in exactly the
side-by-side comparison `docs/PRD.md:1504` asks for.

**Latency, and why it is recorded rather than dismissed.** A `NaN` mean is
reachable in principle: `ResourceMap.update:92-96` computes
`posterior_mean = posterior_variance * (prior_precision*mean + obs_precision*reading)`,
so a `NaN` `ResourceMapUpdate.ice_concentration` propagates into the grid
permanently, and `orchestrator_node._on_map_update` (`:1453-1458`) passes
`msg.ice_concentration` straight through with **no finiteness check** — unlike
`sensor_uncertainty`, which `agent_node._publish_map_update`
(`agent_node.py:997-1005`) does validate and drop. The variance stays finite,
so `useFleetState`'s geometry guard does not reject the snapshot and per-cell
means are never validated. **No path is known that produces a `NaN` reading**,
and none could be exercised from here, so this is latent, not live.

**Not fixed.** The fix is symmetric and small — clamp a non-finite mean to 0.0
in `resource_map_viz.concentration_to_rgb`, mirroring the JS `|| 0`, clamp a
non-finite variance to `prior_variance`, and add the non-finite cases to
`test_dashboard_colour_parity.py` so the pair is pinned there rather than only
over the finite ramp. It is left open because the better fix may be upstream
(reject a non-finite reading in `_on_map_update`, as the agent already does for
sigma) and that is the orchestrator owner's call.

---

## D-19 — `recharge_threshold` was declared, configured, and read by nobody — CLOSED 2026-07-31, DEMONSTRATED

**The fourth appearance of this repository's signature failure, and the most
expensive one.** `AdaptiveSurveyPlanner` had green tests and no call sites;
`MaterialInventory`'s writers had no production callers; `resource_map_publish_rate`
was declared and never read for two phases. This is the same shape and it cost
the mission.

**Was**: the **orchestrator** declared `recharge_threshold`, `orchestrator_params.yaml`
set it, and nothing anywhere read it. It sat on `test_no_orphan_parameters.py`'s
allow-list, annotated "the agent decides recharge locally" — which was a claim
about a decision that did not exist. The agent ended **every** task with an
unconditional `_start_recharge()`, so a robot that finished a survey at 90%
charge drove to the pad and charged to 90%.

**What that did, and why it was never noticed.** Nothing errored. Every robot
looked healthy, every task completed, and the fleet spent its life commuting.
Waypoint-to-waypoint took **8 minutes**. A survey took long enough that
`SelectSite` — which resolves only when *every* survey task completes — never
resolved, so no excavate was ever decomposed, so `MaterialInventory` was never
written. **This is why the ISRU ledger read 0.0 from Phase 4 onward.** D-06 spent
two days finding seven breaks in the material chain; this was the reason the
chain was never reached.

**Now**: the parameter lives where the decision is made. `agent_node.py:141`
declares it, `:163-166` validates it through `validated_recharge_threshold`,
`agent.launch.py:110` passes 0.30, and `energy_manager` / `recharge_policy`
consume it. A task now ends with a decision that has three inputs — the floor,
the charge, and whether there is margin to get home — and logs which one it used.
The allow-list is down to one name (`fleet_state_publish_rate`) and the test file
records why the other left.

**MEASURED live (2026-07-31):**

    Task done at 83.7% battery; staying in the field (floor 30%, return margin OK)

    waypoint -> waypoint       8 min  ->  52 s
    observations               316 in 21 min  ->  785 in 8 min

---

## D-20 — the auction re-announced one task 261 times — CLOSED 2026-07-31, DEMONSTRATED

**Was**: a task nobody could bid on was re-announced every auction tick forever.
One task was measured re-announced **261 times**. There is one auction slot, so
an unbiddable task starves every biddable one behind it, indefinitely, while the
log fills with identical lines that look like activity.

**Now**: `TaskEntry` carries `failed_auctions` and `auction_backoff_until`
(`task_queue.py:87-106`); `get_next_ready` skips a task inside its backoff window
(`:285-307`); after five consecutive no-bid auctions the task is **abandoned**
(`auction_backoff_until = math.inf`, `:364`) and says so; and a robot arriving in
IDLE clears every backoff (`:381`), because a fleet that just gained capacity is
new evidence. A requeued task never inherits a backoff (`:190-193`, `:237-238`).

**MEASURED live (2026-07-31, ten robots).** Two tasks hit the give-up state —
`no bids in 5 consecutive auction(s); GIVING UP … will not be announced again
until a robot arrives in IDLE` — and were then re-armed by
`A robot became IDLE; 6 backed-off task(s) are auctionable again`. **Both
subsequently completed.** Ten distinct survey tasks were announced and ten
`Prospect complete` lines followed. So the mechanism was exercised in both
directions: it held tasks back, and it let them go.

---

## D-21 — a dead simulator degraded the fleet in silence — CLOSED 2026-07-31, DEMONSTRATED (see also D-30)

**Was**: when Gazebo died the whole fleet stopped moving and nothing said so.
Odometry froze, agents kept reporting states, tasks kept being auctioned, and an
operator watching the dashboard saw a fleet that was simply slow. This was the
observable half of D-26: `ros2 launch` survived every ODE abort.

**Now**: `_check_simulation_stall` (`orchestrator_node.py:1743`) raises a
CRITICAL `FleetAlert` when no robot in the fleet has moved for a window while at
least one of them should be driving, and clears it when motion resumes.

**MEASURED live**: it fired and recovered during the third crash run —
`Fleet motion resumed; the odometry freeze has cleared.`

**And it is badly calibrated. That is D-30**, opened deliberately rather than
folded in here: across the two ten-robot runs it produced **four false positives
and zero true positives**, and in one of them it described a single wedged scout
as a fleet-wide freeze. The mechanism works; the threshold and the message do
not. **A per-robot instrument found the same event 201.5 s earlier — D-25.**

---

## D-22 — the HTN planner sent the hauler to the excavator's exact coordinate — CLOSED 2026-07-31, DEMONSTRATED

**Was**: `HTNPlanner` gave a haul task the **identical** target coordinate as the
excavate it depended on, so the hauler navigated into the parked excavator.

**Now**: two independent numbers, on purpose. `HTNPlanner.HAUL_PICKUP_OFFSET_M`
(1.2 m) offsets the pickup point from the site **toward the depot**, and
`HaulSkill.PICKUP_STANDOFF_M = 4.5` (`haul.py:146`) makes arrival a distance test
rather than a goal test (`haul.py:375`). `test_haul_pickup_standoff.py`
re-derives the standoff from the planner's own offset so the two cannot drift
apart silently.

**The open question in the brief is answered: the log rounds, the offset is
applied.** `orchestrator_node.py:1863` formats auction targets with `:.0f`. For
the site the 2026-07-31 run used:

    site                                    (-80.5000, -144.5000)
    haul pickup = site + 1.2 m toward depot (-79.8314, -143.5035)   separation 1.2000 m
    excavate target printed at .0f          (-80, -144)
    haul pickup   printed at .0f            (-80, -144)   -> IDENTICAL

Both print the same string because Python's round-half-to-even sends −80.5 to
−80 and −144.5 to −144. The two targets are 1.2 m apart and always were.
**Caveat**: this proves the mechanism for that run's site. The crash-run site
that raised the question, (−114, −136), was never re-derived, and a site on
integer coordinates would print differently.

**MEASURED physically, for the first time**, on the ten-robot run: at
`phase=loading`, `hauler_02` was at (−82.3949, −143.5020) and `excavator_01` at
(−80.0732, −143.6970). The run report states 2.303 m; **recomputing from the two
coordinates it quotes gives 2.330 m**, and the discrepancy is recorded rather
than smoothed. Either way it is comfortably above the 1.1694 m at which two
footprints touch, and well below the 4.5 m commanded — the standoff is a floor
the vehicle stops near, not a radius it holds.

**The number that makes this trustworthy is D-24's, not this entry's.** A
standoff enforced in `odom_world` can only bound physical separation as well as
`odom_world` bounds physical position. On the midday run — before the pose
source moved — the same measurement gave "4.915 m apart" between two robots
whose beliefs were 13.8 m and 241.6 m from truth, which was worth nothing.
An earlier, genuinely physical approach was **2.4283 m** at the same phase.
Any collision-avoidance distance expressed in a dead-reckoned frame has this
property, and it is the reason D-24 had to land before this entry could be
believed.

---

## D-23 — the PSR crater is a one-way trip, and it made every haul physically impossible — CLOSED 2026-07-31 BY RELOCATION, DEMONSTRATED

**This is a root cause. It is not the ODE abort's root cause, and it must not be
read as one.**

**Was**: every ice deposit in `ice_deposits.yaml` sits inside the PSR crater
(r = 20.6–22.4 m from its centre) and **both** depot positions this project has
ever configured sat outside it. So every haul had to climb out.

**MEASURED from the shipped deterministic generator (seed 42)**: the crater rim
is **34.3–39.2°** of uphill over a 3 m baseline on all 24 azimuths at 15°
spacing; over 72 azimuths the gentlest exit is **34.09°**. Against a declared
`max_traversable_slope_deg` of 15.0. And it is not fixable by reshaping the
profile — 15 m of relief over a 45 m annulus averages 18.4° whatever shape you
give it.

**What it looked like instead of an error.** On 2026-07-31 a hauler tried. It
climbed to r = 57.5 m, pitched over to **−35°** and pinned. For **320.7 s** its
wheels turned at the commanded 0.395 m/s while its body moved **6.6 cm**. Its
dead-reckoned pose sailed on to within 0.4 m of the configured depot, `HaulSkill`
declared arrival, and it unloaded 19 kg **241.577 m from where it actually was**.
The ledger recorded a perfect delivery. Nothing errored. See D-06's status block
for why that run must not be quoted as a demonstration.

**Now**: the depot is on the crater floor at **(−100, −150)**, central to all
four deposits (20.3–22.4 m from each) — which is also a defensible ISRU
architecture: process the regolith where it is. Changed in four places that must
agree: `orchestrator_params.yaml:174-175` (the one that actually reaches a
hauler), `world_params.yaml`, the `depot` marker in `lunar_psr.sdf` at a
**surveyed** z of −13.86 (measured collision surface −13.914932 plus half the
disc's 0.1 m thickness, rounded up so it clears rather than grazes), and
`selene_dashboard/src/utils/worldConfig.js`. A `recharge_pad` marker now occupies
the old (−30, −100) at its own surveyed z of 0.94.

**MEASURED live**: five deliveries on the ten-robot run, and at the moment of
one of them Gazebo ground truth put `hauler_02` at (−98.669, −149.228) against
the marker at (−100.000, −150.000, −13.860) — **1.539 m**.

**Pinned so it cannot rot**: `selene_sim/test/test_mission_traversability.py`
(6 tests) recomputes the rim slopes from the generator on every run, asserts the
configured depot and the SDF marker are the same place, asserts every deposit
reaches the depot under `max_traversable_slope_deg`, and **pins the one-way-trip
defect itself** so regenerating the terrain cannot silently change it.

**NOT FIXED, and this is a relocation rather than a repair.** The crater wall is
still 34°. The real fix is a graded ramp or a shallower crater, and it is
deferred. **The return leg is still impossible** — the recharge pad is outside
the crater, behind the same wall. That is **D-32**. And the planner still does
not read a slope limit at all: **D-28**.

---

## D-24 — dead reckoning was the mission's only position estimate, and its error is unbounded — CLOSED 2026-07-31, DEMONSTRATED

**Was**: after D-33 put the spawn SE(2) back, `/<rid>/odom_world` was still wheel
odometry — correct in frame, unbounded in error. Nothing in the system had any
other opinion about where a robot was.

**MEASURED live, twice, and the numbers are the argument:**

    run A   scout_04    115.8 m of divergence at t=256.5 s
    run B   hauler_02   166.2 m of divergence at t=1356 s
    midday  hauler_01   241.577 m at the moment it reported a successful delivery

**Now**: `world_odometry_node` gains a `pose_source` parameter and becomes the
one place the pose is *checked* as well as converted.

- `localisation` (**default**) publishes the simulator's true world pose — the
  simulator standing in for a localisation stack, which is what this node's
  docstring always claimed it was.
- `dead_reckoning` reproduces the previous behaviour **exactly**, so the defect
  stays reproducible rather than being deleted from history.
- **The divergence is measured and alerted in both modes.** Choosing
  `dead_reckoning` does not hide the drift, it narrates it. On the run above the
  suppression is stated in the log:
  `dead reckoning has drifted 115.8 m … That error is currently suppressed:
  pose_source is localisation.`
- **Twist still comes from the encoders in both modes**, deliberately. That is
  what leaves the slip signal intact for D-25 to read.
- If truth never arrives it publishes dead reckoning **and** raises an ERROR plus
  a CRITICAL `FleetAlert` naming the missing topic. `truth_grace_sec` suppresses
  that only before the first truth sample ever arrives.

Truth source: `PosePublisher` in all three `models/*/model.sdf`, bridged
`/model/<rid>/pose` → `/<rid>/pose_truth` in `simulation.launch.py:254`,
`spawn_robot.launch.py:60`, `scripts/start.sh` and `scripts/run_demo.sh`.
`PosePublisher` was chosen over `OdometryPublisher` **by measurement**: both
report the true world pose on gz-sim 8, but `OdometryPublisher`'s `<odom_topic>`
is a literal with no model-name substitution, so two scouts spawned from one
model file would have collided on one topic.

**MEASURED, two independent ways:**

    worst |odom_world - truth|   run A 0.0296 m      run B 0.0816 m
    path integral (run B)        odom_world 753.8 m  truth 752.3 m   (0.2% over 753 m)

The instantaneous figure is dominated by sample-time skew between two
independently sampled streams at 0.4 m/s, not by arithmetic.

**NOT demonstrated**: `pose_source: dead_reckoning` has never been run. The
escape hatch is unit-tested only.

**What this is honestly worth.** It is a simulator handing the mission layer a
pose the simulator already knows. It removes localisation error from every other
result in this register — which is exactly what was needed to make D-22, D-06 and
D-23 mean anything — and it builds no localisation stack. On hardware this node
is a stub with a real estimator behind it, and every error bar in this document
comes back.

---

## D-25 — nothing could see a robot whose wheels turn while its body does not — CLOSED 2026-07-31, DEMONSTRATED ON A NATURAL EVENT

**Was**: `_check_simulation_stall` requires the **whole** fleet frozen, and its
own docstring delegates the single-robot case to "that robot's own ERROR". A
robot pinned at 100% slip never goes to ERROR: it reports `WORKING`, its
odometry advances at the commanded rate, and it eventually reports success.
**No odometry-based check can catch this**, because the odometry is not frozen —
it is wrong. Only a comparison against an independent position source can.

**Now**: `selene_sim/selene_sim/localisation.py` (new, ROS-free, 264 lines)
computes two separable numbers — instantaneous `error_m` (belief versus truth)
and windowed `slip_fraction` (wheel path versus body path). They are separable
because **path length is invariant under any rigid transform**: a frame error
moves `error_m` and leaves `slip_fraction` at zero. Samples are decimated to 5 Hz
before entering the window, because integrating `|dp|` at full rate on a body
resting on a heightmap manufactures ~0.17 m/s of phantom path out of contact
jitter.

**MEASURED live on an event nobody staged:**

    [world_odom_scout_04]: scout_04: WHEELS TURNING, BODY NOT MOVING.
      9.9 m of wheel travel over 20s, 2.58 m covered (74% slip).        t=206.5
    [orchestrator_node]: FLEET-WIDE ODOMETRY FREEZE: none of 10 robot(s)
      has moved in 20s and 1 of them should be driving (scout_04).      t=408.0

**The new instrument found it 201.5 seconds before the existing one, and the
existing one then described it wrongly** — nine robots were fine. That is D-30.

**Sim-only instrument.** On hardware the same comparison is localisation against
encoders, which is a real and standard check; here it is the simulator marking
its own homework, and it is only legitimate because the thing being checked
(wheel odometry) is genuinely independent of the thing checking it (physics
pose).

---

## D-26 — `ros2 launch` outlived the simulator — CLOSED 2026-07-31, DEMONSTRATED

**Was**: Gazebo aborted three times and `ros2 launch` survived every one. The
fleet then ran on with no physics: odometry frozen, agents cycling states, tasks
being auctioned into a world that had stopped. **The answer already existed
upstream**: `ros_gz_sim`'s `gz_sim.launch.py` takes an `on_exit_shutdown`
argument and defaults it to `'false'`
(`/opt/ros/jazzy/share/ros_gz_sim/launch/gz_sim.launch.py:135-146`). Nobody had
passed it.

**Now**: `simulation.launch.py:202` passes `'on_exit_shutdown': 'true'`, and a
`_diagnose_simulator_exit` handler registered on `OnProcessExit` (`:49`,
`:373-374`) prints a banner naming the ODE signature **and stating that its cause
is unknown** — because a shutdown on its own produces a wall of "process has
died" with no statement of which death mattered.

**A second defect had to be fixed for the first one to be legible.**
`rclpy.shutdown()` is now guarded by `if rclpy.ok()` in all six `selene_sim`
nodes. On a launch-level shutdown the context is already down, the unguarded call
raises out of `finally`, and each node exits 1 — so a **clean** teardown logged
**eight** `process has died [exit code 1]` ERRORs and buried the diagnosis. A
clean teardown must not look like eight crashes, least of all on the one path
whose entire purpose is to be readable after a crash.

**MEASURED**, by killing the simulator deliberately:

    === SIMULATOR-DEATH TEST: killing gz with SIGABRT ===
    gz pid 1058
    RESULT: ros2 launch EXITED with the simulator

    [ERROR] [gazebo-1]: process has died [pid 1058, exit code -6, ...]
    [INFO] [launch]: process[gazebo-1] was required: shutting down launched system
    THE SIMULATOR EXITED (process gazebo-1, return code -6). Shutting the whole
    launch down.

**This is survivability, not a fix.** It makes the next ODE abort loud instead of
silent. It does nothing about why the abort happens — D-37.

---

## D-27 — the FR-ISRU-2 overdraw alarm fired on every healthy haul — CLOSED 2026-07-31, DEMONSTRATED

**Was**: the load-overdraw check compared float32-derived masses against a
hard-coded **1e-6 kg** tolerance. One float32 ulp at 19 kg is **1.9e-6 kg**, so
the tolerance was **finer than the representation of the quantity it compared**.
The 2026-07-31 run's residue of 1.0109e-4 kg — 53 ulps of cross-instrument
conversion error — tripped it, and the WARNING it raised printed
`reported 19.01 kg but only 19.01 kg had been extracted there; 0.00 kg is
unaccounted`. **The alarm fired below its own printing precision**, on a haul
that was completely healthy. An alarm that cries wolf on every success is worse
than no alarm: it trains the reader to skip it, and `MissionProgress.msg` says
in its own words that a non-zero `unaccounted_quantity` "is precisely what
FR-ISRU-2's acceptance says cannot happen".

**Now**: `material_overdraw_tolerance_kg` (`orchestrator_params.yaml:205`,
declared `orchestrator_node.py:1096`, read `:1155`, used `:845`) defaults to
**0.001 kg** — 500× smaller than `material_residual_tolerance_kg`, far above
float32 resolution. `MaterialInventory.record_load` takes a `tolerance_kg`
argument whose **default is 0.0**, i.e. the strict old behaviour, so no other
caller changes. Within tolerance the overdraw is credited to the load *and* to
the site's extracted total, so the conservation identity still closes; only the
genuine excess is banked in `_unaccounted_kg`.

**MEASURED live**: the ten-robot run applied 15 material events across 5 hauls
with `unaccounted_quantity` **exactly 0.0** and **zero** overdraw WARNINGs.

**What is fixed and what is only silenced — say it plainly.** The tolerance stops
a healthy haul raising an alarm. It does **not** explain the 1.0109e-4 kg. Two
independent reviews computed that figure at 53–85 float32 ulps depending on which
instrument's scale you use — one and a half to two orders of magnitude too large
for either instrument's quantisation. The hopper and the load cell disagreed by
more than their representation can account for and **nobody knows why**. That is
open item 20, and it is the check this closure did not perform.

---

## D-28 — `navigation.max_traversable_slope_deg` has had zero readers since Phase 2 — CLOSED 2026-08-01, MEASURED AND DEMONSTRATED

> **CLOSED 2026-08-01 at `9c1a4d7`.** The parameter now has production readers
> (`selene_agent/selene_agent/agent_node.py:219`, and
> `selene_agent/selene_agent/navigator.py` in six places), it carries a
> **measured** value rather than a guessed one, and the rule it enforces is not
> the rule its name suggests. Three things had to be true together and the third
> is the interesting one.
>
> **1. THE CAMPAIGN.** `scripts/measure_slope_capability.sh` ran **54 trials** on
> ROS 2 Jazzy / gz-sim on WSL2 — 3 robot types × 9 grades × 2 directions — driving
> each vehicle from rest straight up or straight down the local fall line and
> judging **world displacement against the COMMAND**, never against odometry (the
> D-25 lesson: a buried wheel satisfies odometry perfectly). Pass criterion: 70%
> of commanded displacement at under 25% slip. Artefacts are committed —
> `docs/slope_capability_2026-08-01.json`, `docs/slope_campaign_2026-08-01.log`
> and `docs/slope_capability_2026-08-01.PROVENANCE.md`.
>
>     scout      ascent 35    descent 25
>     excavator  ascent 20    descent 25    (ascent NON-MONOTONIC)
>     hauler     ascent 20    descent 25    (ascent NON-MONOTONIC)
>     counts: 24 pass, 15 fail, 4 buried, 2 tumbled, 9 no_site
>
> Worst ascent 20, worst descent 25, so **a mission needing round trips is
> governed by 20°**, and that is the number in `nav_params.yaml:61` and
> `world_params.yaml:100`. **The non-monotonicity is recorded, not smoothed**:
> the excavator and the hauler both FAILED at 10° and 15° and then PASSED at 20°
> (`verdict.per_robot_direction.*.monotonic: false` in the artefact). A capability
> that is not monotonic in grade means the trials are not measuring grade alone —
> see D-41, which explains four of those apparent failures and cannot explain all
> of them.
>
> **2. THE PROVENANCE FILE, and why it exists rather than an edit.** The
> artefact's own `git_commit` and `workspace_source_commit` both read
> **`ff80ed1`, and both are WRONG** — the campaign ran against the files of
> `7727ba8`. The WSL2 workspace was a clone at `ff80ed1` whose *files* were then
> rsynced from the Windows tree, and rsync excludes `.git`, so git answered
> honestly about a repository nobody had moved. **The as-run JSON was NOT
> edited.** Its SHA-256 fields are the chain that makes it evidence, and editing
> it would break that chain; the correction is recorded additively in
> `docs/slope_capability_2026-08-01.PROVENANCE.md`. **The measurement stands
> because the hashes stand**: world, relief heightmap, collision heightmap and
> terrain datum were all verified against the committed repository and all match —
> including the **post-D-39** `lunar_psr.sdf`, so the campaign did not run on a
> pre-fix world. One further discrepancy is recorded and unresolved in that same
> file: `gz sim --versions` answered **8.10.0** while `gz sim --version` answered
> **8.11.0** on the same host on the same day, and which one describes the physics
> that produced these trials has not been established.
>
> **3. THE CONTRADICTION, AND ITS RESOLUTION, WHICH IS THE POINT.** 20° is far
> below the crater rim, and the mission is inside the crater. The rim was
> re-measured as a **minimax barrier** — a binary search over connected-component
> labelling of the planning lattice, so a winding route *would* have been found if
> one existed — and it is **34.02°** (`navigator.py:31`). Two other numbers for
> the same rim are in the tree and are not the same measurement, and all three are
> kept distinct on purpose: the campaign artefact's 2-D native gradient magnitude
> minimised over 72 azimuths is **34.0349°**, and the radial 1-D derivative that
> `selene_sim/test/test_mission_traversability.py` uses over the same azimuths is
> **34.09°** (`terrain_slope.py:68` pins the pair at 0.5° agreement). There is no
> gentler way round on any of the three. **Yet on 2026-07-31 the fleet delivered
> 94.85 kg into that crater** (D-06), hauler ground truth 1.539 m from the depot
> marker.
>
> Both facts are true because they are about different quantities. **A vehicle
> climbs along its own heading, not along the terrain's fall line.** A path
> crossing ground of slope `S` at a heading `theta` off the fall line climbs at
> `atan(tan(S) * cos(theta))` along its direction of travel; at S = 34.02° a path
> **≥ 57.4° off the fall line climbs at ≤ 20°, for a 1.85× length penalty**. That
> is a switchback. **The campaign measured `theta = 0` by construction** — the
> steepest heading that ground offers.
>
> So the limit is enforced **PER STEP**, against the grade along each expanded
> edge, and **NOT per cell**, which is what the parameter's name invites. Measured
> over the 500 × 500 / 1.0 m lattice, 8-connected, on the **collision** heightmap
> (the surface the robot contacts), and independently re-derived by the
> implementer:
>
>     per-step   10 deg -> depot UNREACHABLE (237,727 of 250,000 cells)
>                15 deg -> reachable          (248,606)
>                20 deg -> reachable          (250,000)
>     per-cell   10 / 15 / 20 / 25 deg -> UNREACHABLE;  34 deg -> reachable
>
> **The per-cell reading would have refused the entire mission at every limit the
> campaign can support.** That is not a tuning detail; it is the difference
> between a fleet and a parked fleet.
>
> **DEMONSTRATED LIVE on the 2026-08-01 gate run.** Every agent logs the audit at
> startup — this is `scout_02`'s, verbatim from `/tmp/selene_unified_launch.log`
> lines 97–100:
>
>     [TERRAIN] slope limit 20.0 deg, enforced PER STEP against the 'collision'
>               heightmap (navigation.max_traversable_slope_deg).
>     [TERRAIN] 250000 cells at 1.00 m: 8729 (3.5%) exceed the limit by the
>               per-CELL gradient reading, which is NOT the rule in force, and
>               208 are occupied by mapped obstacles.
>     [TERRAIN] under the per-STEP rule the navigable set is 1 connected
>               component(s); this robot starts at (-45.2, -88.6) in one of
>               249792 mutually reachable cells.
>     [TERRAIN] depot (-100.0, -150.0): REACHABLE | recharge_pad (-30.0, -100.0):
>               REACHABLE
>
> The audit is **a report and never a gate** — it cannot refuse to start an agent,
> deliberately (`navigator.py`, `ReachabilityAudit`), because the shipped terrain
> has been through three different beliefs about what is climbable in two days and
> aborting a fleet on arithmetic over a heightmap would be the worse failure. Its
> purpose is that the first time a hauler cannot get home, the reason is already
> in the log from before it set off.
>
> **A guard the existing one could not provide.**
> `test_no_orphan_parameters.py` AST-walks the **orchestrator's**
> `declare_parameter` calls, so a YAML key no node declares at all is invisible to
> it — the parameter is not orphaned, it is absent, which is exactly D-28's shape.
> `selene_agent/test/test_nav_params_are_read.py` sees that shape. **MEASURED:
> `nav_params.yaml` had 26 leaf keys of which 17 had no reader; it now has 22 keys
> with 5 unread**, all `obstacle_avoidance.*`, allow-listed with a written reason
> (`ObstacleAvoidance` itself has no production caller — the same pattern again,
> one frame smaller). Re-verified on this pass: 22 leaf keys, and the allow-list
> holds exactly those five.
>
> **Two defects found while building this, neither predicted.**
> (a) `_simplify_path` silently discarded the cost preference: A* correctly
> detoured off 19° ground and the simplifier straightened it back on, because
> line-of-sight has no objection to ground that is drivable and merely expensive.
> Shortcuts are now priced with the search's own cost function.
> (b) `scripts/run_demo.sh` printed `Recharge station: (40, 40)`, which was never
> true anywhere — it is `RechargeSkill`'s stale constructor default.
> The goal guard also refuses a target **on** over-limit ground, which caught
> `nav_params.yaml`'s own first prospect waypoint at (−60, −120), **36.80°**.
>
> **WHAT IS NOT DEMONSTRATED, and it is not small.**
> * **Side-slope rollover — usually the binding limit on a real vehicle, and
>   exactly the mode a switchback route spends its time in — WAS NOT MEASURED,
>   and nothing in SELENE bounds it.** The rule closed here *licenses* the
>   manoeuvre whose failure mode nobody has characterised. This is stated in the
>   config comment beside the constant as well as here.
> * **One trial per (robot, grade, direction).** No repeats, no run-to-run spread,
>   no confidence interval. 54 trials is 54 samples of 54 different conditions.
> * **No vehicle has driven a switchback.** The route lengths quoted under D-32
>   are *executed plans over the committed heightmap*, not journeys.
> * The spawned model was **sensor-stripped** — see D-41 — so the vehicle measured
>   is not byte-identical to the vehicle the mission flies.
> * Sites were chosen on the 513-sample **visual** heightmap while the wheels
>   contact the 129-sample **collision** decimation, which can only be smoother;
>   the grade actually felt is at most the grade reported.

The entry as first written follows, unchanged — its present tense describes the
state before the status block above, and it is kept because it is the record of
how the defect was found.

**The fifth instance of the "wired but never called" pattern**, and the one that
made D-23 possible.

`selene_agent/config/nav_params.yaml:21` has declared
`max_traversable_slope_deg: 15.0` since Phase 2. Verified on this pass: the only
thing in the repository that reads it is
`selene_sim/test/test_mission_traversability.py`, added on 2026-07-31 as part of
D-23's fix. **The planner does not read it.** `world_params.yaml:81` now also
declares it so the test has a world-scoped authority to check against, which
raises the count of declarers to two and the count of production readers to zero.

**Why the existing guard could not catch it.**
`test_no_orphan_parameters.py` parses the **orchestrator's** `declare_parameter`
calls and fails on any that nothing reads. A limit that lives in a YAML file no
node declares at all is invisible to it — the parameter is not orphaned, it is
absent. The anti-regression that closed one third of this pattern does not reach
the other two thirds.

**What it costs today.** An operator-injected target, or an extraction site, on
the crater wall would be planned and driven with nothing refusing it. Measured
from the generator: the worst 1-sigma route to the relocated depot is **16.83° at
(−72.3, −130.8)**, over the declared 15.0 limit, and nothing in the system would
decline it. `terrain_guard` refuses targets **off the terrain**; it says nothing
about targets on impossible ground.

**Not fixed**: it needs terrain-aware A*, which is a real piece of work and not a
parameter wiring.

---

## D-29 — the exit gate's check 10 was structurally vacuous — CLOSED 2026-07-31, DEMONSTRATED

**Was**: check 10 asserted heatmap / overlay parity over whatever cells the map
happened to contain, and passed on **zero** cells. The two runs this workstream's
ground truth records as "11/11" both passed it that way: `total_observations` was
0 and the assertion never executed. **A gate that passes vacuously is a worse
artefact than a gate that fails**, because it converts an absence of evidence
into a green line in a report — which is the exact failure D-10 exists to name,
committed by the gate D-10 wrote.

**Now**: the check **seeds the map itself, through the real fusion path**. 49
synthetic `ResourceMapUpdate` readings shaped like `deposit_alpha` from
`ice_deposits.yaml` are published to `/orchestrator/map_update` on a 5 m lattice
over ±15 m, and the check then asserts the hottest cell decodes near the seeded
peak. It **FAILs or SKIPs** rather than passing silently on an empty map.

**MEASURED, twice, bit-for-bit identical:**

    1556 observed cells, 1556 cubes, 1556 matching colours, one header stamp, frame 'map'
    hottest cell 7.833 wt% at flat index 55169
      -> world (-80.5, -139.5), 0.707 m from the seeded peak
    total_observations 0 -> 3920   (predicted 3920)

0.707 m is the half-diagonal of a 1.0 m cell, and index 55169 reproduces the
offline prediction pinned in the probe's own docstring exactly. The only number
that moved between runs was `seed_wait_sec` (1.7 s / 1.8 s).

**It discloses its own seeding**, in the check row and again in a footer block
the script prints whether or not the run is green: *"Check 10 ran on a map this
gate seeded … It does not prove that robots autonomously survey the deposits."*
That disclosure is load-bearing — **the baseline was 0 observations after ~90 s
of real fleet operation on both runs**, so on the evidence of this gate the fleet
had surveyed nothing.

**Still not the PRD's method.** No image was compared and no RViz2 was run. And
the parity half recomputes through `resource_map_viz`, the same module the
publisher used, so a defect *inside* that module is invisible to it.

---

## D-30 — `_check_simulation_stall`: four false positives, zero true positives — CLOSED 2026-08-01, ROOT-CAUSED AND FIXED

> **CLOSED 2026-08-01 at `7727ba8`, and the root cause is a measurement error,
> not a threshold.** This entry said "the fix is a judgement rather than a
> constant". That was right about the remedy and wrong about the diagnosis:
> **the check was measuring the wrong quantity.**
>
> `_last_pose_change` is "time since this robot last moved 1 cm" — **a clock that
> runs while a robot is parked.** A robot that sat in IDLE for 60 s was therefore
> already "stalled" **the instant its FSM flipped to NAVIGATING**, before it had
> been given any chance to move. And parked robots are stalled by construction, so
> the *all online robots stalled* clause was satisfied for free by the nine
> members of a ten-robot fleet that happened to be parked — which made one wedged
> scout **bit-identical** to a dead simulator. Both of the observed failure modes
> above fall straight out of that: Run A's fleet-wide label on a single wedged
> `scout_04`, and Run B's two one-second all-stationary flickers.
>
> **Now**: `FleetMonitor.assess_motion` measures how long each robot has been
> **EXPECTED to move and has not** — a robot that is not expected to move is
> neither a mover nor stalled — and the fleet-level clause requires every *mover*
> to be stalled **and** at least `sim_stall_min_movers` of them
> (`fleet_monitor.py`; the parameter is declared at `orchestrator_node.py:1130`).
> The alert reports **"N of M"** rather than asserting a fleet-wide cause:
> `'{len(report.stalled)} of {len(report.movers)} robot(s) expected to be moving
> are in this condition.'` (`orchestrator_node.py`, `_report_per_robot_stalls`).
>
> **The threshold is derived from this repository's own kinematics, not from
> n = 1**: a 180° reversal from rest was integrated against the real
> `PathFollower` and the minimum per-sample displacement came out at **14.9×
> `POSE_MOTION_EPSILON_M`** (excavator) to **24.8×** (scout). D-21's genuine dead
> simulator still fires, with a test.
>
> **What the live evidence is worth, stated plainly: almost nothing.** The
> 2026-08-01 gate run logged **zero** `MOTION STALL` lines — but it was a
> two-minute run of four robots in which nothing was wedged, so it demonstrates
> the absence of a false positive on one short sample and **not** that a true
> positive would fire. The mechanism's evidence is
> `selene_orchestrator/test/test_simulation_stall.py`, which is a unit test, and
> this entry does not upgrade it beyond that. Two coverage holes are written into
> the code rather than only here: a robot that has given up and gone to ERROR is
> no longer expected to move, so once the whole fleet has given up the alert goes
> quiet (it dates the failure, it does not track it); and **a robot that never
> acquires a position fix is not watched at all**, because there is no position
> measurement to call stationary.

The entry as first written follows, unchanged — its present tense describes the
state before the status block above, and it is kept because it is the record of
how the defect was found.

Its own docstring predicts the wallpaper failure mode. The failure mode has
arrived.

**Measured across the two ten-robot runs of 2026-07-31:**

- **Run A**: it labelled a single wedged `scout_04` a **fleet-wide** freeze, at
  t=408.0 s, 201.5 s after the per-robot slip detector had already named the
  robot and the mechanism (D-25). Nine robots were fine. The alert's text was
  wrong about what had happened.
- **Run B**: it fired **twice** on roughly one-second all-stationary transitions
  and cleared one second later.

**Zero true positives in those two runs.** D-21 records it firing correctly once,
on a genuinely dead simulator, so the mechanism is real — it is the threshold and
the message that are wrong. Its window admits a moment when every robot happens
to be between waypoints, and its wording asserts a fleet-wide cause for a
condition that can have a single-robot one.

**Not fixed**, and the fix is a judgement rather than a constant: the honest
version probably requires the fleet to be simultaneously stationary *and* at
least one robot to be commanding non-zero velocity for a period longer than any
legitimate turn-in-place, and it should say "N of M robots" rather than asserting
a cause.

---

## D-31 — `fleet_distance_total` is 2.21× the fleet's true path — DIAGNOSED AND FIXED 2026-08-01; SUFFICIENCY NOT ESTABLISHED

> **This entry's title said "OPEN, NOT DIAGNOSED". IT IS NOW DIAGNOSED**, at
> `7727ba8`, and the mechanism is not the hypothesis recorded below.
>
> **The agent published a FABRICATED pose before odometry existed.**
> `GazeboOdometrySensor.read()` never raises; before the first `/odom_world`
> message it hands back a cached `OdometryReading` constructed with
> **`is_valid=False, x=0.0, y=0.0`** (`gazebo_hal.py:357-359`), and
> `AgentNode._publish_state` copied `odom.x` / `odom.y` straight into
> `RobotState.pose` **with no validity test — while the same file guards its
> other two odometry reads on exactly that flag.** The message had no way to say
> "this is not a measurement", so `FleetMonitor.update_robot` seeded `_last_pose`
> from the fabricated origin and booked **|spawn|** as travel the first time a
> real pose arrived.
>
> **The arithmetic, reproduced twice against the real module** (once by the
> diagnosis, once independently by its reviewer, both landing on the same
> digits): two (0, 0) samples then the true spawn pose books **1096.580 m** over
> the shipped ten-robot fleet — **90.050 m** (`scout_03`) to **127.224 m**
> (`hauler_02`) per robot — and **102.416 m** for a single scout at (−45, −92).
> **Every one of those increments is under the 500 m implausible-jump guard**,
> which was sized for respawns, so nothing rejected them and nothing counted
> them. The launch timing makes it certain rather than theoretical: agents all
> start at t = 12 s while spawns are staggered 2 s apart, so robots 7–10 publish
> state for 2–8 s before their Gazebo model exists.
>
> **SUFFICIENCY IS NOT ESTABLISHED, and this is the honest half.** 1096.580 m
> **OVER**-explains the 913.07 m excess rather than matching it. What the launch
> timing guarantees is that robots 7–10 fabricated; their spawns sum to
> **470.717 m, 51.6% of the excess**. Whether the other six also fabricated was
> never measured, and if they did not, **roughly 442 m remains unattributed.**
> A second mechanism of the same shape is **NOT eliminated**:
> `world_odometry_node` re-evaluates `truth_fresh` on every odom message against
> a 1.0 s timeout, so one second of silence on `/pose_truth` flips the published
> pose to dead reckoning and back — two jumps of |DR − truth| per episode, which
> this register measures at **166.2 m** for `hauler_02` on that same run, all of
> it under the 500 m guard. The figure usually cited against that
> ("worst |odom_world − truth| = 0.0816 m") is ~0 **by construction** in
> localisation mode and cannot detect a flip. **The mechanism is proven; that it
> accounts for the whole excess is not, and this closure does not claim it.**
> The caveat is committed in the test's own docstring
> (`selene_orchestrator/test/test_fleet_distance.py:21-40`), not only here.
>
> **The fix is a new field on a published message, and it is fail-safe by
> choice.** `selene_msgs/msg/RobotState` gains a trailing `bool pose_valid`;
> `pose` is **still populated** when it is false — the flag carries the meaning,
> not the value — because the same message is the heartbeat
> `FleetMonitor.check_heartbeats` reads. **The cost of the fail-safe default is
> stated rather than assumed** in the `.msg` file itself: ROS 2 default-initialises
> `bool` to false and a subscriber cannot tell "the publisher set it false" from
> "the publisher never set it", so any `RobotState` built by code not rebuilt in
> the same pass reports "no fix" and drops out of the distance total and the
> orchestrator's survey centroid. **Rebuild all six packages in one `colcon
> build`.**
>
> **Three readers consume it**, which is what makes this different from the
> orphan pattern: the orchestrator directly (`fleet_monitor.py`,
> `orchestrator_node.py`); the exit-gate probe, through
> `getattr(msg, 'pose_valid', True)` (`scripts/phase5_probe.py:962`) so that a
> pre-D-31 workspace degrades rather than crashes, with samples carrying
> `pose_valid = false` **dropped** from the motion measurement (`:2765`); and the
> dashboard (`useFleetState.js`, `utils/poseFix.js`, `FleetCards.jsx`,
> `MissionProgress.jsx`, `RobotDetail.jsx`).
>
> **The dashboard half was DEMONSTRATED IN CHROME on 2026-08-01 — against a
> rosbridge test double, not the real stack.** A robot with no fix moves to an
> amber **"NO POSITION FIX"** roster reading *"not drawn — position unknown, not
> (0, 0)"*, keeps its card and its battery gauge, presents no hit target on the
> map (`FleetMap.jsx:1244`, `:1814`), and moves onto the map when odometry
> arrives. That observation proves what the browser does when messages of that
> shape arrive and **nothing about ROS, DDS or QoS**. **No robot has yet been
> seen publishing `pose_valid = false` on a real run.**
>
> **A sixth instance of the wired-but-never-called pattern was found here.**
> Until 2026-07-31 `FleetMonitor.get_total_distance` had zero *test* callers and
> `get_robot_distance` had **zero callers anywhere in the repository**. The
> assertions in `test_fleet_distance.py` are the first this accumulator has ever
> carried. Every rejected increment now also carries its **magnitude**, because a
> count of eight cannot distinguish eight 2.6 m hiccups from four 166 m flips.

The entry as first written follows, unchanged — its present tense describes the
state before the status block above, and it is kept because it is the record of
how the defect was found.

**Measured on the ten-robot run**: `MissionProgress.fleet_distance_total`
reported **1665.37 m** against **752.3 m** of true fleet path — and the 752.3 m
is trustworthy, because two independent integrals agree on it (Gazebo ground
truth 752.3 m, `odom_world` 753.8 m, 0.2% apart over 753 m).

The number is produced by `FleetMonitor.get_total_distance()`
(`fleet_monitor.py:332`), fed to `_build_mission_progress` at
`orchestrator_node.py:2129` and published at `:919`.

**I did not diagnose it and neither did the run that found it.** The obvious
candidate — accumulating `|Δp|` per `RobotState` sample, so that pose noise
integrates into distance — is a **hypothesis and is recorded as one**. It is
consistent with a ratio above 1 and with the ratio being roughly constant, and it
is not evidence. Anyone picking this up should start by comparing the
accumulator's sample rate and its rejection threshold against the 2 Hz state
topic.

It is a dashboard-facing number in a P1 requirement, and it is currently wrong by
a factor of two.

---

## D-32 — the recharge station is behind an unclimbable wall — DISSOLVED 2026-08-01, NOT FIXED

> **DISSOLVED is the honest word, and it is not a synonym for fixed.** Nothing
> moved the pad, nothing graded a route and nothing changed the terrain. What
> changed is that the premise below — that the wall is unclimbable — turned out to
> be a statement about **climbing it straight up**, which is the one heading no
> route has to take. See D-28: at a measured per-step limit of 20°, a path ≥ 57.4°
> off the fall line of 34.02° ground climbs at ≤ 20° for a 1.85× length penalty.
> **The wall was never unclimbable; it was unclimbable straight up, and nothing
> had ever asked the planner to go round.**
>
> **MEASURED at `9c1a4d7`**, over the 500 × 500 / 1.0 m lattice, 8-connected, on
> the collision heightmap: under the per-step rule at 20° the navigable set is
> **one connected component** of 249,792 cells, and executed plans give
>
>     spawn -> depot        132.0 m against  79.9 m straight   (1.65x)
>     depot -> recharge pad 130.2 m against  86.0 m straight   (1.51x)
>
> — the switchback, measured. **Both are executed plans over the committed
> heightmap. NO VEHICLE HAS DRIVEN EITHER OF THEM.** The live corroboration is one
> step weaker and one step more useful: every agent on the 2026-08-01 gate run
> logged `depot (-100.0, -150.0): REACHABLE | recharge_pad (-30.0, -100.0):
> REACHABLE` at startup, which is the planner's own lattice answering, not a
> journey.
>
> **The three-way coordinate disagreement is resolved by DELETION, not by
> promotion.** `mission.recharge_position: [-75.0, -100.0]` is **deleted** from
> `nav_params.yaml` rather than corrected, and the reasoning is recorded at the
> point of deletion (`selene_agent/config/nav_params.yaml:126-140`): it was read
> by nothing, it disagreed with both the physical `recharge_pad` include in the
> world and `agent_node`'s own parameter default, and it sat on ground no robot
> could have stopped on. **Promoting an unread key to authority is the same defect
> from the other end** — it would have moved every robot's charger 45 m. The
> single source of truth is the physical pad at (−30, −100): the world marker,
> `world.recharge_station.position` in `world_params.yaml`, and the
> `recharge_x` / `recharge_y` parameters `agent_node` declares and
> `agent.launch.py` now passes explicitly. Two other silent duplicates went with
> it (`low_battery_threshold`, `recharge_target`), each a copy of a ROS parameter
> that is declared and read.
>
> **What is NOT resolved.** The pad still recharges from solar and the crater is
> still permanently shadowed, so the *power architecture* objection in the body
> below stands untouched — a route exists; sunlight at the depot does not. And no
> robot has yet made the return leg: on the 2026-08-01 run `scout_02` tried, under
> D-42's spurious 0% battery, and got 0.71 m from the pad marker on a planned path
> it never completed.
>
> **`test_mission_traversability.py` was STRENGTHENED, not weakened, by this
> change.** Its deposit-edge assertion failed at 20° exactly as predicted —
> 16.83° at (−72.3, −130.8), reproducing this register's own figure — and the
> `> limit` inequality it used, which passed for anything between 15 and 90,
> became a ±0.05° value pin **plus** `<= limit`.

The entry as first written follows, unchanged — its present tense describes the
state before the status block above, and it is kept because it is the record of
how the defect was found.

D-23 moved the depot onto the crater floor because that is where the mission is.
**The recharge pad is still on the illuminated plain outside**, at (−30, −100),
behind the same 34° rim. Every robot that depletes in the deposit field and tries
to go home has to climb the wall D-23 established it cannot climb.

**It is not fixable by moving the pad into the crater.** The pad recharges from
solar; a permanently shadowed region has no sun. The mission needs either a power
architecture that does not depend on the pad's insolation, or a graded route out,
which is the same deferred work D-23 names.

**Three coordinates still disagree**, which is open item 7 unresolved and now
more visible: `agent_node.py:122-123` defaults `recharge_x`/`recharge_y` to
(−30, −100) — the value that actually reaches the agent — while
`nav_params.yaml:48` says `recharge_position: [-75.0, -100.0]` and is not read
for this, and `energy_manager`'s constructor default is (40, 40).

**Nothing has hit it and nothing detects it.** Batteries on the ten-robot run
ended between 0.73 and 1.00, so no robot attempted the return leg. There is no
check that a configured position is reachable — that is D-28's missing slope
limit, from the other end.

---

## D-33 — `/odom` was dead-reckoned from spawn and consumed as world coordinates — CLOSED 2026-07-31, DEMONSTRATED

**This closes D-08's closing note and "Open items carried forward" item 2**, both
of which have carried this defect since the register was written.

**Was**: Gazebo's DiffDrive plugin integrates `/odom` from each robot's **spawn
pose**, and every consumer in SELENE treated it as world coordinates. The
register's own text said the map was "internally consistent … but the region
sampled is not where the robot physically is" — which was true and understated
the damage. `nav_params.yaml` lists all 26 rocks in **world** coordinates, so
obstacle avoidance was dodging rocks that were not where the robot was, while the
robot drove into real ones.

**The size of the error was got wrong first, and the correction is the point.**
An operator hypothesis modelled the frame as a **translation**. Under that model
several commanded targets left the ±248 m heightfield, and the terrain-edge
theory of the ODE abort was built on it. `scripts/check_drive.sh` was then run:

    settled       x=-45.0033  y=-91.9797  z=1.48533  yaw=-2.36722
    after drive   x=-48.7395  y=-95.6305  z=1.90063  yaw=-2.36800
    WORLD displacement 5.2237 m (97.8% of command); ODOM 5.1892 m; slip -0.67%
    bearing(world) - bearing(odom) = -2.3678 rad; spawn yaw -2.3300
    SE(2) hypothesis off by 0.0378 rad, translation-only off by 2.3678 rad

**The frame is a full SE(2) — rotated into the spawn heading.** Under it, none of
those targets leaves the terrain, and **the terrain-edge theory is refuted**. See
D-37.

**Now**: one conversion point and no second opinion.

- `selene_sim/selene_sim/world_frame.py` — pure SE(2) helpers plus `TerrainBounds`.
- `selene_sim/selene_sim/world_odometry_node.py` — `/<rid>/odom` →
  `/<rid>/odom_world`, `frame_id: map`, one node per robot, started by
  `simulation.launch.py` from the **same pose dict** that feeds `ros_gz_sim create`.
- `selene_hal/config/*.yaml` — the odometry sensor's topic moves `odom` →
  `odom_world` in all three RCDLs, so no behaviour code changed.
- `neutron_spectrometer_node`, `hopper_node`, `extraction_node` and
  `battery_node` all moved to `odom_world` together.
- `selene_orchestrator/selene_orchestrator/terrain_guard.py`, with guards in
  `inject_task_logic` and `override_robot_logic`, and `AStarPlanner.plan`
  refusing off-terrain goals.

**MEASURED — the frame gate, on all ten robots.** Every `world_odom_<rid>`
first-pose line equals `spawn_positions.yaml` exactly:

    scout_01: first world pose (-45.000, -92.000) yaw -2.3300 rad from odom (0.000, 0.000)
    ...
    hauler_03: first world pose (-52.000, -102.000) yaw -2.3300 rad from odom (-0.000, 0.000)

Against `gz model -p` ground truth: stationary robots **2.9 mm** (hauler_01) and
**4.6 cm** (excavator_01); moving scouts, bearing-from-spawn, **0.033 rad** and
**0.004 rad**. The counterfactual — translation only — would have been **17.14 m**
and **12.26 m** off.

**A residual bias is recorded rather than rounded away.**
`spawn_positions.yaml` declares yaw −2.33 for every robot and
`world_odometry_node` consumes that literal, but `check_drive.sh` measured the
**settled** yaw at −2.36722: a systematic **0.037 rad (2.1°)** rotation error in
the transform, presumably the robot settling on the slope after spawn. The frame
gate's 0.033 rad bearing check **passed while measuring that bias rather than
bounding it**. It accounts for only a few metres at mission distances and does
not threaten anything above, but it is a known, unfixed error in a transform this
entry describes as correct.

**Consequence worth carrying forward**: navigation targets are now genuinely
world coordinates, so robots drive to different physical places than in any run
recorded before 2026-07-31. Comparisons across that boundary are not valid.

---

## D-34 — the exit gate cannot observe an FSM state shorter than its sampling period — CLOSED 2026-08-01, DEMONSTRATED ON THE GATE'S OWN OUTPUT

> **CLOSED 2026-08-01. Both halves were fixed at `7727ba8`, and the 2026-08-01
> gate run returned ZERO SKIPS — checks 6 and 9 both produced verdicts and both
> PASSed, so PRD exit-gate rows 3 and 4 are measured for the first time.**
>
> **Agent side**: `AgentFSM` gains a transition observer and `AgentNode`
> publishes `RobotState` **on transition** as well as on the 0.5 s timer, so a
> 0.247 s IDLE window is no longer structurally invisible.
> **Gate side**: the probe detects the transition from the sample history **it
> was already recording and throwing away**, so it is correct even if the agent
> half were absent. Two halves, either sufficient — which is the right shape for
> an instrument, because the gate must not depend on the thing it measures.
>
> **Two comments that DEPENDED on the old blindness were made false by this
> change and are rewritten rather than left standing** (`fsm.py`,
> `recharge_policy.py`). That is the failure mode this register keeps finding:
> a comment describing behaviour that a later change removed.
>
> **What the live run shows, and where it stops.** `scout_01` was freed by an
> operator `cancel_task` at `297.9157` and left IDLE at `298.1354` — an IDLE
> window of **0.220 s** — and the gate recorded an IDLE state sample inside it
> (`check 6`: *"corroborated by an IDLE state sample after the cancel"*). A 0.5 s
> timer alone catches a 0.220 s window less than half the time, so this is
> **consistent with** publish-on-transition carrying the sample and is **not
> proof** that it did; n = 1 cannot separate them.
>
> **A separate thing this run measured, which the SKIP used to hide.** The probe
> still waited its full **60 s** for a naturally IDLE prospect-capable robot and
> none appeared — all four robots were busy. That is fleet behaviour, not an
> instrument defect, and it was invisible while the check SKIPped. The check now
> says so in its own row: *"this row was measured on a robot the gate
> perturbed."*
>
> **The product observation below still stands, and is NOT closed by this.** The
> dashboard consumes the same topic; it now sees transitions because the
> publisher emits them, and a **247 ms IDLE hand-off (NAVIGATING → IDLE →
> BIDDING) was observed in `RobotDetail`'s state history in Chrome on
> 2026-08-01 — against a rosbridge test double, not the real stack.** The old
> `throttle_rate: 500` would have dropped it. **That proves the transport and the
> render, not the agent**: the edges were published by a test double, and the
> agent half's authoritative evidence is the gate run above.

The entry as first written follows, unchanged — its present tense describes the
state before the status block above, and it is kept because it is the record of
how the defect was found.

**Two of the PRD's seven exit-gate rows are currently unmeasurable, and the
system is not why.**

`pick_prospect_robot` (`scripts/phase5_probe.py:1775-1783`) polls
`probe.latest_state(freed)` for `fsm_state == 'IDLE'` for 10 s. `RobotState` is
published from a **0.5 s timer** (`selene_agent/selene_agent/agent_node.py:299`).
Measured from the two gate runs' launch logs:

    | run | cancel accepted | -> IDLE      | -> BIDDING   | IDLE lasted |
    |-----|-----------------|--------------|--------------|-------------|
    | 1   | 131.417886      | 131.418348   | 131.665462   | 0.247 s     |
    | 2   | —               | 496.478300   | 496.779290   | 0.301 s     |

The FSM crosses IDLE in **half a state-publish period**. No sample carried it, so
the probe waited its full 10 s and returned a failure string — while the system
did exactly what check 6 asserts, as D-04's status block quotes from the same
log. **Checks 6 and 9 SKIPped on both runs**, costing PRD rows 3 and 4.

**This is D-10's failure mode inverted**: not a check claiming more than it
measured, but a check reporting nothing on a system that satisfied it. A SKIP is
correctly not a pass — the gate's contract is right. The instrument is wrong.

**Why it misses reliably rather than about half the time is a hypothesis, not a
measurement.** The agent's state timer and the orchestrator's auction tick are
both 0.5 s and both start when the launch brings the nodes up together, so the
IDLE interval plausibly sits at a near-fixed phase relative to the sampler. n=2
cannot establish that. **What is certain regardless of mechanism**: a 0.25–0.30 s
state cannot be reliably seen by a 0.5 s sampler.

**And the same limit applies to the dashboard**, which consumes the same 2 Hz
topic. A task hand-off through IDLE is invisible to any consumer of
`/{rid}/state`. That is a product observation, not just a gate one.

**Not fixed.** The options are a real one — subscribe to the transition rather
than the state, or publish state on change as well as on the timer — and this
document's owner does not own either file.

---

## D-35 — the gate's send-to-location check is a coin flip — CLOSED 2026-08-01; THE CHECK STILL FAILS, FOR A DIFFERENT REASON

> **CLOSED 2026-08-01 at `7727ba8`, and the closure has to be read carefully:
> check 11 FAILED again on the 2026-08-01 run, and it did not fail for this
> reason.** D-35 is the *aim* of the instrument, and the aim is fixed. What took
> the check down on 2026-08-01 is **D-42** — the gate chose a robot reporting 0%
> battery and never asked whether it could perform the manoeuvre.
>
> **Fixed as this entry demanded and not the way it warned against.** The bearing
> is now chosen **relative to the robot's current heading**, and the baseline is
> **re-sampled after the override is accepted**. **The 12 s window literal is
> DELETED, not raised** — widening it would have been choosing a threshold from
> n = 1, which is the move this register exists to prevent.
>
> **Both repairs are visible inside the 2026-08-01 failure line itself**, which is
> the cleanest evidence available that they are in force:
>
>     bearing +45 deg off heading 0.691 rad, target (-30.96, -95.20),
>     window 11.0s derived at 0.50 m/s from
>       /home/hoyer/selene/install/selene_hal/share/selene_hal/config/scout.yaml,
>     pose_source localisation
>
> **The verifier then found that the mechanism credited with killing the coin flip
> had NO regression test** — mutating it to always-true left all 45 tests green.
> The decision is now extracted into a pure function pinned by 11 more tests, of
> which 9 mutations each turn at least one red; the extraction is proven
> behaviour-preserving over 168 exhaustive and 20,000 randomised histories with 0
> mismatches. **That is the part of this closure that would have been worth doing
> even if the check had gone green**: a fix with no test that fails without it is
> not closed, it is asserted.
>
> **Both reporting defects this entry recorded as "neither repaired" are
> repaired**, and both are visible in the regenerated report:
> 1. `path_note` is now included in the **FAIL** message — the 2026-08-01 FAIL
>    row carries `planned_path ends (-29.50, -99.50), 4.54 m from the commanded
>    target`, which is exactly the evidence run 1's FAIL withheld.
> 2. PRD row 5's coverage column no longer says the displacement is read off a
>    pose that is *"STILL DEAD-RECKONED"*; it now states that `/<rid>/odom_world`
>    carries the simulator's **true world pose** whenever `pose_source` is
>    `localisation`, that the check reads that parameter off each `world_odom`
>    node and prints what it found, and that the fallback to dead reckoning
>    happens only with an ERROR log and a CRITICAL `FleetAlert`.
>
> **What is now visibly missing from the check, and is NOT closed here.** Check 11
> selects a robot and issues the override without establishing that the robot can
> obey it. On 2026-08-01 it picked `scout_02` at 0.0% battery; the FSM went
> `RETURNING --(OPERATOR_GOTO)--> NAVIGATING` and **six milliseconds later**
> `NAVIGATING --(ENERGY_CRITICAL)--> RETURNING`, so the planned path ended
> **0.71 m from the recharge pad** and 4.54 m from the commanded target. The
> override path did exactly what it is supposed to do, twice, in the right order.
> **A precondition on check 11 is a real remaining gap in the gate**; it is listed
> in the disposition rather than patched here, because the first question is why a
> robot reported 0% at all — **D-42**.

The entry as first written follows, unchanged — its present tense describes the
state before the status block above, and it is kept because it is the record of
how the defect was found.

**Check 11 FAILed on run 1 and PASSed on run 2, on identical invocations.** It is
not currently trustworthy in either direction.

`run_send_to_location` (`scripts/phase5_probe.py:2168`) always tries bearing
`(+6.0, 0.0)` — **due east** — first, and commits to the first bearing that
reaches NAVIGATING (`attempts` was empty on both runs). The fleet spawns at
x = −45 and every robot drives **south-west** into the PSR, so due east is
systematically about 165° behind the robot under test.

**Measured** from a read-only pose subscriber during run 2: the robot stops, then
turns at a **saturated 1.0 rad/s** while driving at 0.5 m/s, sweeping **164.8°**.
The arc carries it up to **3.745 m away** before its +x displacement turns
positive at **t ≈ 10.2 s**. Check 11's window is **12 s** — 1.8 s of margin on a
manoeuvre that takes 10.2 s. The two runs landed either side of that line:

    run 1  FAIL  dot = -0.951  ->  mx = -15.9 cm
    run 2  PASS  dot = +1.039  ->  mx = +17.3 cm

**33 centimetres of x-displacement on a 3.6 m arc separated FAIL from PASS.** The
check is measuring whether a differential drive can complete a 165° about-turn in
under 12 s, not whether `send_to_location` works.

**The override itself worked on both runs.** Assertion (4) — the one the probe's
own docstring calls "what actually proves the target was honoured" — passed both
times; run 2 states it as `planned_path ends (-65.50, -111.50), 0.50 m from the
commanded target`.

**Two reporting defects found with it, neither repaired:**

1. `path_note` is computed but included only in the PASS message (`:2226-2244`),
   so run 1's FAIL **withheld the one piece of evidence showing the override
   succeeded**.
2. Row 5's generated coverage column still says the displacement is read off a
   pose that is *"STILL DEAD-RECKONED, so it advances whether or not the robot
   moved in the world"*. That was true before D-24; the launch log now shows all
   four nodes reporting `pose_source localisation`, so check 11's displacement is
   the simulator's **true world pose**. The caveat is wrong in the safe direction
   — it understates — and the same wording is in `run_send_to_location`'s
   docstring (`:2140-2144`). Both should be corrected: this register's own rule
   is that a document's value is its accuracy.

**The fix must not be a constant bump.** Widening the window from 12 s to 15 s
would be choosing a threshold from n=1. The considered options are: pick a
bearing relative to the robot's current heading, retry the next bearing on a
displacement failure, or start the measurement from rest.

---

## D-36 — the two-package test lane is red again, from the opposite direction to D-14 — FIXED 2026-07-31

**Found 2026-07-31 (evening) by this register's owner, by re-running every lane
the register documents instead of copying its own numbers forward.**

    PYTHONPATH="selene_orchestrator;selene_isru" \
      python -m pytest selene_orchestrator/test selene_isru/test -q
      -> 1 failed, 518 passed

`selene_orchestrator/test/test_terrain_guard.py:343` executes a bare
`from selene_agent.navigator import OccupancyGrid` inside a test body, with no
`pytest.importorskip` and no guard, so the lane **fails** rather than skips when
`selene_agent` is not on the path. The test itself is a good one — it pins the
orchestrator's terrain guard and the agent's planner against the same box, which
is exactly the cross-implementation check this repository needs — and its import
is unguarded.

**Which lane broke matters.** This register calls that invocation "THE GATE LANE"
and lists it in Verification limits at 327 passed. It is also the `PYTHONPATH` the
CI `e2e-integration` job declares — that job survives only because it runs a
single file.

**Neither existing guard can see it.** The CI `cross-package-tests` job puts all
five packages on the path; so does the operator's Windows lane. **D-14's rule was
"do not add a test lane without a cross-package lane". The converse is now also
true**: a cross-package assertion needs a guard for the lanes that do not span
those packages, or it converts a missing optional dependency into a red suite.

**FIXED 2026-07-31**, immediately after this entry was written, by the operator
rather than by this document's owner — the entry above stands as written because
it is the record of how the defect was found.

`test_terrain_guard.py:343`'s bare `from selene_agent.navigator import
OccupancyGrid` is now `pytest.importorskip('selene_agent.navigator', reason=...)`,
with the two-lane reasoning recorded in the test's own docstring. **Both halves
were measured, and the second is the one that matters:**

    gate lane        518 passed, 1 skipped   (was 1 failed, 518 passed)
      SKIPPED [1] test_terrain_guard.py:358: cross-package agreement check;
                  selene_agent is not on the gate lane PYTHONPATH (D-36).
    cross-package    test_terrain_guard.py -> 51 passed, 0 skipped
    full lanes       826 passed / 1 skipped, sim 120 passed / 1 skipped, flake8 clean

A skip is only safe if some lane still runs the assertion. The cross-package lane
does — 51 passed, no skip — so the orchestrator/agent box agreement is still
checked, on the lane that can check it. Had the skip fired on both lanes this
would have been a worse defect than the red one it replaced, which is exactly
D-14's complaint about `importorskip` and why the counts above are recorded
rather than asserted.

**Still open, and inherited from this entry**: nothing in CI runs
`selene_orchestrator/test` alone. `e2e-integration` declares that PYTHONPATH but
names a single test file, so it would not have caught this. A lane that runs the
whole orchestrator suite on the two-package path is still missing.

> **THAT REMAINDER IS CLOSED, 2026-08-01 at `d390315`.** A new CI job
> **`gate-lane-tests`** (`.github/workflows/ci.yaml:121`, "Gate lane pytest
> (orchestrator + isru only)") runs the gate lane **whole** — the command this
> register calls THE GATE LANE and the one the operator runs by hand now has a
> machine reading it. It installs the **same** dependency set as
> `cross-package-tests` so that `PYTHONPATH` is the only variable between the
> two, and on failure it names D-36, because a red gate lane beside a green
> cross-package lane has essentially one cause.
>
> **MUTATION-TESTED before commit rather than asserted.** The `importorskip`
> guard was removed, all three legs were measured, and the file was then restored
> byte-identical to HEAD:
>
>     guard removed, gate lane (2 pkgs)       1 failed, 518 passed   <- catches it
>     guard removed, cross-package (5 pkgs)   51 passed              <- blind
>     guard restored, gate lane               518 passed, 1 skipped
>
> The first line **reproduces this entry's own recorded measurement exactly**.
> The second is the point: the job that already existed cannot see this defect.
>
> **Verified green in CI on this branch**: the `gate-lane-tests` job's "Run the
> orchestrator and isru suites on the two-package path" step succeeded in runs
> `30678095310` (`d390315`), `30681543994` (`7727ba8`) and `30685883138`
> (`9c1a4d7`).
>
> D-14's rule was "do not add a test lane without a cross-package lane". Its
> converse — a cross-package assertion needs a guard for the lanes that do not
> span those packages — is D-36. **Both now have a job behind them.**

---

## D-37 — the ODE abort: three reproducible crashes — STILL OPEN, but the MECHANISM is now identified and one candidate explanation is REFUTED BY MEASUREMENT

> **AMENDED 2026-08-01 (late).** The entry below still stands on everything it
> says. What is new is that the assertion's trigger condition is now known at
> source level, the terrain-edge theory is refuted a **third** time by
> independent arithmetic, and the most attractive new explanation — "the box was
> running a gz-physics without the upstream fix" — **was checked and is false**.
> The cause of the three aborts remains unknown. No cause is proposed here.
>
> ### THE ASSERTION FIRES ON NaN
>
> `dICHECK(aabbBound >= dMinIntExact && aabbBound < dMaxIntExact)` sits in ODE's
> `collision_space.cpp` inside `dxHashSpace::collide`, where
> `aabbBound = geom->aabb[i] * 2^-level`. It fails on exactly two inputs: a **NaN**
> AABB coordinate — every comparison against NaN is false, so the check fails at
> *any* magnitude — or a **finite-but-astronomical** one. It does **not** fail on
> infinities: `findLevel()` returns `MAXINT` for an infinite AABB and the geom is
> routed to `big_boxes`, which is how ODE handles infinite planes. There is no
> plane in this world in any case (`grep -rn "<plane>" selene_sim/` → no match).
>
> **The finite bound, derived rather than guessed.** DART sets
> `dHashSpaceSetLevels(mSpaceId, -2, 8)`, so `2^-level ≤ 4`; `dMaxIntExact` is
> `2147483647` (double-precision ODE) or `16777215` (single). The tightest geom
> in this fleet is a wheel (AABB ≈ 0.2–0.24 m → level −2 → factor 4), giving a
> coordinate limit of **5.37 × 10⁸ m** (double) or **4.19 × 10⁶ m** (single).
>
> ### THE TERRAIN-EDGE THEORY IS REFUTED A THIRD TIME, INDEPENDENTLY
>
> Free fall at 1.62 m/s² reaches 4.19 × 10⁶ m in **37.9 minutes** and
> 5.37 × 10⁸ m in **7.15 hours**. The three aborts were at **~5, ~21.5 and
> ~29 minutes**. **A fall cannot produce this assertion in the observed times**
> — whatever the robot did, and regardless of the SE(2) frame argument and the
> 200,027-sample measurement that refuted it twice already. Three independent
> refutations now agree, and this one needs no measurement at all.
>
> ### THE HEIGHTFIELD IS STRUCTURALLY EXEMPT, AND THE PRINT IS CONFIRMED AT SOURCE
>
> `Dbg ODE Heightfield AABB` is emitted by
> `dart/collision/ode/detail/OdeHeightmap-impl.hpp` **inside the
> `OdeHeightmap<S>::OdeHeightmap(...)` constructor**. It cannot be emitted from
> inside `collide()`. Verification-limit item 22's "strongly supported and not
> directly checked" inference is now checked from the other end. And the
> heightfield's own AABB extent of 496.124 m gives `frexp` level 9, above DART's
> `global_maxlevel = 8`, so it lands in `big_boxes` and **never reaches the
> `dICHECK` at all**. The crashing geom is a robot geom, necessarily.
>
> ### UPSTREAM FIXED THIS, THE FIX IS ON THIS BOX, AND IT WAS ON THIS BOX WHEN THE ABORTS HAPPENED
>
> gz-physics **PR #706, "Prevent crash when objects move to invalid poses"**,
> closes gz-physics issue #661 — the identical assertion — with the diagnosis:
> *"DART seems to compute invalid poses for certain objects … with large
> accelerations. The computed poses end up with `nan` values resulting in a
> crash."* It adds a post-step `model->getPositions().hasNaN()` check to
> `dartsim/src/SimulationFeatures.cc::WorldForwardStep` that rolls back to the
> last good positions and logs `Some links in model '<X>' have invalid poses`.
> Backported to `gz-physics7` as **PR #707, merged 2024-12-19**, first released
> in **7.5.0**.
>
> **MEASURED ON THE OPERATOR'S BOX, 2026-08-01:**
>
>     libgz-physics7-dartsim:amd64   7.8.0-1~noble
>     dpkg.log: 2026-07-29 17:44:10 status installed  (one entry, never upgraded)
>     strings libgz-physics7-dartsim-plugin.so | grep "invalid pose"
>       -> ' have invalid poses.'          GUARD PRESENT
>
> The three aborts were on **2026-07-30 and 2026-07-31**. The package was
> installed on **2026-07-29** and has not been touched since. **So the upstream
> NaN guard was present, in the loaded binary, for all three aborts.** The
> tidiest available explanation is dead: this is not a stale-package bug, and
> `apt upgrade` is not the remedy.
>
> **AN INFERENCE, LABELLED AS ONE, ABOUT WHY THE GUARD DOES NOT COVER THIS.**
> The guard is a **post-step** check: it runs after `WorldForwardStep` returns.
> The assertion fires **during** the step, inside
> `WorldForwardStep → ConstraintSolver::solve → collide`. A NaN that first
> reaches a geom's transform within step *N* is therefore presented to
> `collide()` in step *N* and aborts before the end-of-step check ever executes;
> the guard can only stop a NaN produced in step *N* from poisoning step *N+1*.
> **This has NOT been verified** — it is read off the call order, not observed.
> What would confirm it: the next abort should carry **no**
> `Some links in model … have invalid poses` line before it. What would refute
> it: that line appearing, and the run continuing.
>
> ### THE EXPOSURE ARITHMETIC THE ENTRY ASKED FOR, COMPLETED
>
> The entry names a per-metre alternative but does not quantify it.
> λ = 3 / (522 + 1400 + 1900) = **1/1274 per fleet-metre**. Under it the
> 1288.8 abort-free metres carry a **36 % survival probability** — they
> establish nothing. Rejecting it needs **3,817 m** (p<0.05) or **5,867 m**
> (p<0.01).
>
> **And the clean runs were not at the same operating point as the crash runs.**
> 1288.8 m / 24,327 robot-seconds = **0.053 m per robot-second**, against
> **0.174 / 0.201 / 0.368** for the three crash runs — 3.3× to 6.9× less driving
> per robot-second. Under a per-metre hazard *that alone* explains the clean
> runs, with no appeal to any of the four configuration changes the entry
> credits. (Caveat, and it matters: the crash-run distances are this register's
> own "~" figures and are probably **dead-reckoned**, which over-reads under
> slip — the 126.7 m phantom. It is a ratio between two instruments, one known
> to over-read. That is a reason to run the experiment, not evidence.)
>
> ### THE EXPERIMENT, COSTED — AND A BLOCKER NOBODY HAD FLAGGED
>
> A 4/3/3 fleet held driving accrues ~2.7 fleet-m/s at a realistic 75 % duty
> cycle, so **~25 minutes clears both hazard models at p<0.05 and ~39 minutes at
> p<0.01**, at 0.27 m/robot-second — inside the crash runs' 0.17–0.37 band,
> which the clean runs never entered. Anything under 20 minutes rejects neither
> model and is not worth the box time.
>
> **A single driving arm cannot DISTINGUISH the two models**, only reject both:
> metres and robot-seconds accrue together. Distinguishing needs either an abort
> (whose exposure ratio then discriminates) or a second **parked** arm — the same
> ten agents alive and physics stepping, commanded to hold station, accruing
> robot-seconds at ~0 m.
>
> **The blocker: the fleet cannot physically drive that long.**
> `ENERGY_PARAMS` gives a scout 50 Wh against 10 + 150 × 0.39 = 68.5 W of driving
> draw — **flat in 43.8 min**; hauler 42.9; excavator 53.3. A 45-minute driving
> campaign runs the fleet into the recharge cycle it is trying to avoid, and the
> robots stop driving exactly when the exposure would start to count. Any
> campaign design has to solve that first, and none has.
>
> ### THE CAMPAIGN HAS NOW BEEN RUN, 2026-08-01. BOTH HAZARD MODELS ARE REJECTED AT p<0.01.
>
> `scripts/d37_drive_campaign.sh` + `.py`, 45 minutes, a 4/3/3 fleet held driving
> at the simulator layer with no agents and no orchestrator. **The battery
> blocker dissolved rather than being worked around**: nothing in the physics
> consumes `BatteryState` — no `<battery>` element and no `LinearBatteryPlugin`
> anywhere in `selene_sim`, `battery_node` only publishes, and the only two
> things that ACT on the value live in `agent_node`. The abort is raised inside
> `dartsim WorldForwardStep → ConstraintSolver::solve → dxHashSpace::collide` and
> not one line of `selene_agent` is on that stack, so removing the agents removes
> nothing the hazard depends on and removes the one thing that made the
> experiment impossible.
>
> **ACHIEVED, against the thresholds this entry derived:**
>
> | | achieved | p<0.05 | p<0.01 |
> |---|---|---|---|
> | fleet-metres | **7,569.9** | 3,817 | 5,867 |
> | robot-seconds | **26,970** | 15,098 | 23,210 |
> | survival, per-robot-second model | **0.0047** | | |
> | survival, per-fleet-metre model | **0.0026** | | |
>
> **AND IT RAN AT 0.281 m PER ROBOT-SECOND — INSIDE the crash runs' 0.174–0.368
> band.** That is the point. The two clean runs this entry already had ran at
> **0.053**, i.e. 3.3× to 6.9× less driving per robot-second, which is exactly
> why their exposure argument was weak: under a per-metre hazard that alone
> explained them. This run is the first clean exposure **at the operating point
> where the crashes actually happened**.
>
> **NO ABORT. AND THE GREP THAT SAYS SO HAD TO BE READ CAREFULLY**, which is
> itself worth recording. `grep -c "ODE INTERNAL ERROR"` returns **1** — and that
> match is D-26's own explanatory banner, which `_diagnose_simulator_exit` prints
> on ANY simulator exit and which quotes the assertion text verbatim. The
> simulator's actual return code was **−9 (SIGKILL), from this script's own
> teardown**, not 134/SIGABRT. A naive reading of that grep would have reported
> an abort that did not occur. The three strings, correctly read:
>
>     ODE INTERNAL ERROR (real abort)   0   (1 match, and it is the banner)
>     "have invalid poses" (NaN guard)  0
>     exit code 134 / -6                0
>
> **The upstream NaN guard never fired either**, so this run says nothing either
> way about the post-step inference above; that question needs an abort to
> settle and this run did not produce one.
>
> ### WHAT THIS DOES AND DOES NOT ESTABLISH
>
> * **It rejects both hazard models at p<0.01** at the right operating point. It
>   does NOT distinguish them — a single driving arm accrues metres and
>   robot-seconds together, and only an abort or a second parked arm can separate
>   them. Rejecting both is the stronger practical outcome and the weaker
>   scientific one.
> * **THE CONFIGURATION IS NOT THE ONE THAT CRASHED.** This fleet drove circles
>   under direct `cmd_vel` with no agents, no orchestrator, no skills, no
>   actuators and no excavate/haul interactions. The three aborts happened under
>   the full stack. If the hazard depends on something an agent does — a
>   particular velocity profile, a drill or transfer actuator, a robot pinned
>   against terrain under a controller that keeps commanding — this campaign does
>   not cover it. **That is the largest caveat and it is not small.**
> * One robot did hit a genuine stress case and it still did not abort:
>   `scout_01: WHEELS TURNING, BODY NOT MOVING. 7.0 m of wheel travel over 20 s,
>   2.03 m covered (71% slip)` — the D-25 detector firing correctly. scout_01
>   covered 20.9 m against ~950 m for every other robot.
> * Pose extremes stayed on the heightfield: max |x| or |y| over all ten robots
>   **205.245 m** against the 248.062 m half-extent, min z **−14.73 m**.
>   Consistent with the 174.700 m from the earlier instrumented run and with the
>   arithmetic showing a fall cannot reach the assertion's bound in these times.
>
> **Cause still unknown. Still not reproduced. Still not fixed.** What changed is
> that the exposure argument is now made at the right operating point, and the
> instrument to make it exists and is committed.

---

**Original entry:**

**This is the largest unresolved item in the repository and nothing below
identifies its cause.**

**The failure**, three times on 2026-07-30/31, always the same assertion:

    Dbg ODE Heightfield AABB: min = {-248.062, -248.062, -5.5e-14}
                              max = { 248.062,  248.062, 24.0537}
    ODE INTERNAL ERROR 1: assertion "aabbBound >= dMinIntExact && aabbBound < dMaxIntExact"
        failed in collide() [collision_space.cpp:460]
    [ERROR] [gazebo-1]: process has died ... exit code 134   (SIGABRT)

Stack: `SimulationRunner::Step` → `Physics::Update` → dartsim
`WorldForwardStep` → `ConstraintSolver::solve` → `GzOdeCollisionDetector::collide`
→ `dxHashSpace::collide` → `dDebug` → `abort`.

| # | fleet | elapsed | state at abort |
|---|---|---|---|
| 1 | 4/3/3 | ~5 min | scouts 02/03/04 → ERROR *after* the abort (odom froze) |
| 2 | 2/1/1 | ~29 min | the next Gazebo line after `[hauler_01] Arrived at waypoint 0, phase=loading`; 19.01 kg extracted |
| 3 | 2/1/1 | ~21.5 min | hauler ASSIGNED and NAVIGATING; never reached loading; 2.70 kg extracted |

### What is refuted

**The terrain-edge theory — the repository's own — is refuted, twice over.** It
held that a robot drove off the ±248 m heightfield, fell, and its AABB left the
integer range ODE's broadphase converts it into. (a) It rested on a
translation-only model of the odom frame, and `check_drive.sh` measured the frame
to be a full SE(2) (D-33); under the real transform **none** of those targets
leaves the terrain. (b) An instrumented 20-minute run then measured the maximum
|x| or |y| over all 31 entities across **200,027 pose samples** at **174.700 m**
against a 248.062 m edge, and the minimum z at **−14.402 m** against a −14.782 m
global surface floor. Nothing came near leaving the heightfield in any axis.

**Two configuration files asserted that refuted theory as a measured root
cause**, and both have been corrected in their own voice rather than quietly
tidied. `selene_sim/config/world_params.yaml` said the fall "takes Gazebo down
mid-mission … measured by the operator three times"; `orchestrator_params.yaml`
carried the same claim. **Three aborts were measured; a fall was not.** Both now
separate MEASURED from NOT MEASURED, state that the cause is unknown, and keep
the safety margin on its own merits — driving off a finite heightfield is a bad
idea whatever ODE does about it.

**One inference this workstream drew about the mechanism is also refuted, and by
measurement.** An analysis reported `Dbg ODE Heightfield AABB` occurring **0**
times in a healthy 20-minute run at `-v 4`, and concluded the line is emitted only
on the failing path — which would put the heightfield geom *inside* the failing
`collide()`. That count was a **broken grep**: the analyser matched the contiguous
literal `Dbg ODE Heightfield AABB`, and the gz console inserts `] ` plus ANSI
escape sequences between `Dbg` and the message body. Measured directly with
`cat -A` on a healthy, non-aborting run at default verbosity:

    49:[gazebo-1] ^[[1;36mDbg^[[0m ODE Heightfield AABB: min = {-248.062, ...}$
    contiguous literal matches: 0        ANSI-tolerant pattern matches: 1
    line 49 of 530

**It is a load-time print** — line 49 of 530, in a run with no abort. Corroborating
that it is the terrain geom's own AABB rather than anything about the crash: the
printed `max z 24.0537` equals `collision.size_z_m 24.053652` in
`selene_sim/models/lunar_terrain/heightmaps/terrain_datum.json` exactly. **So the
heightfield is not shown to be inside the failing `collide()`**, and any
conclusion resting on that 0 must be withdrawn. *Caveat: the archived crash logs
are no longer on disk, so this rests on the healthy-run measurement, not on
re-grepping the crashes.*

### What the clean runs are and are not worth

Two ten-robot runs on 2026-07-31 completed without an abort:

    run A    615.1 s x 10 =   6151 robot-seconds
    run B   1817.6 s x 10 =  18176 robot-seconds
    TOTAL abort-free      =  24327 robot-seconds, and 1288.8 m of true fleet path

Both at **4/3/3 — the only fleet size with a measured abort time (~5 min)**.
Against a constant-hazard fit of ~1/5040 per robot-second (maximum-likelihood
over the three observed failures at 3000 / 5160 / 6960 robot-seconds),
`exp(−24327/5040) = 0.008`. Rejecting that hazard at p<0.05 needs 15,120
abort-free robot-seconds and at p<0.01 needs 23,209; both are cleared. I
recomputed all four of those numbers here.

**And it still does not identify a cause. Four caveats, all of which matter:**

1. **Four things changed at once** — the world-frame fix, the localisation pose
   source, the depot relocation, and therefore every route the fleet drove.
2. **The hazard is a one-parameter fit to three observations** that nobody in
   this workstream made, on a model nobody has justified.
3. **"Robot-seconds" presumes H3's bodies × time law.** If the hazard is
   per-metre the exposure argument is much weaker: those runs drove 1288.8 m
   against crash runs of ~522 m, ~1400 m and ~1900 m.
4. **An earlier 20-minute clean run at 2/1/1 proved nothing at all** and was
   nearly quoted as if it did — it was *shorter* than both 2/1/1 runs that
   aborted (21.5 and 29 min), with a 37% survival probability under the same
   hazard.

### The lattice corollary, which is independent of all of this

The ODE heightfield half-extent is **500/129 × 128 / 2 = 248.0620155 m** exactly,
which reproduces the abort log's printed digits — so the collision lattice pitch
is **3.87597 m**, not the 500/128 = 3.90625 m that `lunar_terrain/model.sdf`
states as "3.91 m cells" and that other files assume. I re-derived this here.
`world_params.yaml` and `orchestrator_params.yaml` now record the correct
figures; `model.sdf` still states the wrong one, and every "half a collision
cell" constant elsewhere in the repository is stated against the wrong lattice.

### Where this stands

**Cause unknown. Not reproduced under instrumentation. Not fixed.** What has
changed is that the next one will be **loud**: D-26 makes `ros2 launch` die with
the simulator instead of running on over dead physics. The recommended next
experiment is the one the exposure argument names — hold a 4/3/3 fleet
**driving** (repeated survey/excavate cycles rather than exiting on first
deposit) and instrument fleet-metres as a first-class number, so that a per-metre
hazard can be distinguished from a per-second one.

---

## D-38 — the dashboard lockfile made CI's newest job red on its first-ever run — CLOSED 2026-08-01, FIXED AND VERIFIED IN CI

**Found by running a lane nobody had ever run.** `npm ci` could not install the
dashboard **at all**:

    npm error `npm ci` can only install packages when your package.json and
    npm error package-lock.json ... are in sync.
    npm error Invalid: lock file's typescript@6.0.2 does not satisfy typescript@4.9.5

`package.json` never declared `typescript`, and there is no TypeScript source in
this project — every dashboard file is `.js` or `.jsx`. It is in the tree only
because `react-scripts` pulls `fork-ts-checker-webpack-plugin`, whose peer range
is the very loose `typescript >= 2.7`. npm resolved that to whatever was newest
when the lock was written — **6.0.2**, which satisfies `>= 2.7` and violates
`react-scripts@5.0.1`'s own peer range of `^3.2.1 || ^4`. **The lock has been
internally inconsistent since `1aec25e`**; `npm install` tolerates it and
`npm ci` does not, so a developer's machine and CI disagree by construction.

**Nothing caught it because nothing had ever run it.** The `dashboard-tests` job
was added on 2026-07-31 with the 39-test Jest suite, and `SELENE CI` triggers
only on push to `main`/`develop`, PR to `main`, or `workflow_dispatch`
(`.github/workflows/ci.yaml:4-14`) — so on `phase5-hardening` the pipeline had
not run since `1200327`, **before that job existed**. Dispatched on this branch
as run **30677902046** (`ff80ed1`): `Install dependencies` **failed**, and the
lint, test and build steps it gates were all skipped.

**This is a job that had never fired testing its own configuration rather than
the thing it guards** — the same shape as every other entry in this register
where an absence of evidence had been reading as a green line.

**Fixed** by declaring the constraint instead of leaving it to transitive
resolution: `typescript: ^4.9.5` in `devDependencies`
(`selene_dashboard/package.json`), lock regenerated. The regeneration is
surgical — **8 insertions, 28 deletions** — and moves no other package:
`react-scripts` stays 5.0.1, `react` 18.3.1, `three` 0.160.1, `roslib` 1.4.1.

**MEASURED under node 18.20.8 / npm 10.8.2**, the same node major CI uses, by
running all four CI steps rather than reasoning about them: `npm ci` added 1319
packages, exit 0; `typescript` resolved 4.9.5; `npx eslint --ext .js,.jsx src`
exit 0; `CI=true npx react-scripts test` 39 passed; `react-scripts build`
compiled.

**Verified in CI. Run `30678000922` at `c4548ce` went 8/8 green.** Read from the
GitHub Actions API on this pass: `conclusion: success`, all eight jobs green
including `Dashboard lint, test and build (no ROS)`.

> **One claim about that run needs correcting, and the correction is smaller
> than the claim.** It was described as "the first fully green `SELENE CI` run
> this branch has ever had". **That is not true**: run `30586258889` at
> `1200327` (2026-07-30) also concluded `success`. It ran **four jobs** —
> terrain-datum, e2e-integration, shell-lint, build-and-test — because
> `gate-coverage`, `cross-package-tests` and `dashboard-tests` did not exist
> yet; they arrived with `30403a8`. **The accurate statement is that
> `30678000922` is the first green run of the pipeline as it now stands**, and
> that `30678095310` at `d390315` is the first green run of the nine-job pipeline
> (`gate-lane-tests` is the ninth; `cross-package-tests` is a two-way pytest
> matrix, which is why eight jobs come from seven `jobs:` keys).

**SELENE CI is now green on this branch at every commit in this session**, read
from the API by run id: `30678000922` (`c4548ce`, 8/8), `30678095310`
(`d390315`, 9/9), `30681543994` (`7727ba8`, 9/9) and `30685883138` (`9c1a4d7`,
9/9), including the Humble `colcon build` / `colcon test` lane. The separate
**Simulation gates** workflow — `check_terrain.sh` and `check_drive.sh`, which
run real Gazebo sessions — also concluded `success` on push at `7727ba8`
(`30681538436`) and `9c1a4d7` (`30685878027`).

---

## D-39 — two world files were invalid XML, and the check that noticed printed a green line with no value — CLOSED 2026-08-01

`selene_sim/worlds/lunar_psr.sdf` and
`selene_sim/models/depot_marker/model.sdf` each contained a literal `--` inside
an XML comment, which **XML 1.0 §2.5 forbids**. Introduced by `30403a8`, in
prose added to explain D-23.

**Gazebo never cared.** libsdformat is lenient and parses straight past it,
which is why three live runs and two gate runs never saw it. Strict parsers do
care, and the repository has one.

**The visible half** was `scripts/check_env.sh` exiting 1 with a blocking
`lunar_psr.sdf is not valid XML`.

**The dangerous half is the one worth recording.** The very next check printed

    [ OK ]   world-scope <gravity> =

against an **empty value**. `check_env.sh:170-183` runs the strict parse
(`ET.parse`) for the validity line and then extracts `<gravity>` in a **second**
`python3` heredoc, also with `2>/dev/null`; when that parse fails, `$GRAV` is
left empty, and empty is not the sentinel `MISSING` the failure branch tests for.
So the check that exists to confirm the world runs at lunar gravity printed OK
**while measuring nothing**. That is the same shape as D-29's vacuous check 10 —
an absence of evidence rendered as a green line — and here it was sitting one
line below a failure loud enough that nobody read further.

**Fixed** by replacing `--` with `-` inside the comments only: three prose edits
(two in `depot_marker/model.sdf`, one in `lunar_psr.sdf`), no semantic content
touched. Verified on this pass: both files parse under `xml.dom.minidom`.
`check_env.sh` now reports **19 ok, 0 failed**, and
`world-scope <gravity> = 0 0 -1.62`.

**Not fixed, and named**: the gravity check still cannot fail closed on a parse
error, because the empty string and the sentinel are different values and only
one of them is tested. It happens to be correct now because the input is valid.

---

## D-40 — the Resource Knowledge Map's animation loop was never started — CLOSED 2026-08-01, DEMONSTRATED IN A BROWSER AGAINST A TEST DOUBLE

**Reported by the operator** as "the knowledge map in the dashboard doesn't seem
to be working correctly", and the cause is simpler and more fatal than anything
this register predicted.

**Was**: `ResourceGraph.jsx` took an empty-state early return whenever
`readings.length === 0` — **which is the state on every page load**, since the
reducer initialises `resourceReadings: []` — and that branch rendered **no
`<canvas>` and no container ref**. All three canvas effects therefore ran against
null refs and bailed: the sizing / `ResizeObserver` effect, the
`requestAnimationFrame` loop (dependency array `[]`), and the wheel listener.
**None of those dependency arrays ever changed again**, so when readings finally
arrived nothing re-ran: the loop was never scheduled, `updateCanvasSize` never
ran, and the canvas kept its default **300 × 150** backing store underneath a
header, legend and stats panel showing real numbers over a black rectangle.

The same defect fired a second way: a rosbridge reconnect dispatches `RESET`,
readings go back to `[]`, the canvas unmounts, and when readings resume React
mounts a **new** canvas while the loop keeps drawing into the detached one it
captured on the first commit.

**`FleetMap.jsx` has the identical loop and no empty-state early return, which
is exactly why the fleet map worked and its sibling did not.** One component
away, one `if` apart, and no test in the project could see the difference.

Three further defects in the same file, all fixed: the render-time
`edgesRef.current = edges` write that could dereference an unbuilt node inside
the rAF callback and **kill the loop permanently** (the trailing
`requestAnimationFrame` never runs after a throw); `slice(0, negative)` on a
reading-count shrink, which retained stale nodes across a reconnect; and the
index scramble once the 500-reading cap is reached, after which every node
silently adopts a different reading while keeping its settled position.

**Fixed** by replacing the plain refs with **state-backed callback refs**
(`ResourceGraph.jsx:405-406`), so every effect that touches the canvas lists the
element it touches and re-runs when that element actually mounts. The reasoning
is written into the file: the invariant is "the loop is attached to the canvas
that is in the DOM", and `readings.length > 0` in the deps would fix the
empty-mount case while leaving the canvas-**replacement** case broken, because it
keys the loop on something merely correlated with the invariant. The empty state
still renders no canvas — that is now correct rather than fatal.

**MEASURED IN CHROME, 2026-08-01, against a rosbridge TEST DOUBLE publishing
real `ResourceMapUpdate` shapes — not against the real stack** — with the view
opened **before any reading had arrived**, which is the operator's path and the
only diagnostic one, because opening the view *after* readings exist has always
worked even with the defect present:

    view opened empty                 0 canvases, empty state
    first reading arrives             canvas mounts after 822 ms
    canvas backing store              1240 x 576   (NOT the 300x150 default)
    frames scheduled in 1200 ms       144
    disconnect                        readings retained, canvas stays
    reconnect -> RESET                back to 0 canvases, empty
    readings resume                   remounts after 3127 ms, same backing
                                      store, same frame rate

**The 1240 × 576 is the load-bearing number**: it proves `updateCanvasSize` ran
*after* mount, which the old code could never do. 144 frames in 1200 ms is the
30 fps interval the file asks for, doubled by rAF's own cadence and throttled in
the draw — it establishes that the loop is running, not that any particular
frame rate is met.

**What this does not cover.** The test double proves **nothing about ROS, DDS,
QoS or the real orchestrator** — only what the browser does when messages of
that shape arrive. Colour fidelity, legibility and frame timing were not
assessed, and open item 18 (this view has no confidence channel at all) is
untouched.

---

## D-41 — `gz sim -s` segfaults in the depth-camera render path on a host with no GL context — WORKED AROUND 2026-08-01, NOT FIXED

Found while running the D-28 slope campaign. A server-only `gz sim -s` died
partway through the first robot's trials, and every trial after it recorded
"no pose after spawn":

    Sensors::CreateSensor -> DepthCameraSensor::SetScene
      -> Ogre2DepthCamera::CreateDepthTexture
      -> CompositorManager2::addWorkspace
      -> Ogre::HlmsDatablock::_unlinkRenderable -> SIGSEGV

`gz sim -s` still loads the sensors system, and all three robot models declare a
`depth_camera`. Creating its depth texture needs a real GL context; under WSL2's
software rasteriser Ogre2 dies.

**THIS IS NOT D-37 AND MUST NOT BE CONFLATED WITH IT.** D-37 **aborts** in
`dxHashSpace::collide` on an **ODE assertion**, with **physics on the stack**.
This **segfaults** in `Ogre::HlmsDatablock::_unlinkRenderable`, in a texture
allocation, with **no physics on the stack at all**. Different signal, different
subsystem, different trigger. Treating them as one failure would lose both.

**Worked around, not fixed**: the campaign spawns a copy of each model with
every `<sensor>` element removed. Safe for what it measures — the sensors are
massless, declare no `<collision>`, and neither `sensors/depth` nor `sensors/imu`
has any subscriber repo-wide (this register's own open item 11) — so removing
them cannot change wheel-terrain contact, mass, inertia or friction. **The
substitution is disclosed in the campaign's own printed limitations and in the
committed JSON artefact** (`limitations[0]`), and the stripped SDFs are kept in
the work directory so the substitution can be diffed. The artefact's own wording
is the right standard: *"the vehicle measured is not byte-identical to the
vehicle the mission flies."*

**THE NEAR-MISS IS THE REASON THIS ENTRY EXISTS.** Four trials recorded
`no_pose` at **10° and 15°** — which is **indistinguishable from a vehicle that
cannot climb those grades.** Taken at face value they would have set
`max_traversable_slope_deg` far below the true value and refused routes the
fleet drives today. Only the script's own distinction between an **apparatus**
failure and a **measured** failure caught it — the same discipline as D-34's
"a SKIP is not a PASS", arriving from the opposite direction. Note that the
committed verdict still carries `monotonic: false` for excavator and hauler
ascent, so **the apparatus is not established to have explained every anomalous
trial**; it explains the four it names.

---

## D-42 — a scout reported "Battery critical (0.0%)" 6.15 s after startup, three times — CLOSED 2026-08-01, ROOT-CAUSED, REPRODUCED ON DEMAND, FIXED, AND THE FIX DEMONSTRATED

> **STATUS AMENDED 2026-08-01 (later the same day).** Everything below the
> horizontal rule was written while the cause was unknown and is kept verbatim,
> because the entry's own instruction — *"NO CAUSE IS PROPOSED HERE. The
> temptation to write one down is exactly what D-37's refuted terrain-edge
> theory is a monument to"* — is the reason the answer came out right. The cause
> is now known, it was found by doing what the entry asked for (a live probe of
> `/scout_02/battery_state` and its **rate, publisher count and provenance**),
> and none of the four hypotheses the entry ruled out needed reinstating.
>
> ### THE CAUSE: a second `battery_node` for the same robot, on a shared ROS domain
>
> **Every link below was measured on the operator's box on 2026-08-01. None is
> inferred.**
>
> 1. **`ros2 launch` does not take its children with it.** Signalling the launch
>    left a COMPLETE second SELENE stack alive — `gz sim`, four `battery_node`s,
>    four `agent_node`s, four `world_odometry_node`s, an orchestrator and
>    rosbridge. A second launch then ran alongside all of it: **50 nodes, every
>    SELENE node duplicated**, and `rosbridge` logging
>    `Unable to start server: [Errno 98] Address already in use` because
>    `GZ_PARTITION` isolates Gazebo transport and **nothing isolates TCP or DDS**.
>    `ROS_DOMAIN_ID` is set nowhere in this repository except
>    `docker/docker-compose.yaml`.
> 2. **An orphaned `battery_node` drains to exactly 0.0 and stays there.**
>    `_cmd_vel_callback` assigns `current_speed` on message and **nothing decays
>    it**. With the simulator gone no further `cmd_vel` arrives, so the node keeps
>    integrating locomotion draw at the last commanded speed forever. Measured on
>    an orphaned `battery_scout_02`: **85.0 W**, i.e. 1.417 % of 50 Wh per 30 s,
>    steady for 28.5 minutes, at which point `max(0.0, ...)` clamped it to
>    **exactly 0.0** — watched sample by sample, and it held 0.0 for the whole
>    120 s observation afterwards.
> 3. **That is the scout_02-only asymmetry.** In the same measurement
>    `excavator_01` and `hauler_01` sat pinned at **exactly 1.0** for the entire
>    run. Neither had ever left IDLE, so neither had ever been sent a `cmd_vel`,
>    so their latched speed was 0 — and both spawn outside the PSR disc, where
>    the solar branch is live. **Only robots that were moving when the simulator
>    died drain.** The register's "one out of four is a legal subset but is not
>    predicted" objection is answered: which robots go flat is decided by which
>    ones were driving, not by chance.
> 4. **The HAL cannot tell the two publishers apart, and neither can anything
>    else.** `GazeboBattery._cb` overwrites its cache with whichever message
>    arrived last; `sensor_msgs/BatteryState` carries no producer identity, and
>    `battery_node` leaves `header.frame_id`, `location` and `serial_number`
>    empty. On the wire the interleaved stream is indistinguishable from one node
>    behaving erratically.
>
> **THE 0.1% WAS THE FINGERPRINT, AND IT IDENTIFIED THE PUBLISHER'S MODEL.**
> For a stationary scout outside a PSR zone the net rate is exactly
> `solar 40 W − idle 10 W = 30 W` into a 50 Wh cell, so from 0 Wh the charge
> fraction is `t/6000`; `f"{x:.1%}"` prints `"0.1%"` for `t` in **[3.0 s, 9.0 s]**,
> and the entry's own "~7.5 s after reaching RECHARGING" lands mid-window at
> 0.00125. The recharge pad (−30, −100) is **86.0 m** from the PSR centre against
> a 60 m radius, so the charging branch is live there. That rise cannot come from
> a default-constructed cache (1.0), from NaN (`min(50.0, nan)` is 50.0, verified),
> or from a frozen cache (a frozen value does not move). It can only come from a
> live scout `BatteryNode` at exactly 0 Wh — which is what an orphan is.
>
> ### REPRODUCED ON DEMAND, then the fix demonstrated against it
>
> A stack was left running until its `battery_scout_01` and `battery_scout_02`
> reached exactly 0.0 (28.5 minutes, no synthetic input, the repository's own
> node doing its own arithmetic). A fresh, healthy 2/1/1 stack was then launched
> on the same domain — which is what an operator does after an incomplete
> teardown. Publisher count on `/scout_02/battery_state` went **1 → 2**:
>
>     [agent_scout_02] Battery critical (0.0%), returning to recharge
>     [agent_scout_02] BIDDING --(ENERGY_CRITICAL)--> RETURNING
>     [agent_scout_01] Battery critical (0.0%), returning to recharge
>     [agent_scout_01] IDLE --(ENERGY_CRITICAL)--> RETURNING
>     ... later:  Battery critical (0.3%) ...  Battery critical (0.4%)
>
> **That is D-42's log signature, on demand, including the small non-zero
> percentages the original entry could not explain.** The probe measured
> `max |agent − sim| = 0.97987` — the agent reading 0.00000 at the instant the
> healthy publisher read 0.97987.
>
> The workspace was then rebuilt with the fixes below and **the identical
> experiment re-run under worse contamination (3 publishers, not 2)**:
>
> | | pre-fix | post-fix |
> |---|---|---|
> | `Battery critical` firings | **4** | **0** |
> | robots driven off-mission | both scouts | none |
> | diagnostics emitted | none | **6 CRITICAL FleetAlerts**, naming topic, count, likely cause and this entry |
>
> ### WHAT WAS FIXED
>
> * **`BatteryState.is_valid`** (`selene_hal/data_types.py`). The HAL could not
>   say "I have never received a reading"; it reported a confident 100%.
>   Defaults **True**, exactly like `SensorReading.is_valid`, with the fail-safe
>   at the one construction site that means "I have nothing".
> * **The five-second wall-clock grace is deleted**, and this is the finding that
>   should outlive the bug. Comments at four sites asserted the HAL "reports a
>   phantom 0%" before its first message. **That mechanism has never existed in
>   this repository.** `GazeboBattery.__init__` has built its cache from the RCDL
>   capacity since the class was written (checked at `a17d6a4`, `5802925`,
>   `4e20c20`, `b736b62`, `30403a8`); `charge_fraction` has defaulted to 1.0
>   since the dataclass was defined; `StubBattery` does the same. The comment
>   entered at **`940f6f7`**, whose message asserts "a cold-boot race on battery
>   topic" and **names no observation**. The most likely reading is that its
>   author hit *this same foreign-publisher problem three months earlier* and
>   mis-attributed it to the HAL. A tick counter is inert against a persistent
>   foreign publisher: it delays the first firing and nothing else — which is
>   exactly the shape of the D-42 log, and why the robot fired 1.15 s past it.
> * **`AgentNode._check_battery_health`** reports, at CRITICAL, on the operator's
>   channel: more than one publisher, no reading ever, readings stopped.
> * **The energy rule is SUSPENDED on an unattributable channel**, and that is a
>   REFUSAL, not a filter. Nothing is discarded, smoothed or median-ed; every
>   reading still reaches `EnergyManager`, `RobotState.battery_level` and the
>   dashboard. What stops is the automatic action. The trade-off is stated in the
>   code: a robot whose battery really is flat during contamination will not take
>   itself to the charger. That is accepted, because the reading that would have
>   triggered it is by construction not known to be about that robot.
> * **`selene_sim/battery_model.py`** — the energy arithmetic extracted from
>   behind `battery_node`'s module-level `import rclpy`, which is why it had
>   **zero tests of any kind**. 14 tests now pin the clamp's exact 0.0, the
>   latch, the 85.0 W drain reproduced from the shipped constants, the 1.0/1.0
>   asymmetry, and the bound that let this entry rule the healthy node out.
> * **`scripts/validate_phase5.sh`** refuses to start when 9090 or 3000 is
>   already held (exit 3 — "the gate could not start"), and warns, naming the
>   processes, when SELENE nodes are already running.
> * **Check 11 no longer commands a robot it can see cannot obey** — see D-10.
>
> ### WHAT IS STILL NOT ESTABLISHED, and it is one thing
>
> **That this is what happened on 2026-08-01 is an inference, not a
> measurement.** Those processes are gone and no publisher census was taken at
> the time. What is measured is that the mechanism exists, that it produces this
> exact signature on demand, that the environment permits it with no defence at
> any layer, and that open item 22(a) independently records a duplicate stack
> live on this box **on that same day**. The 0.1 % fingerprint is the strongest
> single piece, because only a live scout `BatteryNode` at 0 Wh produces it.
> **No alternative mechanism has been found that reproduces all three data
> points, and four were tested adversarially and refuted.**

---

**Original entry, 2026-08-01, written while the cause was unknown:**

**This is the second entry in this register whose cause is unknown, and it is
the one that cost the 2026-08-01 gate run its green.**

**The observation**, from `/tmp/selene_unified_launch.log` on the 2026-08-01
run, verbatim and complete — three firings, all `scout_02`, none on any other
robot:

    [1785562221.112635] [agent_scout_02] Battery critical (0.0%), returning to recharge
    [1785562221.112991] [agent_scout_02] IDLE --(ENERGY_CRITICAL)--> RETURNING
    [1785562298.216274] [agent_scout_02] Battery critical (0.0%), returning to recharge
    [1785562298.216705] [agent_scout_02] NAVIGATING --(ENERGY_CRITICAL)--> RETURNING
    [1785562309.312948] [agent_scout_02] Battery critical (0.1%), returning to recharge
    [1785562309.313518] [agent_scout_02] IDLE --(ENERGY_CRITICAL)--> RETURNING

`agent_scout_02` started at `1785562214.960339`, so the first firing is
**6.152 s** after the agent came up. `battery_scout_02` started at
`1785562202.610303` announcing `50.0 Wh capacity`, so it is **18.50 s** after
the battery node came up.

**How it took check 11 down.** The operator's `send_to_location` was accepted and
the FSM went `RETURNING --(OPERATOR_GOTO)--> NAVIGATING` at `298.210547`. **Six
milliseconds later** — `298.216705` — the energy-critical rule fired and sent it
straight back to the pad. The planned path therefore ended **0.71 m from the
recharge pad** at (−29.50, −99.50) and **4.54 m from the commanded target**, and
check 11 FAILed. **Neither the override path nor the FSM did anything wrong**:
both transitions are correct, in the right order, on the inputs they were given.

### What has been ruled out, by reading and arithmetic

* **The sim node cannot report 0%.** `battery_node` sets
  `remaining_wh = capacity_wh` at construction and drains
  `power_w * dt / 3600`, publishing `msg.percentage = remaining_wh /
  capacity_wh` (`selene_sim/selene_sim/battery_node.py:84, :171-194`). A scout's
  largest modelled draw is `idle 10 W + 150 W/(m/s) × 0.5 m/s × slope_factor`,
  and `slope_factor` is capped by `1 + 2 sin(angle)` — at most about 235 W, with
  `actuator_draw_w` zero for a scout (200 W is drill power, excavator only). At
  235 W for the full 18.50 s since the node started, that is **1.21 Wh of 50, or
  2.4%.** The node's own model cannot reach 0.
* **It is NOT the D-31 fabricated-default pattern.** `GazeboBattery.__init__`
  constructs its cache **full** —
  `BatteryState(capacity_wh=descriptor.battery.capacity,
  remaining_wh=descriptor.battery.capacity)` (`gazebo_hal.py:570-573`) — and
  `BatteryState.charge_fraction` **defaults to 1.0**
  (`selene_hal/selene_hal/data_types.py:115`). `EnergyManager` reads
  `charge_fraction` directly (`energy_manager.py:92-102`). So a HAL that has
  received **no** message reports **100%**, not 0%. `StubBattery` does the same.
* **The topic has exactly one publisher and one subscriber.**
  `battery_node.py:111` publishes `/<rid>/battery_state`; `gazebo_hal.py:574`
  subscribes. Nothing else in the tree touches it.
* **A fleet-wide default would not produce this.** Four robots ran; only
  `scout_02` was affected, and `scout_01` — same type, same capacity, same
  launch — never fired once.

### What remains, and it is the whole of it

**Something delivered `percentage = 0.0` to that agent, and nothing above
explains what.** The third firing reports **0.1%**, about 7.5 s after the robot
reached `RECHARGING` — which is consistent with a battery that really is near
empty and really is charging slowly, and is *not* consistent with a stale or
default-constructed cache. **That is an observation, not a mechanism.**

**This needs a live probe of `/scout_02/battery_state`** — its rate, its
`percentage` field, and whether the value the HAL caches matches what the node
publishes — on a run that reproduces it. **NO CAUSE IS PROPOSED HERE.** The
temptation to write one down is exactly what D-37's refuted terrain-edge theory
is a monument to.

### One thing this exposes regardless of cause

`agent_node` has a **5 s startup grace** on the energy-critical check
(`agent_node.py:374`, `:412-415`), and its own comment says why it exists:
*"skip during startup grace period so DDS can deliver the first real battery
reading (avoids 0% phantom)"*, repeated at `:1049` and in
`recharge_policy.py:188`. **`scout_02` fired at 6.15 s — just past the grace.**
So the grace is a band-aid over something real, and it is 1.15 s too short for
whatever this is.

**And the mechanism those three comments assert does not exist in the code as it
stands.** They claim "the HAL reports a phantom 0%" before the first message;
both HAL battery implementations report a **full** battery before the first
message, as above. Either the comments are stale — describing a HAL that has
since changed — or there is a path to 0% that nobody has named. **Whichever it
is, three comments in two files currently document a mechanism this repository
cannot demonstrate**, and that is the same defect class as the two configuration
files D-37 had to correct.

---

## D-43 — the path follower orbited its waypoints, and it cost the mission the whole ISRU chain — CLOSED 2026-08-01, ROOT-CAUSED, MUTATION-TESTED, DEMONSTRATED LIVE

**This is the cause of open item 22(b), and it was not where anyone was
looking.** The fleet was not slow because of terrain, traction, slip, latency or
battery. `PathFollower` could not retire a waypoint it had stopped steering
toward, so on any sharp corner it circled that waypoint until something else
timed out.

### THE INVARIANT THAT WAS VIOLATED

`PathFollower._find_lookahead` (`navigator.py:1014-1022`) scans forward **from
`_target_idx`** and returns the first waypoint at or beyond
`lookahead_distance` — so it stops steering toward any waypoint closer than
**2.0 m**. The retirement loop in `update` advanced `_target_idx` only when the
robot was within `waypoint_tolerance` — **1.0 m**.

Between 1.0 m and 2.0 m sits a band in which the follower has stopped steering
toward a waypoint but has not retired it. **On a straight path that band is
harmless**: the robot crosses it anyway and closes to 1 m. **On a reversal it is
fatal**: the follower curves away toward a point 2 m further along, never closes
to 1 m, `_target_idx` never advances, the next scan starts from the same stale
index and re-acquires the same waypoint.

**THE FOLLOWER CODE IS OLDER THAN THE SYMPTOM.** What changed is the paths.
Commit `9c1a4d7` closed D-28 by enforcing the slope limit **per step**, which
turned A\* routes across the crater wall from a couple of waypoints with no turns
into long chains with reversals of up to **135°** — precisely the geometry that
makes a 2 m lookahead miss a 1 m tolerance. D-28 did not introduce this bug; it
introduced the routes that trip it. That is the second time in this register
that a correct fix has exposed a latent defect one layer down.

### THREE INDEPENDENT METHODS AGREE ON THE NUMBER

| method | net progress |
|---|---|
| offline, **real** planner + **real** follower, **ideal frictionless plant** | 0.048 m/s |
| the running system, 4 robots, 16 minutes | **0.044 m/s** |

The offline reproduction drove **599.8 m** and swept **68,370° of yaw** without
reaching a goal in 1200 s. **An ideal plant cannot slip**, so terrain, traction
and latency are all excluded as necessary conditions.

### THE FIX IS THE INVARIANT, NOT A RETUNED CONSTANT

    retire_radius = max(self._wp_tol, self._lookahead)

Whatever the lookahead scan declines to steer to is retired, by construction.
Raising `waypoint_tolerance` in `nav_params.yaml` would have papered over it and
would also have loosened the **arrival** test, which is a different question and
stays tight — `test_arrival_tolerance_is_still_tight` asserts the goal test still
refuses at 1.5 m against a 1.0 m tolerance, so the fix cannot be a widened
threshold in disguise.

**MUTATION-TESTED BEFORE COMMIT**, which is this register's own standard: with
the retirement radius reverted to `self._wp_tol`, **10 of the 14 new tests fail**
— and the 30° corner and the straight path still pass, because the bug does not
bite on those geometries. The tests fail for the reason the mechanism predicts,
not merely because something changed.

### DEMONSTRATED LIVE, SAME SCRIPT BOTH SIDES

Two 16-minute 2/1/1 runs, one clean stack each, identical invocation:

| | pre-fix | post-fix |
|---|---|---|
| survey waypoints COMPLETED | **6 of 10** | **10 of 10** |
| first reading reaches the map | t = **802.5 s** | t = **240.4 s** |
| `map_update` messages | 4 | **9** |
| `total_observations` | 319 | **716** |
| path / net ratio, scout_01 | **5.29×** | **2.59×** |
| scout_01 FSM transitions | 17 | **31** |
| **`(excavate)` auctions started** | **0** | **1** |
| **excavator_01 FSM transitions** | **1** | **4** |
| **excavator_01 distance driven** | **0 m** | **48.2 m** |

**THE EXCAVATOR MOVED.** Pre-fix, 70 auctions ran in 16 minutes and every single
one was `(prospect)`; the excavator and hauler had nothing to bid on because
`HTNPlanner.check_and_advance` resolves `select_site` only when **every** survey
task is COMPLETED (`htn_planner.py:313-322`) — a conjunction, with no
concentration, certainty or reading-count threshold anywhere in the chain. Six of
ten made it false. Post-fix all ten complete, the conjunction resolves, and an
excavate task exists for the first time in these runs.

### WHAT THIS ENTRY DOES NOT CLAIM

* **Item 22(b) is not thereby discharged.** The fleet now surveys all ten
  waypoints in about four minutes of reading time, which is what (b) needed, but
  the side-by-side has not been re-taken against a surveyed map. That is the
  remaining work.
* **The path/net ratio is still 2.59×**, against the register's 1.85×
  switchback estimate. Better than 5.29× and not yet explained.
* **Five survey tasks were still ABANDONED** (`no bids in 5 consecutive
  auctions`) before being woken by `idle_arrivals` and completed. The wake
  mechanism works; the churn is real and unmeasured.
* **`Dropping map update ... unusable sensor uncertainty inf` fired once in each
  run**, at (-104.2, -152.7) and (-94.4, -163.7). The guard is behaving
  correctly — a scout more than the spectrometer's 10 m `max_detection_range`
  from every deposit reads `ice=0.000 +/-inf` and the reading is refused rather
  than fusing a fabricated confidence. **But it means a survey waypoint sited
  more than 10 m from any deposit contributes NOTHING to the map**, and nothing
  in the survey planner knows that.

---

## FR-MAP-3 - adaptive survey never ran - CLOSED 2026-07-30

Not a Phase 5 deviation: FR-MAP-3 is P0 **Phase 4** scope
(`docs/PRD.md:434-442`), and Phase 4 was recorded as complete. It is listed here
because SC-3 is a Phase 6 acceptance criterion and the gap was found during this
work.

`AdaptiveSurveyPlanner` shipped with 8 green unit tests and zero production call
sites -- `self._adaptive_survey` appeared exactly once in `orchestrator_node.py`,
the assignment that created it. What ran was a fixed hex lattice of 10 points
computed once at decomposition, before any reading existed.

**Wiring it up alone would not have worked.** At the shipped defaults
`min_spacing` (8.0 m) exceeds `ResourceMap._footprint_radius` (5.0 m), so no
admissible candidate has ever been observed -- and `_get_neighbor_signal` probed
at the map *resolution*, 1.0 m, sampling points 7-9 m from the nearest reading,
outside every footprint. Measured over a full survey: `max(signal) == 0.0` on
every one of 10 selections across all ~360-434 candidates, with the variance
term identically `prior_variance` for the same reason. Both terms constant, so
the score collapsed to pure nearest-neighbour. The 8 existing tests passed only
because they use `min_spacing` of 3.0 or 5.0, at or below the footprint radius.

Now: PENDING survey targets are re-scored on a timer at
`adaptive_survey_replan_rate`, with the lattice seeding the first two waypoints;
committed targets (AUCTIONING / ASSIGNED / IN_PROGRESS) are never rewritten;
termination is structural because the function cannot create a task.

SC-3 measured over the real deposit field, deterministic:

    static    first half 2.21 -> second half 3.40 wt%,  60% of second half >=4
    adaptive  first half 3.86 -> second half 5.34 wt%,  80%

1.57x the second-half mean, with waypoints landing 5.0 m from deposit centres at
7.33 wt%. Live on ROS 2 Jazzy the replan fires and logs its re-targets.

> ### SUPERSEDED 2026-07-31: the SC-3 figures were measured in the wrong frame
>
> **The four numbers above, and the 1.57x, are withdrawn as evidence about the
> physical deposit field**, for exactly the reason D-08's hot-cell figure is
> withdrawn: readings were indexed in each robot's dead-reckoned odom frame, and
> `scripts/check_drive.sh` then measured that frame to be a **full SE(2)** — a
> ~133° rotation, not the translation the repository had assumed. The comparison
> is still internally valid (the same field, the same seed, adaptive against
> static, in one consistent frame), so it remains real evidence that **the
> adaptive planner beats the lattice**. It is not evidence about where the ice
> is. The frame is fixed — see **D-33** — and SC-3 **needs re-measuring in world
> coordinates**. It has not been.
>
> **The paragraph this note replaces used to end "the region sampled is not where
> the robot physically is." That is no longer true**, and the change is the point
> of D-33.
>
> **What was newly observed live on 2026-07-31**, in the instrumented run, is the
> planner doing its job in the field for the first time:
>
>     FR-MAP-3 adaptive survey: 6 pending waypoint(s) re-targeted
>     (peak 4.08 wt%, 162 readings, ref (-96.9, -147.8));
>     survey_79040211 (-115.0, -135.7) -> (-100.0, -145.0)
>
> Six pending targets re-scored against 162 real readings and moved. That is the
> mechanism this entry was opened for, running on a fleet rather than in a
> harness — and it is a **qualitative** observation, not a repeat of SC-3.

---

## Open items carried forward

Closing D-01..D-06 and D-10 deliberately did **not** close these, and each is
recorded here so the closure cannot be read as covering it.

Items 1-8 predate that work. **Items 9 and 10 were introduced by it** — both are
small consequences of the new task-event ring and the new constrained auction,
both are cosmetic rather than behavioural, and both are named rather than
quietly carried. Items 11-14 are pre-existing defects that the work surfaced
without fixing. **Items 15-18 were added 2026-07-31** by the adversarial review
D-01 and D-02 never received; they are the minor half of its findings, the
substantial half being D-15..D-18. The larger things this work introduced or
discovered have their own numbers: D-11 through D-18.

**Revised on the evening of 2026-07-31.** Items **2 and 5 are closed** (the
dead-reckoned odom frame, by D-33; no JavaScript test runner, by a 39-test Jest
suite), **item 7 is superseded by D-32**, and **items 19-22 are new**. Item 1
(`use_sim_time`) was re-checked on this pass and is **unchanged and still true**:
`use_sim_time` has zero code occurrences, and `/clock`, `gz.msgs.Clock` and
`rosgraph_msgs` have zero occurrences of any kind in the tree. Everything in this
system still runs on wall clock.

**Revised again 2026-08-01.** **Item 22 stands unchanged and is now the oldest
untouched gap in this register** — RViz2 has still never been started. Item 14
is partly discharged and partly worse: `_publish_assignment_msg` still has no
caller, and the same pattern was found twice more this session (D-31's
`get_robot_distance`, and `hazard_penalty_weight` / `_hazard_w`, both deleted
rather than defaulted). **Items 23-27 are new**, and four of the five are limits
the slope campaign and the browser session deliberately did not reach.

1. **`use_sim_time` — DEFERRED, deliberately.** It is still set by nothing: no
   node declares it, no launch file passes it, and `/clock`, `gz.msgs.Clock` and
   `rosgraph_msgs` have zero occurrences (the only hits for the name anywhere
   are comments saying exactly this). Making it real needs three things, and
   doing fewer than all three is strictly worse than doing none: (a) a global
   `parameter_bridge` entry for `/clock`; (b) `use_sim_time:=True` on every node
   that times anything — every agent, the orchestrator, every `selene_sim` node,
   rosbridge, rviz2; (c) replacing **every** `time.monotonic()` / `time.time()`
   with node-clock reads. Without (c), heartbeat and auction timeouts stay on
   wall clock while everything else moves to sim time, and at the 0.5x
   real-time factor NFR-1.5 permits, a 10 s heartbeat timeout becomes 5 s of sim
   time and healthy robots are marked OFFLINE. `MissionProgress.elapsed_sim_time`
   keeps its name — renaming a published field breaks the dashboard and PRD
   MSG-7 — and now carries a comment saying it is wall clock.
   **This analysis was not reproduced**; it is read out of the cited call sites
   together with rclpy's documented sim-time semantics.
2. ~~**The dead-reckoned odom frame** (D-08's open item).~~ **CLOSED
   2026-07-31 — D-33** for the frame and **D-24** for the estimate. The
   transform is applied once in `world_odometry_node`, every consumer reads
   `odom_world`, and the pose behind it is now the simulator's true world pose by
   default. The material chain's immunity to the old frame — sites keyed by
   `site_id` rather than by position — was the right design and remains in place;
   it is now belt and braces rather than the only thing holding the ledger up.
3. **FR-MAP-1(b), per-cell last-update timestamp.** Unchanged from D-09.
   `ResourceMap` tracks mean, variance and count and no per-cell time.
4. **PRD exit-gate row 7.** Not achievable headlessly; recorded NOT COVERED with
   its reason in every report the gate writes.
5. ~~**No JavaScript test runner.**~~ **CLOSED 2026-07-31.** There are now two
   suites under `selene_dashboard/src/__tests__/` —
   `fleetMap.marks.test.js` (D-16) and `fleetState.resourceMapRevision.test.js`
   (D-15) — running under `react-scripts test`. **Measured here: 39 passed, 39
   total, 2 suites.** They execute the real reducer and the real mark planner.
   What they still do not do is render: jsdom has no canvas, so every claim about
   what appears on screen remains an observation-or-nothing question, and the
   only observations that exist are the operator's Chrome pass recorded in D-01,
   D-02, D-03, D-04 and D-17.
6. **Physical material transfer in Gazebo.** The excavator-to-hauler handoff is
   ledger-mediated: two uncoupled sim nodes whose coupling is an authorisation
   number (`quantity_kg`), not a physical stockpile model. Honest about what it
   measures; not the same as simulating it.
7. **The recharge/depot position inconsistency — SUPERSEDED by D-23 and D-32,
   and it was worse than this item said.** The ISRU depot is no longer (50, 50):
   D-23 moved it to (−100, −150) on the crater floor, because (50, 50) was
   outside a 34° crater containing every deposit and **no haul to it could ever
   have completed**. This item recorded three positions disagreeing and treated
   it as untidiness; one of the three was mission-fatal. The recharge station's
   three-way disagreement is unchanged and is now tracked under D-32, together
   with the larger problem that the pad is behind the same wall.
8. **`selene_orchestrator/package.xml`** declares `rclpy`, `selene_msgs`,
   `geometry_msgs`, `builtin_interfaces` and `lifecycle_msgs`, but
   `orchestrator_node.py` imports `std_msgs` and `visualization_msgs`.
   Pre-existing; the Humble CI job apt-installs both, which is why it has never
   failed. Out of scope, recorded.

Added 2026-07-31, all found while verifying the closures above:

9. **Operator `TaskEvent`s carry `task_id=''` unconditionally.**
   `_handle_override_robot` (`orchestrator_node.py:1955-1960`) hardcodes it, even
   when `override_robot_logic` had the interrupted task's id in hand three lines
   earlier. `TaskEvent.msg` documents the field as "the task the event is about,
   or `''` when it is not about a task", so the comment describes an intent the
   code does not carry out, and the dashboard joins a cancel to its task only via
   a separate status row. D-05's mechanism works; this is the one field that
   would make the join explicit.
10. **A task requeued as `preferred_robot_absent` rests in INTERRUPTED though it
    was never started.** `REQUEUE_STATUS_BY_REASON` (`task_feed.py:221-225`) maps
    it that way, while the comment immediately above it argues — correctly, for
    the adjacent `auction_no_bids` key — that INTERRUPTED would be a lie about a
    task nobody ever began. So a targeted injection whose robot is busy shows up
    to two INTERRUPTED rows beside the INTERRUPTED that means a real operator
    cancel, which is the distinction D-03 exists to create. `status_reason`
    disambiguates them and is rendered; the status itself does not.
11. **`sensors/depth` and `sensors/imu` are declared by all three RCDLs and
    published by nothing.** The same failure mode as D-11 — a skill reading them
    would get `is_valid=False` forever — and pre-existing. Both are now
    allow-listed with reasons in `test_sensor_topic_coverage.py` and rot-checked,
    so they stay visible and the allow-list entry must be deleted if anyone fixes
    them.
12. **`extraction_node.py:80-81` integrates a second, independent "total
    extracted kg"** from the same Gaussian concentration model at a hardcoded
    0.5 kg/s,
    duplicating `HopperNode.BASE_EXTRACTION_RATE` with no shared constant. It
    never clamps and never resets, so it diverges from the hopper's mass by
    construction as soon as the hopper drains. Harmless today —
    `/{rid}/extraction/rate` and `/extraction/total` have zero subscribers
    repo-wide — but it is a second unowned source of "extracted kg" next to a
    ledger whose entire value is having exactly one.
13. **`GazeboTransferActuator.trigger_load(max_kg)` sends an absolute fill
    target while `HaulSkill` passes a per-pickup quota and measures an
    increment.** They agree whenever the bin arrives empty, which the unload
    phase normally guarantees. With residue in the bin the load stops early; the
    settle detector then ends the phase and reports the true measured delta, so
    the ledger stays correct and conservation holds — the haul merely under-fills.
    Recorded rather than reconciled, because choosing between the two semantics
    is a design decision and neither has ever been run.
14. **`_publish_assignment_msg` has no caller.** Kept, documented as having none,
    and specifically *not* routed through D-06's haul authorisation gate for that
    reason. It is the same shape as the `AdaptiveSurveyPlanner` and
    `MaterialInventory` cases this repository has now been bitten by three times.

Added 2026-07-31 by the D-01 / D-02 adversarial review, all four confirmed by
reading or grepping the working tree on this pass:

15. **Two per-snapshot typed arrays are written and never read.**
    `cellCount: Int32Array.from(count)` (`useFleetState.js:306`) and
    `priorMean: msg.prior_mean` (`:294`) are stored on every accepted snapshot;
    a grep over `selene_dashboard/src` finds no reader for either — `FleetMap`
    destructures only `{ cellIndex, cellMean, cellVariance, priorVariance }`
    (`FleetMap.jsx:223`) and the legend uses `cellIndex.length` and
    `totalObservations`. The `Int32Array.from` is paid every 2 s for nothing.
    **The wire-contract validation of `cell_observation_count.length` and
    `prior_mean` in the reducer is load-bearing and must stay** — it is only the
    storing of the results that is dead. Same species as the pattern this
    register calls the repository's recurring failure mode, at trivial cost.
16. **Four `colors.js` exports are imported by no module.**
    `iceConcentrationRGB` (`:113`), `varianceToCertainty` (`:223`),
    `LOW_CONFIDENCE_GRAY` (`:191`) and `VARIANCE_FLOOR` (`:197`). Checked on
    this pass: `FleetMap.jsx` imports `posteriorCellRGBA` and mentions
    `LOW_CONFIDENCE_GRAY` only in a comment; `ResourceLegend.jsx` imports
    `iceConcentrationColor`, `certaintyRGB`, `ALPHA_MIN`, `ALPHA_MAX`. There is
    a real reason not to un-export them —
    `test_dashboard_colour_parity.py` parses these four out of the file as text
    and would be harder to write against non-exported constants — but that
    reason is nowhere in the file, so the next reader will see four orphans.
    Say so in `colors.js` or drop the exports.
17. **Four comments name `App.jsx` as the validator when the validation is in
    `useFleetState.js`, and one guard is unreachable because of it.**
    `FleetMap.jsx:272-273` says "App.jsx validates the parallel arrays but not
    the geometry"; the `UPDATE_RESOURCE_MAP` reducer (`useFleetState.js:268-276`)
    in fact validates `resolution > 0`, `width > 0`, `height > 0`,
    `prior_mean` finite and `prior_variance > 0` and drops the snapshot
    otherwise. So `resourceMap` cannot reach `FleetMap` with
    `resolution <= 0` and the guard at `FleetMap.jsx:276` can never fire —
    dead code justified by a false premise. Same misattribution at
    `FleetMap.jsx:224-225`, `useFleetState.js:31` and `ResourceLegend.css:47-51`,
    the last of which also states the wrong rejection condition, so the legend's
    own warning text under-reports why a snapshot was dropped.
18. **`ResourceGraph`'s node opacity is now a constant on purpose, and that is
    a deliberate loss.** D-02 replaced the inert `uncertaintyAlpha` with
    `NODE_ALPHA = 0.6` rather than repointing it at the posterior, on the
    argument that a raw reading carries no confidence to encode. The argument
    holds, but the consequence is that the "Resource Knowledge Map" has no
    confidence channel at all, and FR-DASH-2's opacity clause is satisfied only
    by the fleet map. Recorded so the deletion is not later mistaken for an
    oversight.

Added 2026-07-31 (evening), from the live runs and the exit-gate runs:

19. **A non-finite reading is still accepted at ingest.** D-18 made both
    renderers safe on a `NaN` cell mean; it did not stop one entering the map.
    `orchestrator_node._on_map_update` passes `msg.ice_concentration` into
    `ResourceMap.update` with **no finiteness check**, while
    `agent_node._publish_map_update` already validates and drops a non-finite
    `sensor_uncertainty` on the way out. A `NaN` mean fused into a cell is
    permanent. No path is known that produces one; the asymmetry is the point.
20. **The 1.0109e-4 kg cross-instrument disagreement is unexplained.** D-27
    raised the overdraw tolerance so a healthy haul stops raising an alarm, which
    was correct — the old bar was below one float32 ulp of the compared quantity.
    It explains nothing about the residue itself, which two independent reviews
    put at **53 to 85 float32 ulps** depending on which instrument's scale you
    measure it against: one and a half to two orders of magnitude too large for
    quantisation. The hopper and the load cell disagreed by more than their
    representation allows and nobody has found out why. The ten-robot run
    returned `unaccounted_quantity` exactly 0.0, so the disagreement is currently
    *not reproducing*, which is not the same as resolved.
21. **`in_transit` retains each haul's fill-threshold overshoot permanently.**
    `ExcavateSkill.FILL_THRESHOLD` (0.95) against a 20 kg hopper gives 19.0 kg
    exactly, the excavator overshoots by a small amount on the tick that crosses,
    and `record_unload` clamps to cargo — so the overshoot stays in `in_transit`
    and nothing reconciles it. Measured: 0.0129 kg on one run, 0.026 kg over five
    hauls on another. It is small and it is **monotonic**, so
    `deposited_quantity` systematically lags `extracted_quantity` and the
    FR-DASH-7 progress bar cannot reach its target from deliveries alone. Whether
    that matters is a product decision; that it accumulates is arithmetic.
22. **DISCHARGED 2026-08-01 (latest). ALL FOUR OF (a), (b), (c) AND (d) ARE NOW
    MEASURED, AND THE PRD:1504 SIDE-BY-SIDE HAS BEEN PERFORMED AGAINST A MAP THE
    FLEET SURVEYED.**

    (b) was the last one open and it was not discharged by trying harder: it was
    discharged by **D-43**, the path-follower waypoint-retirement bug. Before that
    fix the first reading reached the posterior at t=802 s and only 6 of 10
    waypoints ever completed, so the only way to get a populated map was to seed
    it synthetically and say so. After it, readings land at t=240 s and all ten
    complete.

    **THE RUN, and nothing in it was seeded:**

        prospect completions         9        (nothing injected by the script)
        total_observations         793        (fleet's own readings)
        dashboard legend           675 cells / 712 readings  (sampled mid-run)
        /orchestrator/resource_map_markers   Publisher count: 1
        /orchestrator/resource_map           Publisher count: 1
        /tf_static                           Publisher count: 1
        rviz2 processes              1        orchestrators: 1
        RViz2 Global Status          Ok       Fixed Frame: OK
        RViz2 Resource Map           Status: Ok
        RViz2 view       TopDownOrtho, Angle 0, Scale 5.3, X -92.5, Y -150

    Both renderers show the same thing and it is visibly NOT the seeded picture:
    a surveyed map is a handful of **discrete overlapping discs**, one per
    waypoint the scouts actually reached, rather than the smooth radial Gaussian
    a synthetic seed produces. That difference is the evidence that (b) is
    discharged — the images could not be mistaken for the seeded pair.

    **THE EARLIER `Scale: 0.625363` RESIDUAL DID NOT RECUR.** The launch-started
    RViz2 now comes up at the committed 5.3. The most likely explanation is that
    the earlier capture caught an instance left over from the double-RViz2 defect
    below, before the box was fully torn down — but that is a reconstruction, not
    a measurement, and the cause is **not established**.

    **WHAT IS STILL NOT CLAIMED.** The two images share a centre, a projection,
    an orientation and a 50 m grid, but NOT an aspect ratio: RViz2's packaged
    window is 16:9 at 5.3 px/m (~219 m across) and the dashboard canvas measured
    1240 x 576 over DEFAULT_VIEW's 185 x 170 m. The comparison is "same centre,
    same lattice, count the cells", not "identical rectangles", and that residue
    is real.

    ---

    **Superseded status line, 2026-08-01 (late): (a), (c) and (d) ARE NOW
    DISCHARGED AND MEASURED. (b) IS NOT, AND ONE NEW RESIDUAL IS RECORDED.** The
    item stays open on (b) alone.

    **(d) — THE FIXED FRAME. FIXED, AND CONFIRMED ON SCREEN.** A new
    `selene_sim/launch/rviz.launch.py` starts the viewer TOGETHER WITH a
    `tf2_ros/static_transform_publisher` publishing `map -> rviz_anchor`, and
    both `unified_sim.launch.py` and `simulation.launch.py` now include it
    behind the existing `rviz:=true` instead of starting a bare `rviz2` node.
    Measured on the running system: `/tf_static` **Publisher count: 1**,
    `frame_id: map`, `child_frame_id: rviz_anchor`, and RViz2's own panel
    reading **`Global Status: Ok`** with **`Fixed Frame: OK`** and
    `Resource Map — Status: Ok`. The `Warn — Frame [map] does not exist` that
    made the overlay unusable as shipped is gone, **with nothing run by hand**.
    The honest statement about this repository changes from "nothing publishes
    TF" to **"nothing publishes TF except `rviz.launch.py`, and only when a
    viewer is started"** — every headless run, every CI job and every exit-gate
    run still has zero TF publishers. Three alternatives were rejected and the
    reasons are in that file's docstring; `map -> odom` identity in particular
    is rejected as a MEASURED FALSEHOOD, because the offset is a real ~133°
    SE(2) (D-33).

    **A DEFECT FOUND WHILE FIXING IT: `rviz:=true` STARTED TWO RViz2 PROCESSES.**
    `unified_sim.launch.py` added its own delayed `rviz2` node AND forwarded the
    launch context to `simulation.launch.py`, which declares its own `rviz`
    argument and started another — a `DeclareLaunchArgument` in an included
    description does not shadow a value already in the context. Measured
    2026-08-01: one launch log carrying `[rviz2-19]: process started with pid
    [1529]` at t=0 and `[rviz2-31]: process started with pid [2186]` at t=12,
    **both alive, both subscribed to the same marker topic**. That is item
    22(a)'s failure one layer down — a launch silently opening two windows on
    one topic — and it is now pinned false by
    `'rviz': 'false'` on the include. Verified after: **`rviz2 processes: 1`**.

    **(a) — EXACTLY ONE STACK. DISCHARGED, AND ASSERTED RATHER THAN OBSERVED.**
    On a box cleaned first and then measured:

        /orchestrator/resource_map_markers   Publisher count: 1
        /orchestrator/resource_map           Publisher count: 1
        /tf_static                           Publisher count: 1
        rviz2 processes: 1     orchestrators: 1

    **(c) — FRAMING. THE OLD CONFIG COULD NOT SATISFY PRD:1504 AT ALL, AND THAT
    IS A STRONGER STATEMENT THAN "IT WAS AIMED WRONG".** The committed camera was
    an `Orbit` at `Yaw 0.785, Pitch 1.2` — an **oblique perspective** — while the
    dashboard is an **orthographic north-up 2-D canvas**. Those projections
    cannot be reconciled by tuning distance: under perspective, equal world
    distances subtend different screen distances with depth, so a cell matched at
    the near edge is wrong at the far one. The side-by-side was therefore not
    merely un-performed, it was **not performable from the committed config**.
    And the focal point (-100,-150) was the PSR/depot centre, **not the ice**:
    `deposit_alpha` is centred (-80,-140) with sigma 12, so at 22.4 m its
    Gaussian is 1.40 wt% — t = 0.140 on the 0..10 ramp, the blue end. The shipped
    frame was centred on the cold edge of the only warm thing in the scene, which
    is exactly the picture item 22(c) describes. Now `TopDownOrtho`, `Angle 0`,
    centred on **(-92.5, -150)** — copied from `DEFAULT_VIEW.CENTER_X/CENTER_Y`
    in `selene_dashboard/src/utils/worldConfig.js`, not chosen — with the Grid
    at **50 m** to match `FleetMap.jsx`'s `const minor = 50`, so the two images
    can be compared by counting cells. The old oblique camera is kept as a saved
    view, because it is genuinely better for reading crater relief.

    **NEW RESIDUAL, AND IT IS UNEXPLAINED.** The launch-started RViz2 came up at
    **`Scale: 0.625363`** px/m against the committed **`Scale: 5.3`** — it
    honoured `Class`, `Angle`, `X` and `Y` from the same file and not `Scale`, so
    the operator opens zoomed out to ~1856 m across and must zoom in. A directly
    started `rviz2 -d` on a copy of that same file with `Scale: 30.0` came up at
    **exactly 30**, rendering the CUBE_LIST large with the full hue ramp and
    per-cell alpha visible — so the key is honoured somewhere and not somewhere
    else. **No cause is proposed.** The overlay is usable; the default zoom is
    not yet right.

    **(b) — STILL OPEN, AND NOW WITH A MEASURED REASON.** The posterior in the
    2026-08-01 comparison was **seeded**, by the same method exit-gate check 10
    uses and discloses: 400 synthetic `ResourceMapUpdate` readings shaped like
    `deposit_alpha`. The fleet was given 13 minutes to survey first and did not
    get there: with D-28's per-step slope rule in force the scouts route around
    the crater rim and were measured making **0.044 m/s of net progress** toward
    their waypoints (positions sampled 110 s apart), with
    `total_observations: 0` and `/orchestrator/map_update` never published. After
    seeding, `total_observations: 6606`, and the dashboard legend read
    **`1744 cells · 6840 readings`**. **So both renderers were driven from one
    posterior, from one publisher, on one stack — but the fleet still has not
    found this ice, and until it does, (b) is not discharged.**

23. *(previous text of item 22, kept because the sequence is the point)*
    **The RViz2 overlay has never been rendered by RViz2, and no side-by-side
    comparison has ever been performed.** `docs/PRD.md:1504` asks for one. Every
    parity statement in this register is a machine comparison of numbers, and the
    strongest of them (exit-gate check 10) recomputes through the same module the
    publisher uses. This is the single largest remaining gap between what Phase 5
    claims and what the PRD asks for.
    **AMENDED 2026-08-01, LATE: RViz2 HAS NOW BEEN STARTED, AND IT RENDERS THE
    OVERLAY. The item is NOT discharged.** The paragraph above was written
    earlier the same day and said "it was not run"; that is now false and is
    kept visible rather than deleted, because the sequence matters.

    What was observed: `ros2 launch selene_sim unified_sim.launch.py rviz:=true`
    brought RViz2 up against `selene_sim/rviz/selene_sim.rviz`; the
    `Resource Map` display reported `Status: Ok` on
    `/orchestrator/resource_map_markers`; and after the camera was moved over the
    deposit field a CUBE_LIST of coloured cells was drawn. The dashboard,
    separately, reported `1633 cells · 7917 readings` on its own legend. **This
    is the first time RViz2 has ever been started in this project.**

    **Four reasons this does NOT discharge the item, in descending severity.**

    (a) **TWO ORCHESTRATORS WERE PUBLISHING AT THE TIME, and this is the one that
    invalidates the comparison rather than merely weakening it.** A previous
    launch out of `~/selene_ws` had never been torn down, so a second complete
    SELENE stack was live alongside the `~/selene` one under test:
    `ros2 topic info /orchestrator/resource_map_markers` reported
    **`Publisher count: 2`**. RViz2 and the dashboard therefore cannot be shown
    to have been reading the same publisher, and the claim that both render *one*
    posterior is **not established by this observation**. The reading of
    `7917` against a seeded `3920` is consistent with that contamination and was
    not otherwise explained. A clean re-run needs exactly one stack.

    (b) **The map was SEEDED, not surveyed** — 49 synthetic `ResourceMapUpdate`
    readings shaped like `deposit_alpha`, the same method exit-gate check 10 uses
    and discloses. The fleet did not find this ice.

    (c) **The framings are not identical.** RViz2 was looking at the edge of the
    field (blue, low concentration) and the dashboard capture is centred on the
    peak (green/yellow). `docs/PRD.md:1504` asks for a side-by-side; two pictures
    of different regions is a weaker thing and must not be quoted as one.

    (d) **A static `map` transform had to be published by hand for RViz2 to work
    at all**, and this is a finding in its own right rather than a testing
    artefact. Nothing in SELENE publishes TF, so RViz2's fixed frame did not
    exist and `Global Status` read `Warn — Frame [map] does not exist`; the view
    could not be established until
    `ros2 run tf2_ros static_transform_publisher --frame-id map
    --child-frame-id rviz_anchor` was run outside the launch. **The FR-MAP-4
    overlay is therefore not usable as shipped**: an operator following the
    documented `rviz:=true` path gets a warned fixed frame and no established
    view. That is a real gap between "the markers are published correctly", which
    check 10 proves, and "an operator can see them", which nothing does.

    The diagnostic camera lived in a `/tmp` copy; `selene_sim/rviz/selene_sim.rviz`
    was not modified.

Added 2026-08-01:

23. **Side-slope rollover is not measured and nothing in SELENE bounds it.**
    This is the direct cost of D-28's closure: the per-step rule licenses
    switchback routes, and a switchback spends its time traversing across the
    fall line — which is the attitude a real vehicle rolls over in, and usually
    the binding limit rather than the climbing grade. The campaign measured
    straight up and straight down only, by construction. The limitation is stated
    in `nav_params.yaml` beside the constant and in the campaign artefact's own
    `limitations` list; **it is not stated in any test, and nothing fails if it
    is violated.**
24. **The slope campaign is one trial per condition.** 54 trials, 54 different
    (robot, grade, direction) triples, no repeats. No run-to-run spread was
    measured and no confidence interval can be quoted from it — and two of the
    six per-robot-direction verdicts are **non-monotonic in grade**, which means
    something other than grade is moving the outcome. D-41 names one such thing
    and does not account for all of them.
25. **No vehicle has driven a switchback.** The 132.0 m and 130.2 m routes under
    D-32, and the "one connected component" result under D-28, are **executed
    plans over the committed heightmap**, not journeys. The startup audit that
    runs on every agent reports the same lattice arithmetic. Whether a
    differential-drive rover on this terrain can actually follow one of these
    paths is untested, and it is the obvious next physical experiment.
26. **Every browser observation in this register from 2026-08-01 was made against
    a rosbridge TEST DOUBLE, not the real stack.** That covers D-40's canvas
    lifecycle, D-31's "NO POSITION FIX" roster and D-34's 247 ms IDLE hand-off.
    They prove what the browser does when messages of that shape arrive; they
    prove nothing about ROS, DDS, QoS, the orchestrator, or message shapes the
    double does not reproduce. The 2026-07-31 Chrome pass (D-01..D-04, D-17) was
    against a **live** rosbridge and is a different and stronger kind of
    evidence; the two must not be quoted as if they were the same.
27. **Two Gazebo version strings disagree on the machine that produced the
    campaign.** `gz sim --versions` answers **8.10.0** and `gz sim --version`
    answers **8.11.0** on the same installation on the same host on 2026-08-01;
    the campaign artefact records the former and the 2026-07-31 gate runs are
    recorded here against the latter. **Which version describes the physics
    engine that produced any of these measurements has not been established**,
    and the difference is recorded rather than assumed cosmetic
    (`docs/slope_capability_2026-08-01.PROVENANCE.md`). Every cross-run
    comparison in this register quietly assumes one physics build.

---

## Verification limits

**Rewritten 2026-07-31 (evening). Several of the limits below have been lifted
by running the system, and each says so in place rather than being deleted** —
a reader who remembers this list as it stood needs to see which line moved. The
ones that remain are the ones that matter now.

**Amended 2026-08-01.** Item **19** carries new counts, all re-run on this box.
Item **20** is **LIFTED, and it was also partly wrong when it was written** —
see the entry. Items **24-27** are new and are the limits of the slope campaign,
the browser session and the 2026-08-01 gate run. Item 1's unqualified clause
("RViz2 was never started") is still unqualified.

This section applies to the whole register. **None of the following may be
described as verified, measured, or observed.**

1. ~~**Nothing in that work was executed against ROS 2, Gazebo, DDS, rosbridge,
   RViz2 or a browser.**~~ **PARTIALLY LIFTED.** Between 2026-07-30 and the
   evening of 2026-07-31 the system was run: `colcon build` (6 packages,
   0 errors), a four-robot fleet three times, a ten-robot fleet twice
   (615 s and 1818 s), and `scripts/validate_phase5.sh` twice. A browser was
   opened and the dashboard confirmed rendering. **RViz2 was never started, and
   no side-by-side image comparison was performed** — that limit stands
   unqualified and is open item 22.

   **This document's owner ran none of it.** What was run here is the Windows
   test lanes (item 19), every `file:line` citation opened and read, and the
   arithmetic in D-06, D-22, D-37 and the lattice corollary recomputed
   independently. Every live figure in this register is attributed to the run
   that produced it, and where a run report's own arithmetic disagreed with its
   own quoted inputs — D-22's 2.303 m against a recomputed 2.330 m — both
   numbers are printed.
2. ~~**`colcon` and `rosidl` never ran.**~~ **LIFTED.** `colcon build` completed
   with **6 packages, 0 errors** on ROS 2 Jazzy, repeatedly, on 2026-07-31, with
   `symlink-install`. The five new and four amended `.msg` definitions have been
   generated by `rosidl` and the resulting interfaces carried real traffic: the
   ledger's `MaterialEvent` moved 15 events across a live run, and
   `TaskQueueState` was subscribed over rosbridge by the exit gate. **`colcon
   test` still has not run**, so the per-package test entry points remain
   unexercised under a real workspace.
3. **`GazeboTransferActuator` never completing** is a static argument from four
   lines of `gazebo_hal.py` and two of `haul.py`. It is demonstrated in the
   ROS-free lane with a mock; no haul was run to watch the 30 s timeout fire.
4. **The `ImageData` row flip** in `FleetMap.jsx` **is now checked, and it is
   correct** — but it has still not been rendered. This item used to read "the
   single change most likely to be silently wrong". On 2026-07-31 three
   independent passes executed the whole round trip outside a browser —
   producer flat index (`np.flatnonzero` over `_count[gy, gx]`, so
   `flat = gy*width + gx`), consumer decode (`FleetMap.jsx:241-256`), and the
   blit's `translate(originX, originY + height*res)` + `scale(res, -res)`
   (`:287-289`) — and all three reproduced `ResourceMap.grid_to_world()`
   exactly. This register's own pass sampled 36,000 cells across all 500 rows
   with **zero mismatches**, including D-08's measured hot cell: world
   (-80.5, -140.5) -> grid (169, 109) -> flat 54669 -> image row 390 -> world
   centre (-80.5, -140.5). The counterfactual was checked too: omitting the
   flip puts that cell at world y **+140.5**, a clean mirror about y = 0 — the
   plausible-looking defect this repository shipped once in
   `generate_heightmap.py`. It did not happen here: the flip occurs once in the
   index and is undone by the north-west anchor, and the two do not compound.
   **This is arithmetic agreeing with arithmetic.** Nothing was rendered, so the
   remaining failure modes for this blit — that the canvas draws it at all, that
   `imageSmoothingEnabled = false` holds, that the raster lands in the right
   place relative to the terrain layer — are untouched by the above.
5. **Label legibility and the battery gauge** (D-01) are static arguments from
   the canvas transform chain and the label separation constants, not
   observations in a browser.
6. **TRANSIENT_LOCAL + RELIABLE replay** for `MaterialEvent` and `TaskResult` —
   that a restarting orchestrator receives each agent's history — is Fast DDS
   behaviour nobody exercised. The `event_id` dedupe is designed so that a wrong
   assumption degrades to **lost history**, never to double-counted mass.
7. ~~**Fill and drain timings**~~ **LIFTED for the excavator, still open for the
   sensor.** An excavator did sit on ore long enough to fill: five excavate/haul
   cycles completed at 174 s spacing, each delivering 18.94–19.00 kg, and
   `hopper_full=True` was reached every time. The concern this item raised —
   navigation accuracy in the dead-reckoned frame — no longer applies, because
   the frame is world and the pose is truth-backed (D-33, D-24). **The RCDL
   capacities themselves are still unvalidated** — see item 12.
8. **`TaskQueueState` on-the-wire size** (~21 tasks, under 4 kB) is arithmetic
   scaled from `ResourceMap.msg`'s measurements. The rosbridge `extract_values`
   cost of **nested** message arrays is covered by no measurement anyone has.
9. **Dashboard rendering — partially lifted, and the residue is specific.** The
   dashboard was opened in Chrome against a live rosbridge on 2026-07-31 and
   D-01, D-02, D-03, D-04 and D-17's replacement legend were confirmed
   rendering; the ISRU ledger's masses were seen in the browser. **What remains
   unverified** is everything quantitative about the rendering: frame timing and
   dropped frames (PRD row 7, NOT COVERED by construction), whether the raster
   holds 30 fps, whether the compressed alpha band reads as a confidence
   gradient, and whether D-16's label-overlap arithmetic matches what a depot
   cluster actually looks like. The confirmation was recorded as one line naming
   five deviations, not as an itemised inspection.
10. **Cross-language parity** is now machine-checked over the **whole** colour
    law, not just the concentration ramp — see D-02 correction 3.
    `test_dashboard_colour_parity.py` parses `LOW_CONFIDENCE_GRAY`,
    `VARIANCE_FLOOR`, `ALPHA_MIN` and `ALPHA_MAX` out of `colors.js`, rebuilds
    `varianceToCertainty` and the gray lerp from those numbers, and asserts
    exact per-channel equality. **What it still cannot see** is a change to a JS
    function *body* that leaves the constants alone (there is no JS test runner
    — open item 5), and it does not cover non-finite inputs, where the two
    halves provably disagree — that is D-18.
11. **The `TaskQueueState` snapshot at 2 Hz has not been shown to meet PRD row
    3's 1-second budget.** The 500 ms worst-case publish latency is arithmetic
    from the period. End-to-end latency through rosbridge into a browser was not
    measured and cannot be from here; D-10's check 9 is designed to measure the
    transport half only.
12. **The RCDL capacities have no cross-check anywhere in the repository.**
    Whether `capacity_kg: 20` (excavator hopper) and `capacity_kg: 50` (hauler
    bin) correspond to any geometry in `selene_sim/models/*/model.sdf` is
    unverified, as are the `transfer_rate` figures of 5 and 10 kg/s. Every
    kilogram in every new test descends from those four numbers.
13. **QoS negotiation was never observed anywhere.** That the HAL's
    `_SENSOR_QOS` (BEST_EFFORT / VOLATILE / depth 5) matches the sim nodes'
    default publisher profile (RELIABLE / VOLATILE / depth 10) is argued from
    DDS compatibility rules. A profile mismatch presents as a topic with both
    ends and no messages — the same silent shape as D-11.
14. **`HaulSkill.SETTLE_GRACE = 2.0 s` and `SETTLE_TICKS = 5`** are arithmetic
    from the agent's 10 Hz tick, not a measured DDS round trip. Too short and a
    haul reports 0 kg loaded; too long and it costs up to 2 s per transfer. At
    the 0.5x real-time factor NFR-1.5 permits on WSL2, neither direction has
    been checked.
15. **The site-registration ordering argument is static.** That no
    `MaterialEvent` can arrive for an unregistered site rests on every excavate
    depending on the `select_site` task, `get_next_ready` refusing a task with
    incomplete dependencies, and the site id being allocated in the same call
    that completes `select_site`. It assumes the 1 Hz `_htn_advance` timer and
    the 2 Hz auction tick interleave as the dependency graph implies. Not
    observed.
16. **`material_residual_tolerance_kg = 0.5` is a judgement, not a noise
    figure** — 2.5% of the hopper, 1% of the bin. No fill-sensor noise has been
    measured. Whether a real hopper sensor and a real load cell agree within
    0.5 kg on the same material in Gazebo is *exactly* what this instrumentation
    exists to find out, and it has not been run.
17. **Neither rewritten sim node was ever instantiated.** `rclpy.Node.__init__`,
    `declare_parameter`, `create_subscription`, `create_publisher` and
    `create_timer` are unexercised in `hopper_node.py` and `bin_load_node.py`;
    only the pure `FillModel` layer beneath them is tested.
    `simulation.launch.py` byte-compiles but `generate_launch_description()` was
    never called, so the `FindPackageShare` substitution that supplies
    `rcdl_path` has never been resolved — the construction is copied from
    `agent.launch.py`, which is an argument from precedent, not a test.
    `selene_sim/package.xml`'s new `<exec_depend>selene_hal</exec_depend>` has
    never been resolved by any build system.
18. **`/{rid}/actuators/hopper_cmd` has never carried a message**, and the
    `"load:<kg>"` round trip is tested only as two isolated halves — the
    formatting side in a test that skips here, the parsing side in
    `test_fill_model.py`. The two have never met on a wire.
19. **What WAS executed on this box, and may be quoted as measured.** Every
    figure below was produced on the evening of 2026-07-31 by this register's
    owner, on Python 3.11.6 / pytest 9.1.1 / flake8 7.3.0, against the
    uncommitted working tree — **re-run, not copied forward from any
    implementer's report**. Counts rise as repairs add tests, so treat the
    baseline comparison rather than the absolute number as the invariant.

        selene_orchestrator + selene_isru + selene_hal + selene_agent
                                                      826 passed, 1 skipped
            (was 542/1 before this work; the operator's own lane, and green)
        selene_sim/test                               120 passed, 1 skipped
            (was 61/1)
        all FIVE packages in ONE process              947 passed, 1 skipped
            (was 604/1)
        selene_hal/test + selene_agent/test           307 passed, 1 skipped
        flake8 over all five packages + scripts/      exit 0
        npx eslint src                                exit 0
        CI=true npx react-scripts test                39 passed, 2 suites
        CI=true npx react-scripts build               compiled

    **One documented lane is RED and that is a new finding, not an omission:**

        PYTHONPATH="selene_orchestrator;selene_isru" \
          python -m pytest selene_orchestrator/test selene_isru/test -q
          -> 1 failed, 518 passed

    This is the lane this register has called "THE GATE LANE" and quoted at 327
    passed. It fails on an unguarded cross-package import and it is **D-36**.
    (**FIXED later the same day**; re-measured at 518 passed / 1 skipped. The
    reading above is preserved as the measurement that found the defect —
    D-36 records the fix and the counts that verify it.)
    The two skips are the declared ones (`selene_hal`'s Gazebo backend needs a
    real `rclpy`; one `selene_sim` case needs `selene_hal` on the path), and the
    five-package total exceeding the sum of the lanes by one pass is the same
    documented effect as before.

    Also recomputed here rather than accepted: the ledger residual in D-06
    (+3.815e-06 kg from the five printed float values), the two robot-robot
    separations in D-22 (**2.3299 m**, against a run report that states
    2.303 m — the discrepancy is printed rather than reconciled), the ODE
    lattice arithmetic in D-37 (500/129 × 128 / 2 = 248.06201550387595), and all
    four hazard figures in D-37 (`exp(−24327/5040) = 0.008`; 3/λ = 15,120).
    Every `file:line` citation in this document was opened and read on this
    pass, against the working tree at base commit `bab8af6`. That tree was
    committed mid-amendment as `30403a8`, so they are now citations into
    committed code — but they were verified before that commit existed, and
    they will drift if anyone edits those files.

    **What the dashboard build and lint do and do not prove.** `eslint`,
    `react-scripts build` and the Jest suite say the bundle compiles and that the
    reducer and the mark planner behave. They say nothing whatever about what is
    drawn: jsdom has no canvas. The only rendering evidence in this register is
    the operator's Chrome pass.

    > **RE-MEASURED 2026-08-01 on the committed tree at `9c1a4d7`**, same box,
    > by this amendment's author, running each command rather than copying a
    > commit message. Counts rise as repairs add tests; the invariant is the
    > comparison, not the absolute number.
    >
    >     all FIVE packages in ONE process        1150 passed, 1 skipped
    >         (was 947/1) — identical in both collection orders
    >     gate lane (orchestrator + isru)           623 passed, 3 skipped
    >         (was 518/1, and 1 failed/518 before D-36)
    >     flake8 over five packages + scripts/      exit 0, 0 findings
    >     CI=true npx react-scripts test            101 passed, 7 suites
    >         (was 39 passed, 2 suites)
    >
    > **The gate lane's three skips are all `importorskip`-guarded with the D-36
    > reason, and the cross-package lane still RUNS all of those assertions with
    > zero skips** — which is the half that makes a skip legitimate rather than a
    > hiding place. Both are now enforced by CI jobs (`gate-lane-tests` and
    > `cross-package-tests`); see D-36.
20. ~~**`shellcheck` was not run**~~ **LIFTED 2026-08-01 — and this item was
    partly wrong when it was written, which is worth more than the lift.** It
    said shellcheck "has still never been run against the rewritten
    `validate_phase5.sh`". **CI had already run it.** The `shell-lint` job
    executes exactly `shellcheck -S warning scripts/*.sh`
    (`.github/workflows/ci.yaml:403-405`), and its `shellcheck` step concluded
    `success` in run `30586258889` at `1200327` on 2026-07-30 — a commit at which
    `validate_phase5.sh` already carried its `251e84d` rewrite. The true claim
    was the narrower one this item also made: it was not run **here**, on this
    box, and is not installed here (still true — no `shellcheck` binary exists in
    the WSL2 distro either). **The lesson is the register's own**: "nobody has
    run X" is a claim about a search, and the search had not been run against CI.
    **Now**: `shellcheck -S warning scripts/*.sh` succeeded in CI at `d390315`,
    `7727ba8` and `9c1a4d7` (runs `30678095310`, `30681543994`, `30685883138`),
    so the current `validate_phase5.sh` — the most-executed script in the tree —
    is covered. The operator additionally reports `rc=0` locally. `bash -n` is
    clean on the shell scripts this work touched.
21. **Nothing in the two ten-robot runs, the three four-robot runs or the two
    gate runs was executed by this document's owner**, and none of the raw
    artefacts is in the repository. The pose captures, launch logs and analyser
    output live under `/root/` in WSL2. Where a run report's number could be
    recomputed from values it quoted, it was (item 19); where it could not — the
    slip percentages, the path integrals, the frame-gate ground-truth
    comparisons, the 34.09° rim minimum — **it is reported on the authority of
    the run that produced it and cannot be re-derived from this repository.**
22. **The `Dbg ODE Heightfield AABB` refutation in D-37 rests on a healthy run,
    not on the crashes.** The archived crash logs are no longer on disk. What was
    measured is that the line is a load-time print at default verbosity in a
    non-aborting run, and that the analyser's grep could not have matched it. The
    inference that it therefore appears at load time in the crash logs too is
    strongly supported and was not directly checked.
23. **The abort's non-recurrence is a statistical statement about one fleet size
    on one machine, and it presumes a hazard model nobody has justified.** See
    D-37's four caveats. It is not a fix and must not be recorded as one.

Added 2026-08-01:

24. **Nothing in the slope campaign, the 2026-08-01 gate run or the browser
    session was executed by this document's owner**, and the same rule as item 21
    applies: those figures are reported on the authority of the runs that
    produced them. What **was** executed here is every test lane in item 19, every
    `file:line` citation added on this pass, the XML validity of the two files in
    D-39, the `nav_params.yaml` leaf-key and allow-list counts in D-28, the
    battery arithmetic in D-42, and the CI run and job conclusions, read from the
    GitHub Actions API by run id.
25. **The slope campaign's committed artefact carries a WRONG commit id and is
    still evidence, for a reason that must not be generalised.**
    `slope_capability_2026-08-01.json` records `git_commit: ff80ed1`; the run
    used `7727ba8`'s files. It stands **only** because all four input SHA-256s
    verify against the committed repository — the world, both heightmaps and the
    terrain datum. **A future artefact without those hashes would not survive the
    same mistake.** The correction is additive
    (`docs/slope_capability_2026-08-01.PROVENANCE.md`); the as-run JSON was not
    edited, because the hash chain inside it is what makes it evidence.
26. **The 2026-08-01 gate run's `pose_valid` evidence is one-sided.** Three
    consumers read the new field and the dashboard's no-fix path was seen in a
    browser against a test double, but **no robot has been observed publishing
    `pose_valid = false` on a running system**, and the fail-safe default means a
    partially rebuilt workspace produces exactly that value for the wrong reason.
    The mitigation is procedural — rebuild all six packages in one `colcon
    build` — and nothing enforces it.
27. **`colcon test` still has not run.** `colcon build` has run many times,
    including in this session's workspace sync; the per-package test entry points
    remain unexercised under a real workspace on this machine. CI's
    `build-and-test` job does run `colcon test` under ROS 2 **Humble**, which is
    not the distro the operator's workspace uses.

---

## Recommended disposition

**Phase 5 cannot be closed. The exit gate has now been run three times and it
does not pass** — 8/1/2 (exit 1), then 9/0/2 (exit 2), then **10 passed /
1 failed / 0 skipped (exit 1)** on 2026-08-01 at `9c1a4d7`. That is the whole
answer. Everything below is detail on it, and the detail has changed shape twice
since the revision before last: **the problem is no longer that nothing has been
run, and it is no longer that the instrument cannot see.**

**What the third run changed.** **Zero skips.** Checks 6 and 9 produced verdicts
for the first time and both PASSed, so **PRD exit-gate rows 3 and 4 are measured
at last** — that is D-34 closed on the gate's own output. The remaining failure
is check 11, and it is neither the system nor the aim of the check: the gate
selected a robot reporting 0.0% battery and never established that it could
perform the manoeuvre, so the energy-critical rule overrode the operator command
six milliseconds after the FSM accepted it. **That 0% is D-42 and its cause is
unknown.**

**All six deviations this register carried as open are closed** (D-28, D-30,
D-31, D-32, D-34, D-35), and five new ones were opened (D-38..D-42). **Two are
open now, D-37 and D-42, and neither has a known cause.**

What is true, and it is a great deal more than it was on 2026-07-30. Phase 5 is
**code-complete against all nine requirements**. The workspace builds — six
packages, zero errors, `rosidl` has generated every message. A ten-robot fleet
ran for 30 minutes at real-time factor 1.000 and **delivered 94.85 kg of
material to a depot it could physically reach**, with `unaccounted_quantity`
exactly 0.0 and `deposited_quantity` non-zero for the first time in this
project's history. The dashboard was opened in a browser and five deviations
were confirmed rendering in it. Eleven of the nineteen deviations opened on
2026-07-31 are closed on live evidence. **Four defects that had been silently
costing the mission for entire phases were found and fixed** (D-19..D-22), and
one — D-23 — was a mission-fatal geometry error nobody had ever checked: every
ice deposit sat inside a 34° crater and every depot sat outside it, so **no haul
in this system had ever been physically possible.**

What is missing:

1. **The gate must go green, and what stands between it and green is now ONE
   check and ONE unknown.** ~~Checks 6 and 9 SKIP on a correct system…~~
   **DONE 2026-08-01**: D-34 was fixed on both sides, checks 6 and 9 produced
   verdicts, and the run had **zero skips**. D-35's coin flip is fixed too — the
   bearing is chosen off the robot's heading and the window is derived from
   `scout.yaml`, both visible in the run's own output — and the 12 s literal was
   **deleted, not raised**. **What remains is check 11's missing precondition**:
   it issues an override to a robot without establishing that the robot can obey
   it, and on 2026-08-01 it chose one at 0% battery. Fixing the check is cheap;
   **finding out why that robot reported 0% is D-42 and comes first**, because a
   gate taught to avoid a robot in a state nobody understands is a gate taught to
   look away. `$HOME/selene/phase5_validation_report.md` was regenerated **by**
   the 2026-08-01 run and is not green; the in-tree
   `docs/phase5_validation_report.md` **is still the superseded eight-check gate
   at `251e84d`** and must be replaced by the output of a green run, never
   hand-edited.

2. **The ODE abort's cause is unknown, and this is the largest open risk in the
   repository.** Three reproducible SIGABRTs; no root cause. The terrain-edge
   theory the repository asserted **as a measured fact in two configuration
   files is refuted** and both files now say so. 24,327 abort-free robot-seconds
   have since been accumulated at the only fleet size with a measured abort
   time, which clears a p<0.01 bar against the fitted hazard — and **four things
   changed at once**, so it identifies nothing. What has genuinely improved is
   that the next abort will be loud rather than silent (**D-26**). The next
   experiment is named in **D-37**: hold a 4/3/3 fleet *driving* rather than
   exiting on first deposit, and instrument fleet-metres, so a per-metre hazard
   can be told apart from a per-second one.

3. **Perform the PRD's visual methods, or accept in writing that they were not
   performed — and the list is now short and specific.** A browser has been
   opened, so most of this section's predecessor is discharged. What remains is
   `docs/PRD.md:1504`: **RViz2 has never been started and no side-by-side
   comparison of the overlay against the dashboard heatmap has ever been made**
   (open item 22). Every parity claim in this document is a machine comparison
   of numbers, and the strongest of them recomputes through the same module the
   publisher uses. PRD row 7 (frame timing) is NOT COVERED by construction. No
   demo recording exists in-tree (`docs/PRD.md:1511`).

4. **Three figures this register published as measurements are superseded and
   must not be quoted.** D-08's hot cell at world (−80.5, −140.5), FR-MAP-3's
   SC-3 comparison, and every position in every run recorded before 2026-07-31
   were measured in a frame that has since been proved to be a full SE(2)
   rotation away from the world (**D-33**). SC-3 in particular **needs
   re-measuring in world coordinates**; the adaptive-versus-static comparison
   survives, the coordinates do not.

5. ~~**Seven deviations remain open and two of them will bite a demo.**~~
   **SIX OF THE SEVEN ARE CLOSED, 2026-08-01.** D-28 is closed with a **measured**
   slope limit (54 trials) enforced **per step**, and a startup audit every agent
   logs. D-30 is root-caused — the detector was timing "how long since this robot
   moved 1 cm", a clock that runs while a robot is parked — and now reports
   "N of M". D-31 is **diagnosed for the first time** (a fabricated pose
   published before odometry existed) and fixed with a `pose_valid` flag three
   consumers read, **with sufficiency explicitly not claimed**. D-32 is
   **dissolved**: the wall was never unclimbable, only unclimbable straight up.
   D-34 and D-35 are closed on the gate's own output. D-36's remainder has a CI
   job. **What remains open is D-37 and D-42, and neither has a cause.**
   **Two things a demo should still expect**: no vehicle has driven a switchback,
   and side-slope rollover — the failure mode the new rule licenses — is
   unmeasured and unbounded (open items 23 and 25).

6. ~~**Fix D-36 before anyone trusts a lane count.**~~ **DONE 2026-07-31**, and
   **its remainder is DONE 2026-08-01.** `test_terrain_guard.py`'s unguarded
   `selene_agent` import is an `importorskip`, and a new CI job
   `gate-lane-tests` now runs the gate lane **whole** on the two-package path —
   mutation-tested before commit, reproducing D-36's own measurement (guard
   removed: gate lane 1 failed/518 passed while the cross-package lane stays
   green at 51 passed). Green in CI at `d390315`, `7727ba8` and `9c1a4d7`.

7. **Run `colcon test` on the operator's distro.** ~~and `shellcheck`~~ —
   `shellcheck -S warning scripts/*.sh` has now run green in CI at all three of
   this session's later commits, so the rewritten `validate_phase5.sh` is
   covered; see verification limit 20, **which was wrong about this and says so**.
   `colcon test` still has not run under Jazzy on the operator's workspace;
   CI runs it under **Humble**, which is a different distro.

8. **Run RViz2.** It is item 22, it is the largest gap between what Phase 5
   claims and what `docs/PRD.md:1504` asks for, `rviz:=true` is already wired and
   WSLg is available on the machine that ran everything else in this session.
   **Three gate runs, a 54-trial Gazebo campaign and two browser sessions have
   now gone past it.** Nothing blocks it.

9. **Accept the twenty-seven open items explicitly**, particularly `use_sim_time`
   — **re-checked and still set by nothing**, with `/clock`, `gz.msgs.Clock` and
   `rosgraph_msgs` at zero occurrences repo-wide. Every duration in this system,
   including `MissionProgress.elapsed_sim_time`, is wall clock. That outlives
   Phase 5.

**A closing note on what changed and why it should be trusted more than the last
revision.** The previous disposition said the gap was "evidence, not code". It
was half right. Running the system produced the evidence — and it also produced
**five defects that no amount of reading would have found**: a crater nobody had
measured, a depot marker that wedged a scout and deadlocked the fleet, a legend
whose labels collided into `unsure5 wt% shownconfident`, an alarm that fired
below its own printing precision, and a hauler that reported a perfect delivery
241 m from where it stood. **Four of the five were invisible to a green test
suite, and one of them made every haul in the system impossible.** The register's
own rule — that a passing test is not a demonstration — was, if anything,
understated.

**A second closing note, 2026-08-01, because the lesson this session taught is
not the same one.** Every defect above came from *running the system*. Four of
this session's five new deviations came from **running the checking apparatus** —
a CI job that had never fired and failed on its own configuration (D-38), a
preflight script whose gravity line printed OK against an empty string (D-39), a
view whose animation loop had never once started while its header and stats
panel showed correct numbers (D-40), and a simulator crash that manufactured
four "cannot climb" results indistinguishable from real ones (D-41). **In each
case the instrument, not the system, was the thing that was wrong, and in three
of the four the instrument was reporting success.**

And the largest single finding is of the same species. D-28 had been read for
two days as "the planner ignores a slope limit". It was not: it was **a limit
nobody had measured, expressed in the wrong quantity.** The measured limit is
20°, the wall is 34°, and both numbers are right — because a vehicle climbs
along its own heading and not along the fall line. **A limit enforced per cell
would have refused the entire mission; the same limit enforced per step admits
it.** The register carried a correct observation attached to a wrong model of
what it meant for four revisions, and only measuring the vehicle settled it.

**What has not moved: D-37's cause is unknown, D-42's cause is unknown, RViz2
has never been started, and the gate does not pass.**
