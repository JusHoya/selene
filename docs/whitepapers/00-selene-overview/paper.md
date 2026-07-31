---
title: "SELENE: An Integrated Architecture for Autonomous Multi-Robot Fleet Coordination in Lunar In-Situ Resource Utilization"
author:
  - "SELENE Project"
affiliation: "Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation"
date: "April 2026"
paper-number: "WP-00"
abstract: |
  Sustainable human presence on the Moon demands autonomous extraction, processing, and transportation of lunar resources — a discipline known as In-Situ Resource Utilization (ISRU). Current approaches address individual facets of the ISRU pipeline — prospecting, excavation, or transport — but no operational system integrates the full value chain under a unified, delay-tolerant, multi-robot coordination framework. We present SELENE (Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation), a software architecture that orchestrates a heterogeneous fleet of autonomous lunar surface robots across the complete ISRU pipeline. SELENE introduces six novel technical contributions: (1) a Hierarchical Task Network planner with virtual task resolution for mission decomposition, (2) a market-based auction mechanism with energy-aware bid scoring, (3) a Bayesian spatial grid fusion algorithm for probabilistic resource mapping, (4) an information-gain adaptive survey planner, (5) a Robot Capability Descriptor Language for hardware-agnostic fleet management, and (6) a conservation-invariant material tracking ledger. SELENE is implemented in approximately 6,600 lines of production Python atop ROS 2 (plus a 4,000-line React dashboard), targeting a four-robot heterogeneous fleet performing ice prospecting, site selection, excavation, and hauling in a permanently shadowed crater environment. All components are covered by a passing Python unit-test suite. We are explicit about maturity: the system has not yet cleared its integration exit gate in Gazebo Harmonic. Two of the six contributions --- the adaptive survey planner and the material conservation ledger --- were implemented and unit-tested but invoked by nothing in the running orchestrator until 2026-07-30; both are now wired in (the planner on its own `adaptive_survey_replan_rate` timer, the ledger from the `MaterialEvent` and `TaskResult` subscriptions), so the gap this sentence used to record is closed in source and remains undemonstrated on a running system. This paper presents the integrated system architecture, design rationale, per-contribution implementation status, and positions each contribution against the current state of the art.
keywords: "lunar ISRU, multi-robot systems, fleet management, hierarchical task network, auction-based task allocation, Bayesian resource mapping, ROS 2"
---

# Introduction

The Artemis program and international lunar exploration initiatives have established a clear trajectory toward sustained human presence on the Moon within the next decade. A critical enabler for this vision is In-Situ Resource Utilization (ISRU) — the extraction and processing of lunar resources, particularly water ice in permanently shadowed regions (PSRs), to produce propellant, life support consumables, and construction materials. Without ISRU, every kilogram of consumable must be launched from Earth at costs exceeding \$1 million per kilogram to the lunar surface, rendering long-term habitation economically infeasible.

The ISRU value chain comprises four sequential phases: *prospecting* (locating and characterizing resource deposits), *extraction* (drilling or excavating raw material), *transport* (hauling material to processing facilities), and *processing* (refining raw material into usable products). Each phase demands specialized robotic capabilities, and the full pipeline requires tight coordination among heterogeneous agents operating under severe constraints: 1.3-second Earth-Moon communication latency, multi-minute communication blackouts, extreme thermal environments, limited onboard power, and the absence of GPS or pre-built infrastructure.

Despite significant progress in individual ISRU technologies — NASA's RASSOR excavator, ESA's PROSPECT drill, and various autonomous navigation systems — no existing system provides an integrated software framework for coordinating a heterogeneous robotic fleet across the complete ISRU value chain. This gap motivates SELENE.

## Contributions

SELENE makes the following contributions, each detailed in a companion white paper in this series:

1. **Hierarchical Task Network (HTN) Planning with Virtual Task Resolution** (WP-01): A mission decomposition algorithm that generates dependency-ordered tasks, including deferred "virtual" tasks that resolve by querying a probabilistic resource map.

2. **Market-Based Auction with Energy-Aware Bid Scoring** (WP-02): A decentralized task allocation protocol where robots bid on tasks using a scoring function that integrates spatial proximity, round-trip energy affordability, and capability matching.

3. **Bayesian Spatial Grid Fusion for Resource Mapping** (WP-03): A probabilistic resource map that fuses noisy sensor observations via conjugate Gaussian updates with distance-decayed spatial footprint weighting.

4. **Adaptive Survey Planning via Information Gain** (WP-04): A waypoint selection algorithm that balances exploration (high posterior variance), exploitation (neighboring resource signal), and travel cost.

5. **Robot Capability Descriptor Language (RCDL)** (WP-05): A YAML-based schema with model validation for declaratively describing heterogeneous robot capabilities, enabling hardware-agnostic agent software.

6. **Material Conservation Ledger** (WP-06): A material tracking system enforcing the invariant that total extracted material equals material in transit plus material deposited.

## Paper Organization

Section 2 presents the system architecture. Section 3 describes the fleet orchestration layer. Section 4 covers the agent autonomy layer. Section 5 details the hardware abstraction and ISRU process control layers. Section 6 presents the integrated mission execution workflow. Section 7 positions SELENE against the state of the art. Section 8 discusses current limitations and future work.

# System Architecture

## Design Principles

SELENE's architecture is governed by five principles derived from the operational constraints of lunar surface operations:

**Delay Tolerance.** The 1.3-second one-way light delay between Earth and Moon renders synchronous teleoperation infeasible for real-time robot control. SELENE's fleet must operate autonomously for extended periods, with Earth-side operators providing supervisory oversight rather than direct commands. All coordination protocols are designed with timeouts far exceeding the round-trip delay of the link they traverse — for the lunar-surface protocols (auction, heartbeat) that is the surface mesh, not the Earth-Moon link.

**Graceful Degradation.** No single robot failure should halt the mission. When a robot becomes unresponsive, its assigned tasks must be automatically recovered and re-allocated to remaining fleet members. The system must degrade proportionally — losing one of four robots should reduce throughput by approximately 25%, not 100%.

**Resource Awareness.** Lunar robots operate under severe energy constraints. In the modelled fleet, battery capacity ranges from 50 Wh (scout) through 65 Wh (hauler) to 80 Wh (excavator), declared in `selene_hal/config/{scout,hauler,excavator}.yaml`; solar recharging is unavailable in permanently shadowed regions. Every task allocation decision must account for whether a robot can reach the task, execute it, *and return to a recharging station* before its battery reaches critical levels.

**Hardware Agnosticism.** The same orchestration software must coordinate robots with fundamentally different capabilities — from neutron spectrometers on scouts to 200W drills on excavators to 50 kg transport bins on haulers. The software architecture must abstract hardware differences behind uniform interfaces.

**Extensibility.** New robot types, sensor modalities, ISRU processes, and even celestial bodies must be accommodable without re-architecting the system.

## Layered Architecture

SELENE employs a four-layer architecture, illustrated in Figure 1.

![SELENE System Architecture. The four-layer design separates concerns between Earth-side supervision, lunar-side fleet coordination, per-robot autonomy, and hardware abstraction.](figures/system_architecture.png){width=100%}

**Mission Control Layer (Earth-Side).** Provides a web-based dashboard (React 18, 2D HTML canvas rendering) for supervisory control and mission monitoring. Operators can monitor fleet state, inject tasks, override robot behavior, and view a heatmap built from incoming scout readings. A 3D digital-twin view is planned but not built: `three` is declared as a dashboard dependency but is imported by no source file, and the current fleet map is a top-down 2D canvas. This layer operates asynchronously — commands are queued and executed when communication windows permit.

**Fleet Orchestration Layer (Lunar-Side).** The central coordination engine running on a lunar surface compute node. Comprises the HTN planner, task auction mechanism, resource map, fleet monitor, and adaptive survey planner. Operates at 2 Hz for auction ticks and 1 Hz for heartbeat monitoring and mission progress reporting.

**Agent Autonomy Layer (Per-Robot).** Each robot runs an independent autonomy stack including a finite state machine, energy manager, path planner (A* with cost grids), pure-pursuit path follower, and skill-based task execution modules. Agents operate independently during communication blackouts.

**Hardware Abstraction Layer (HAL) + ISRU Process Control.** Provides uniform sensor and actuator interfaces across heterogeneous robots. Robot capabilities are declared in YAML descriptors (RCDL) and validated at startup via Pydantic schemas. The ISRU process control layer tracks material flow with conservation invariant enforcement.

## Technology Stack

SELENE is implemented entirely in Python atop ROS 2, using Fast DDS (the default RMW) for inter-node communication. Continuous integration builds against Humble; the WSL2 development and validation path targets Jazzy. The simulation environment uses Gazebo Harmonic with custom lunar terrain and sensor configuration. The dashboard is a React application communicating via rosbridge WebSocket. Rust for safety-critical components, C++ for real-time paths, Isaac Sim, OpenUSD, and ONNX-based onboard inference are all part of the forward plan; none of them exist in the codebase today, and no claim in this paper depends on them.

Line counts below are `wc -l` over the non-test package source, measured at the time of writing.

| Component | Technology | Lines of Code |
|---|---|---|
| Orchestrator (`selene_orchestrator/selene_orchestrator/`) | Python / ROS 2 | 2,080 |
| Agent (`selene_agent/selene_agent/`) | Python / ROS 2 | 2,986 |
| HAL (`selene_hal/selene_hal/`) | Python / Pydantic | 1,559 |
| ISRU Process (`selene_isru/selene_isru/`) | Python | 157 |
| Messages (`selene_msgs/{msg,srv}/`) | ROS 2 IDL | 68 |
| Dashboard (`selene_dashboard/src/`) | React / JSX | 4,020 (+1,782 CSS) |

Table: SELENE implementation breakdown by component. Production package source only. Not counted here: 4,855 lines of Python unit tests across the four packages' `test/` directories, and 1,612 lines of Python in `selene_sim` (launch files, world generation, and sensor bridging).

# Fleet Orchestration Layer

The orchestration layer coordinates the fleet through five tightly integrated modules.

## HTN Planner

The HTN planner decomposes high-level mission objectives into primitive, auction-able tasks. A `collect_ice(zone, radius, quantity)` mission decomposes into:

1. **Survey phase**: Hexagonal grid waypoints within the target zone, sorted by distance from center (spiral-outward pattern), generating `prospect`-type tasks.

2. **Virtual site selection**: A non-auctioned placeholder task dependent on all survey tasks. When all surveys complete, the planner queries the Bayesian resource map, scoring each cell as $\text{score} = \mu / (1 + \sigma^2)$ to favor high concentration with low uncertainty.

3. **Extract-haul cycles**: Sequential `excavate` → `haul` task pairs generated based on the target quantity and hopper capacity (20 kg/load). Additional cycles are generated dynamically as the material ledger reports deposited quantities below the target.

![HTN Mission Decomposition with Virtual Task Resolution. Virtual tasks (purple) defer execution until sensor-derived conditions are met, enabling conditional task generation.](figures/htn_decomposition.png){width=80%}

The virtual task mechanism is, to our knowledge, a novel contribution to the HTN planning literature in the context of multi-robot ISRU systems. See WP-01 for the complete algorithmic treatment.

## Task Auction Mechanism

Task allocation uses a market-based auction protocol designed for delay-tolerant operation:

1. The orchestrator detects idle robots and pending tasks with satisfied dependencies.
2. A `TaskAnnouncement` is broadcast containing the task location, energy cost estimate, required capabilities, priority, and deadline.
3. Agents compute a bid score: $b = w_d \cdot \frac{1}{1 + d/\sigma_d} + w_e \cdot E_{\text{afford}} + w_c \cdot C_{\text{match}}$ with $\sigma_d = 100$ m and default weights $w_d = 0.4$, $w_e = 0.35$, $w_c = 0.25$ (`_on_task_announced` in `selene_agent/selene_agent/agent_node.py`, where `dist_score = 1.0 / (1.0 + distance / 100.0)`; weights are the `bid_weight_*` ROS parameters, declared and read by the **agent** (`agent_node.py:114-116` and `:629-641`) and set for a launched fleet in `selene_agent/launch/agent.launch.py`). This paper previously said they were set in `selene_orchestrator/config/orchestrator_params.yaml`; they sat there until 2026-07-31 and configured nothing, because the orchestrator declares none of the three and ROS 2 drops an undeclared override silently — deviation D-13. The numbers above are unchanged; only the file that actually feeds them is. WP-02 explains why the inverse-linear proximity term was preferred over a Gaussian $e^{-d^2/2\sigma^2}$.
4. After a 5-second timeout, the orchestrator selects the highest-scoring bidder. Note that the auction is entirely lunar-surface-local, so the relevant latency budget is the surface mesh round-trip (sub-100 ms), not the 2.6-second Earth-Moon round trip; the 5-second window is sized for DDS re-discovery after a blackout rather than for Earth-in-the-loop bidding. WP-02 derives the figure.
5. If no bids are received, the task is re-queued for future auction.

The bid score integrates three factors: spatial proximity (inverse-linear decay with distance), energy affordability (whether the robot can execute the task and return to base with a 10% safety margin), and capability match (binary: does the robot's RCDL descriptor include the required capability?). See WP-02 for the energy model and scoring analysis.

![Task Auction Protocol. The 5-second bid window is set two orders of magnitude above the lunar-surface mesh round-trip time, so bidding survives transient DDS re-discovery after a communication blackout.](figures/auction_sequence.png){width=80%}

## Probabilistic Resource Map

The resource map maintains a 500 $\times$ 500 grid (1 m resolution) where each cell stores a posterior mean $\mu$, posterior variance $\sigma^2$, and observation count. When a scout reports a neutron spectrometer reading at position $(x, y)$, the map updates all cells within a 5-meter footprint radius using Bayesian Gaussian-Gaussian conjugate formulae:

$$\tau_{\text{post}} = \tau_{\text{prior}} + w \cdot \tau_{\text{obs}}$$
$$\sigma^2_{\text{post}} = 1 / \tau_{\text{post}}$$
$$\mu_{\text{post}} = \sigma^2_{\text{post}} \cdot (\tau_{\text{prior}} \cdot \mu_{\text{prior}} + w \cdot \tau_{\text{obs}} \cdot z)$$

where $\tau = 1/\sigma^2$ denotes precision, $z$ is the observation value, and $w = \exp(-r^2 / 2\sigma_f^2)$ is the distance-decayed footprint weight at distance $r$ from the sensor. This yields O(1) updates per observation — critical for resource-constrained processors. See WP-03 for the complete derivation and convergence analysis.

## Adaptive Survey Planner

Rather than surveying on a static grid, SELENE's adaptive survey planner selects waypoints to maximize information gain. Each candidate waypoint is scored:

$$S = w_v \cdot \hat{\sigma}^2 + w_s \cdot \hat{N} - w_d \cdot \hat{d}$$

where $\hat{\sigma}^2$ is the normalized posterior variance (exploration), $\hat{N}$ is the normalized average neighbor ice concentration (exploitation), and $\hat{d}$ is the normalized distance from the robot (cost). Hats denote cross-candidate normalization. This three-term formulation explicitly balances exploration of unknown regions, exploitation near detected deposits, and energy-efficient routing.

**Status: implemented and unit-tested, not yet integrated.** The planner is a standalone module with 8 passing unit tests, and `OrchestratorNode.__init__` assigns `self._adaptive_survey = AdaptiveSurveyPlanner(self._resource_map)` — but that is the attribute's only appearance in the file; no method on it is ever called, and `select_next_waypoint` has no call site outside its own tests. Every survey waypoint in the current build comes from the static hexagonal grid described above, capped at `SURVEY_WAYPOINT_COUNT = 10` (`htn_planner.py:28`). Wiring the planner into the survey phase is outstanding work and is not yet validated in simulation. See WP-04 for the complete formulation and comparison with pure information-gain approaches.

## Fleet Monitor

The fleet monitor tracks robot state via heartbeat messages at 2 Hz. If a robot's heartbeat exceeds a 10-second timeout, it is marked offline and its assigned tasks are reverted to PENDING status for re-auction. This provides automatic, human-free task recovery — essential when Earth-side operators may be minutes away from awareness of a failure.

# Agent Autonomy Layer

## Finite State Machine

Each robot's lifecycle is governed by an event-driven FSM with 9 states (`IDLE`, `BIDDING`, `ASSIGNED`, `NAVIGATING`, `WORKING`, `RETURNING`, `RECHARGING`, `ERROR`, `OFFLINE`) and 17 events, with explicit transition rules (`selene_agent/selene_agent/fsm.py`). The FSM supports *wildcard transitions* for cross-cutting concerns: an `ENERGY_CRITICAL` event from any active state immediately transitions to `RETURNING`, and a `FAULT` event transitions to `ERROR`. This ensures safety-critical behaviors override task execution regardless of the agent's current activity.

The FSM is implemented as a pure Python module with zero ROS dependencies, enabling isolated unit testing of the complete state space.

## Energy Manager

The energy manager models task affordability as a multi-leg budget:

$$E_{\text{total}} = E_{\text{go}} + E_{\text{task}} + E_{\text{return}}$$

where each leg accounts for locomotion power, idle draw, and speed-dependent consumption. A 10% safety margin is applied:

$$E_{\text{budget}} = 1.1 \times E_{\text{total}}$$

A robot will not bid on a task unless $E_{\text{remaining}} \geq E_{\text{budget}}$. If battery level falls below 15% during any activity, the `ENERGY_CRITICAL` wildcard fires, aborting the current task and initiating return to the recharging station.

## Skill-Based Task Execution

Complex multi-phase behaviors are encapsulated as *skills* — composable state machines orthogonal to the agent FSM. Four skills are implemented:

- **ProspectSkill**: Navigate → Settle (1s) → Sense (2s, 20 readings) → Record
- **ExcavateSkill**: Navigate → Position → Drill (until hopper full or timeout) → Stop
- **HaulSkill**: Navigate to pickup → Load → Navigate to depot → Unload
- **RechargeSkill**: Navigate to station → Charge to 90%

Each skill reports progress (0.0–1.0) to the orchestrator, enabling fleet-level situational awareness. Skills are HAL-agnostic — they access sensors and actuators exclusively through abstract interfaces.

# Hardware Abstraction and ISRU Process Control

## Robot Capability Descriptor Language (RCDL)

SELENE introduces RCDL, a YAML-based schema for declaratively describing robot capabilities. Each descriptor specifies the robot's kinematic model, maximum speed, mass, battery profile (capacity, idle draw, locomotion draw), sensor suite (type, range, noise characteristics, power draw), actuator suite (type, capacity, power), and capability tags.

Descriptors are validated at startup using Pydantic v2 model validators, catching misconfigurations before they cause runtime failures. The HAL factory constructs the appropriate sensor and actuator interface implementations based on the parsed descriptor. See WP-05 for the schema specification and validation rules.

![Heterogeneous Fleet Composition. Each robot type has distinct capabilities, energy profiles, and physical constraints declared via RCDL descriptors.](figures/fleet_composition.png){width=100%}

## Material Conservation Ledger

The ISRU process control layer maintains a material conservation ledger tracking three quantities: extracted (at sites), in-transit (on robots), and deposited (at depot). The system enforces the invariant:

$$m_{\text{extracted}} = m_{\text{in\_transit}} + m_{\text{deposited}} \pm \epsilon$$

where $\epsilon = 0.01$ kg is the numerical tolerance. The intent is that violations trigger alerts, enabling early detection of accounting errors or sensor drift. The extraction rate model incorporates ice concentration, drill power fraction, and depth penalty.

**Status: implemented and unit-tested, not yet integrated.** No production code path calls `record_extraction`, `record_load`, or `record_unload`, so the ledger holds zeros at runtime and the `extracted`/`in_transit`/`deposited` fields of `MissionProgress` publish 0.0. `check_conservation` has no production caller, and as written it would report a violation throughout extraction because the three-account model has no *at-site* term (`selene_isru/selene_isru/inventory.py:142`--`149`). WP-06 gives the conservation proof, the rate model analysis, and the four-account correction required to close that gap.

# Integrated Mission Execution

![ISRU Value Chain Pipeline. SELENE orchestrates the full sequence from prospecting through deposition, with dynamic cycle expansion based on material tracking.](figures/isru_pipeline.png){width=100%}

A complete SELENE mission proceeds as follows:

1. **Mission initialization.** The HTN planner decomposes `collect_ice(zone_center, zone_radius, target_kg)` into survey waypoints + virtual site selection + initial extract-haul cycles.

2. **Survey phase.** Survey tasks are auctioned to scouts. Each scout navigates to its assigned waypoint, activates the neutron spectrometer, records ice concentration readings, and publishes `ResourceMapUpdate` messages. The Bayesian resource map fuses these readings, progressively reducing uncertainty.

3. **Adaptive replanning** *(designed, not yet in the loop)*. The intent is that between auctions the adaptive survey planner evaluates whether additional waypoints should be generated based on the current knowledge map state. In the current build this step does not execute: the planner is constructed but never invoked, so the survey consists solely of the 10 fixed hexagonal waypoints produced in step 1.

4. **Site selection.** When all survey dependencies are satisfied, the virtual `select_site` task resolves by querying the resource map. The cell with the highest $\mu/(1+\sigma^2)$ score is selected as the extraction site.

5. **Extraction-transport cycles.** Excavate tasks are auctioned to excavators; haul tasks to haulers. Each excavate-haul cycle is dependency-linked, enforcing temporal ordering. The material ledger is intended to track mass flow here; today no code path writes to it (see the ledger status note above).

6. **Dynamic cycle expansion.** At 1 Hz, the HTN planner checks whether deposited mass meets the target and generates additional excavate-haul cycles on demand if not. Its deposited-mass figure is currently derived as (completed haul tasks) $\times$ 20 kg (`htn_planner.py:325`--`333`), not read from the ledger, so it assumes every completed haul delivered a full hopper.

7. **Mission completion.** When $m_{\text{deposited}} \geq m_{\text{target}}$, the mission is marked complete. All robots return to idle.

Throughout execution, the fleet monitor detects unresponsive robots and recovers their tasks. Energy-critical robots abort tasks and recharge autonomously. The dashboard visualizes fleet state, mission progress, and task auctions in real time.

One point about the resource map deserves precision, because it is easy to overstate in either direction. **The orchestrator's fused Bayesian posterior grid is published, and it reaches both viewers, as of 2026-07-30.** `selene_orchestrator/selene_orchestrator/orchestrator_node.py` now makes seven `create_publisher` calls: the original four (`task_announcement`, `task_assignment`, `alerts`, `mission_progress`), plus `/orchestrator/resource_map` (`selene_msgs/msg/ResourceMap`, the posterior mean, variance and observation count, sparse-encoded over observed cells), `/orchestrator/resource_map_markers` (a `visualization_msgs/MarkerArray` CUBE_LIST overlay for RViz2, hue carrying concentration and alpha carrying certainty), and `/orchestrator/task_queue`. Both map topics are built from ONE snapshot on ONE timer driven by `resource_map_publish_rate` (default 0.5 Hz) — the parameter that had been declared and never read, which is why FR-MAP-4 went unimplemented for two phases. `selene_orchestrator/test/test_no_orphan_parameters.py` now fails the build on any parameter declared but never read. RViz2 is configured for it: `selene_sim/rviz/selene_sim.rviz` carries a `MarkerArray` display bound to `/orchestrator/resource_map_markers` with `Fixed Frame: map`, which must stay equal to `resource_map_frame_id` because nothing in this repository publishes TF. The dashboard heatmap renders the fused posterior too, with no silent fallback to the raw readings: when no snapshot has arrived it draws nothing and says so. The raw per-reading `ResourceMapUpdate` stream on `/orchestrator/map_update` is still published by scouts (`_publish_map_update` in `selene_agent/selene_agent/agent_node.py`) and is still consumed client-side, but only by the concentration-vs-time trace in `ResourceGraph.jsx`, which wants individual samples rather than a fused estimate. This paragraph previously said the posterior was on no topic, that `resource_map_publish_rate` was never read, and that `selene_sim/rviz/selene_sim.rviz` contained only Grid and TF displays. All three were true when written and none is true now. **What is still outstanding, stated plainly:** none of the above has been photographed. No RViz2 window and no browser has been opened by anyone who wrote this, so the claim is that both renderers are provably the same function of the same snapshot (`selene_orchestrator/test/test_dashboard_colour_parity.py`), not that the two pictures have been compared side by side — which is what PRD exit-gate row 2 actually asks for and is a human method. Separately, `ResourceMapUpdate.location` comes from `/odom`, which DiffDrive dead-reckons from each robot's spawn pose rather than from world coordinates, so the map is internally consistent but the region it describes is not where the robot physically is; that is tracked on its own and is untouched by the publishing work.

![SELENE Mission Control Dashboard showing fleet map with robot positions, PSR survey zone, depot location, mission status metrics, and fleet status cards.](screenshots/dashboard_full.png){width=100%}

# State of the Art

## Comparison with Existing Systems

Table 2 compares SELENE against the most relevant existing systems across five architectural dimensions.

| System | Het. Fleet | Auction/HTN | ISRU Chain | Delay-Tolerant | ROS 2 |
|---|---|---|---|---|---|
| **SELENE** | Yes | Yes | Yes | Yes | Yes |
| NASA CADRE | No | No (leader) | No | Yes | No |
| NASA SRCP2 | Yes | No (central) | Yes | No | Yes |
| OffWorld | Yes | No (MARL) | Yes | Unknown | Unknown |
| ESA PRO-ACT | Yes | No (central) | Partial | No | No |
| DARPA SubT | Yes | Partial | No | Yes | Yes |
| Cat/Rio Tinto | Yes | No (MILP) | Yes (terr.) | No (GPS) | No |

Table: Comparison of SELENE with existing multi-robot coordination systems. No existing system occupies SELENE's complete design space. The SELENE row describes implemented architecture, not validated field performance — the comparison systems have flight or field records that SELENE does not.

**NASA CADRE** (launching 2026) demonstrates multi-robot autonomy with leader election and shared state, but operates a homogeneous fleet for mapping — not ISRU. **NASA SRCP2** (2019–2021) is the closest problem-domain match, using Scout/Excavator/Hauler roles in Gazebo, but employed centralized task assignment without HTN planning, Bayesian mapping, or auction-based allocation. **OffWorld Inc.** pursues heterogeneous swarm mining but uses multi-agent reinforcement learning rather than symbolic planning — a fundamentally different architectural approach. **DARPA SubT Challenge** teams independently validated SELENE's core component choices: CERBERUS used distributed auction, CoSTAR used Bayesian belief-space planning, and all teams designed for communication-degraded operation. However, no SubT team combined all three approaches, and none addressed the ISRU value chain.

## Novel Contributions

SELENE's primary novelty is the *system-level integration* of components that individually have precedent but have never been combined. Additionally, three specific algorithmic contributions appear novel:

1. **Virtual task resolution in HTN**: Non-auctioned placeholder tasks that resolve by querying a probabilistic resource map, enabling conditional task generation based on sensor-derived state. Not found in prior HTN, MRTA, or ISRU literature.

2. **Dynamic cycle expansion**: Closed-loop integration of HTN planning with material conservation tracking, generating extraction cycles on demand based on real-time deposited mass.

3. **Three-term adaptive survey scoring**: The combination of posterior variance, neighbor signal exploitation, and distance cost in a single weighted scoring function with cross-candidate normalization.

# Limitations and Future Work

**Validation status --- stated plainly.** Every component is covered by a passing Python unit-test suite, run per-package. SELENE has *not* yet cleared its integration exit gate. The Sprint 0 plan (`docs/PRD.md`) defines six phases; Phases 1--4 are implemented, Phase 5 (dashboard and integration) is implemented in code but its exit gate has not been passed, and Phase 6 (polish, hardening, NFR validation, integration demos) has not started. The Phase 5 gate is an executable script, `scripts/validate_phase5.sh`, requiring WSL2 with ROS 2 Jazzy and a built colcon workspace; no `phase5_validation_report.md` is committed, so this repository contains no recorded evidence of an end-to-end Gazebo run. Readers should treat every behavioural claim in this series as either unit-tested (where stated) or as design intent (where stated), and none as simulation-validated.

**Known integration gaps.** Three items are implemented but not wired into the running system, and each is called out in the relevant section above: (1) the adaptive survey planner is never invoked, so surveys use a fixed 10-waypoint hexagonal sample; (2) the material conservation ledger has no production writers, so it reports zeros at runtime, and its conservation check would in any case misfire during extraction for want of an at-site account; (3) the fused Bayesian resource map is not published on any topic, so neither the dashboard nor RViz2 can display posterior mean or variance (FR-MAP-4 is unimplemented).

**Other limitations.** The flat-terrain model does not capture the full complexity of PSR terrain (boulders, steep crater walls, permanent shadow). The communication model assumes reliable DDS messaging without modeling RF propagation, signal attenuation, or multi-path effects. The fleet size (4 robots) is small; scalability to dozens of agents remains untested. There is no benchmark harness in the repository, so no comparative performance figures are reported anywhere in this series.

**Planned extensions (Sprint 1 and beyond).** The items below are *not* the Phase 4/5/6 of the Sprint 0 plan --- that numbering is reserved and defined in `docs/PRD.md`. These are post-Sprint-0 candidates, in rough priority order: closing the three integration gaps above; multi-mission planning (concurrent ice and regolith oxygen extraction); predictive maintenance and learned terrain cost models via onboard ML inference; and porting safety-critical components to Rust alongside integration with Space ROS for flight qualification pathways. No code exists for any of these.

**Toward flight readiness.** The path from simulation prototype to flight software requires: (1) integration with Space ROS and F-Prime for DO-178C alignment, (2) hardware-in-the-loop testing with physical rover platforms, (3) terrain model validation using orbital data (LOLA, Diviner, Mini-RF), and (4) communication protocol alignment with NASA LunaNet DTN specifications.

# Conclusion

SELENE sets out an architecture in which the complete ISRU value chain — from prospecting through deposition — is autonomously orchestrated by a heterogeneous robotic fleet, combining HTN planning with virtual task resolution, market-based task allocation with energy-aware bidding, Bayesian resource mapping, and information-gain adaptive surveying. Four of the six contributions are implemented and integrated end to end in code; two (adaptive survey planning and the conservation ledger) are implemented and unit-tested but not yet invoked by the orchestrator. The architecture's delay-tolerant, fault-resilient design addresses the fundamental operational constraints of lunar surface operations, and the hardware-agnostic HAL and RCDL layers give a concrete path toward physical platforms. What remains is the work that turns an architecture into evidence: closing the three integration gaps, passing the Phase 5 exit gate in Gazebo Harmonic, and building the benchmark harness that would let the design claims in the six companion white papers be measured rather than argued. Those papers provide the detailed algorithmic treatment of each contribution, each with its own implementation-status statement.

# References

1. G. Sanders et al., "Progress Review: NASA In-Situ Resource Utilization (ISRU) Development & Incorporation — 2019 to 2025," NASA TM, 2025.
2. D. Nau et al., "SHOP2: An HTN Planning System," JAIR, vol. 20, pp. 379–404, 2003.
3. R. Zlot and A. Stentz, "Market-Based Multirobot Coordination for Complex Tasks," Int. J. Robotics Research, vol. 25, no. 1, pp. 73–101, 2006.
4. M. B. Dias and A. Stentz, "TraderBots: A New Paradigm for Robust and Efficient Multirobot Coordination in Dynamic Environments," CMU-RI-TR-03-19, 2003.
5. H. Choi, L. Brunet, and J. How, "Consensus-Based Decentralized Auctions for Robust Task Allocation," IEEE Trans. Robotics, vol. 25, no. 4, pp. 912–926, 2009.
6. S. Chien et al., "Using Autonomy Flight Software to Improve Science Return on Earth Observing One," J. Aerospace Computing, 2005.
7. "Multi-robot cooperation for lunar In-Situ resource utilization," Frontiers in Robotics and AI, vol. 10, 2023.
8. "CADRE: Planning, Scheduling, and Execution for Multi-Robot Lunar Exploration," arXiv:2502.14803, 2025.
9. "Space ROS: An Open-Source Framework for Space Robotics," AIAA SciTech 2023-2709, 2023.
10. S. Thrun, W. Burgard, and D. Fox, "Probabilistic Robotics," MIT Press, 2005.
11. "LunarMiner: A Nature-Inspired Swarm Robotics Framework for Lunar Water Ice Extraction," Biomimetics, vol. 9, no. 11, 2024.
12. "Informative Path Planning to Explore and Map Unknown Planetary Surfaces," arXiv:2503.16613, 2025.
