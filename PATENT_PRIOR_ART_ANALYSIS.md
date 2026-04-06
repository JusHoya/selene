# SELENE Patent Prior Art Analysis & Novelty Assessment

**Date:** 2026-04-05
**Subject:** AI-Driven Lunar ISRU Fleet Management Software Suite
**Purpose:** Identify prior art, assess patentability, and define verifiably unique claims

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [SELENE System Overview](#2-selene-system-overview)
3. [Market Landscape — Competing Systems](#3-market-landscape)
4. [Patent Landscape](#4-patent-landscape)
5. [Academic Prior Art](#5-academic-prior-art)
6. [Element-by-Element Novelty Analysis](#6-element-by-element-novelty-analysis)
7. [SELENE's Verifiably Unique Contributions](#7-selenes-verifiably-unique-contributions)
8. [Recommended Patent Claims](#8-recommended-patent-claims)
9. [Freedom-to-Operate Considerations](#9-freedom-to-operate-considerations)
10. [Recommendations & Next Steps](#10-recommendations--next-steps)

---

## 1. Executive Summary

### Finding

**No existing system, patent, or published work integrates all of the following into a single unified framework:**

1. Hierarchical Task Network (HTN) planning with virtual task resolution for ISRU missions
2. Market-based auction task allocation with energy-aware bid scoring
3. Bayesian spatial grid fusion with distance-decayed footprint for probabilistic resource mapping
4. Information-gain adaptive survey planning driven by posterior variance
5. Delay-tolerant multi-robot coordination designed for 1.3s+ communication latency
6. Hardware-agnostic Robot Capability Descriptor Language (RCDL) with schema validation
7. Full ISRU value chain orchestration (prospect -> extract -> haul -> process) with material conservation tracking
8. Composable skill-based multi-phase task execution decoupled from agent lifecycle FSM

Individual elements have precedent in the literature. The **system-level integration** and several **specific algorithmic combinations** are novel.

### Closest Existing Systems

| System | Overlap | Key Gap vs. SELENE |
|--------|---------|-------------------|
| NASA SRCP2 solutions | Scout/Excavator/Hauler + ROS + Gazebo, same problem domain | Simulation only; central planner (not auction); no HTN; no Bayesian mapping; no adaptive survey |
| NASA CADRE | Multi-robot autonomy, leader election, delay-tolerant | No ISRU process chain; homogeneous rovers; no auction bidding |
| OffWorld Inc. | Heterogeneous swarm, full ISRU chain, ML-based | Proprietary; no published architecture; terrestrial-first; no HTN/Bayesian details |
| ESA PRO-ACT | Heterogeneous robots, cooperative ISRU tasks | Assembly-focused (not extraction); no delay tolerance; no auction; centralized planner |
| REALMS2 | Multi-robot ROS 2 prospection, field-tested | Prospection only (no extraction/hauling); no auction; no HTN; teleoperation fallback |
| JPL ASPEN/CASPER | Flight-proven autonomous planning, delay-tolerant | Single-agent focus; no multi-robot auction; no ISRU process chain |

### Patentability Assessment

| Claim Area | Novelty | Non-Obviousness | Utility | Patentable? |
|------------|---------|-----------------|---------|-------------|
| Integrated HTN + Auction + Bayesian Map system | HIGH | HIGH | HIGH | **Strong candidate** |
| Virtual task resolution in HTN for ISRU | MODERATE-HIGH | HIGH | HIGH | **Strong candidate** |
| Energy-aware auction bidding with round-trip affordability | MODERATE | MODERATE-HIGH | HIGH | **Good candidate** |
| Adaptive survey via information-gain on Bayesian grid | MODERATE | MODERATE | HIGH | Defensible with specific claims |
| RCDL with Pydantic validation for space robots | MODERATE | MODERATE | HIGH | Defensible with specific claims |
| Material conservation ledger for ISRU | MODERATE | LOW-MODERATE | HIGH | Weak standalone; strong as dependent claim |
| Skill-based execution decoupled from agent FSM | LOW-MODERATE | LOW | HIGH | Prior art exists; narrow claims possible |

---

## 2. SELENE System Overview

SELENE is a ~5,000-line Python + ROS 2 software suite comprising four core packages:

### Architecture Layers
```
MISSION CONTROL (Earth) --- 1.3s delay --- FLEET ORCHESTRATION (Lunar)
                                            |
                            +---------------+---------------+
                            |               |               |
                         Agent           Agent           Agent
                         (Scout)        (Excavator)     (Hauler)
                            |               |               |
                         HAL Interface   HAL Interface   HAL Interface
                            |               |               |
                      Gazebo/Hardware  Gazebo/Hardware  Gazebo/Hardware
```

### Core Algorithms

1. **HTN Planner** (344 LoC) -- Decomposes missions into survey -> virtual site selection -> excavate/haul cycles with dynamic cycle expansion
2. **Task Auction** (63 LoC) -- Market-based allocation with timeout-based synchronization
3. **Resource Map** (123 LoC) -- Bayesian Gaussian conjugate updates with spatial footprint
4. **Adaptive Survey** (256 LoC) -- Information-gain waypoint scoring: `w_var * variance + w_sig * neighbor_signal - w_dist * distance`
5. **Agent FSM** (201 LoC) -- Event-driven state machine with wildcard transitions for ENERGY_CRITICAL/FAULT
6. **Energy Manager** (146 LoC) -- Round-trip affordability checks with safety margin
7. **Navigator** (300+ LoC) -- A* with cost grids + pure pursuit path following
8. **Skills** (prospect, excavate, haul, recharge) -- Multi-phase composable task execution
9. **HAL + RCDL** (500+ LoC) -- YAML descriptors with Pydantic validation, abstract sensor/actuator interfaces
10. **Material Inventory** (158 LoC) -- Conservation-invariant material ledger
11. **Fleet Monitor** (83 LoC) -- Heartbeat timeout detection + automatic task recovery
12. **Task Queue** (144 LoC) -- Dependency-aware FIFO with robot failure recovery

---

## 3. Market Landscape

### 3.1 Commercial Companies

#### OffWorld Inc. (Pasadena, CA + Luxembourg)
- **Status:** Prototype/early commercial (terrestrial contracts; lunar demo ~2027)
- **Approach:** AI-powered swarm mining with heterogeneous "species" of robots on a common 53 kg chassis. Edge computing, ML-based coordination, no central server.
- **Overlap with SELENE:** Highest. Multi-species fleet for full ISRU chain.
- **Key Difference:** ML/RL-based coordination (vs. SELENE's HTN + auction); proprietary architecture; no published delay-tolerant protocol; terrestrial-first.
- **IP Status:** Proprietary. Patents likely but not publicly detailed.

#### Lunar Outpost (Golden, CO)
- **Status:** Flight-proven (MAPP on IM-2, March 2025)
- **Approach:** Modular MAPP rover platform (5-250 kg variants). Autonomous navigation. No fleet orchestration layer published.
- **Overlap with SELENE:** MAPP is a candidate hardware platform. No fleet management software.

#### Astrobotic Technology (Pittsburgh, PA)
- **Status:** Flight-ready (CubeRover certified)
- **Approach:** Standardized modular rovers, multi-unit deployment from lander, wireless charging.
- **Overlap with SELENE:** Hardware platform only. No fleet coordination or ISRU software.

#### Caterpillar Inc.
- **Status:** Concept/technology transfer (terrestrial autonomous mining operational)
- **Approach:** Adapting terrestrial autonomous haul truck fleet management for lunar. GPS-based coordination, AI diagnostics.
- **Overlap with SELENE:** Terrestrial fleet management is closest industrial analog. GPS-dependent (not applicable to Moon). Sponsoring NASA Lunabotics.
- **Key Difference:** Requires GPS infrastructure; centralized dispatch; not designed for heterogeneous ISRU roles.

#### Other Companies
- **ispace:** Long-term ISRU business model, swarm micro-rovers planned but conceptual
- **Intuitive Machines:** Lander/infrastructure provider, delivering CADRE on IM-3
- **Blue Origin / Honeybee Robotics:** Landers + excavation tools (TRIDENT, PlanetVac), no fleet coordination

### 3.2 Government Programs

#### NASA CADRE (Cooperative Autonomous Distributed Robotic Exploration)
- **Status:** Launching 2026 on IM-3
- **Approach:** 3 homogeneous rovers + base station. Novel Planning, Scheduling & Execution (PS&E) with leader election, shared state database, strategic planner, agent controllers. Built on JPL F-Prime with ROS bridge. Fully autonomous, no Earth control needed.
- **Overlap with SELENE:** Multi-robot autonomy, delay-tolerance, fault-tolerant coordination.
- **Key Differences:** (1) Homogeneous fleet (no role specialization), (2) No ISRU process chain, (3) Leader election (vs. SELENE's auctioneer model), (4) Mapping mission only, (5) F-Prime (vs. ROS 2 native).

#### NASA SRCP2 (Space Robotics Challenge Phase 2, 2019-2021)
- **Status:** Completed (simulation competition)
- **Approach:** Teams coordinated Scout/Excavator/Hauler robots in Gazebo for lunar ISRU. Central task planner + decentralized FSMs. ROS-based.
- **Overlap with SELENE:** Near-identical problem domain and robot role decomposition.
- **Key Differences:** (1) Central task assignment (not auction-based), (2) No HTN planning, (3) No Bayesian resource mapping, (4) No adaptive survey, (5) No delay-tolerant design, (6) Simulation only.

#### NASA IPEx (ISRU Pilot Excavator)
- **Status:** TRL 5 (testing at KSC)
- **Approach:** Single autonomous excavator (RASSOR heritage). Auto-dig algorithms. 10,000 kg/day target.
- **Overlap with SELENE:** Excavation autonomy. Single-robot, no fleet coordination.

#### ESA PROSPECT
- **Status:** Flight-ready for 2026 (IM Nova-C delivery)
- **Approach:** Drill + gas analysis payload. Single instrument, not a robot.
- **Overlap with SELENE:** ISRU demonstration (oxygen from regolith). No fleet coordination.

#### ESA PRO-ACT (EU H2020, DFKI Bremen)
- **Status:** Research completed (physical hardware demonstrations)
- **Approach:** 3 heterogeneous robots (wheeled manipulator, hexapod walker, gantry) for ISRU plant assembly. Cooperative mission planner.
- **Overlap with SELENE:** Heterogeneous fleet for ISRU tasks with cooperative planning.
- **Key Differences:** (1) Assembly-focused (not extraction), (2) No auction mechanism, (3) Centralized planner, (4) No delay-tolerant design, (5) No Bayesian resource mapping.

#### CNSA / ILRS
- **Status:** Chang'e 8 ISRU demo ~2028; ILRS base ~2035
- **Approach:** Autonomous construction robots, tunneling rovers planned. Published details sparse.
- **Overlap with SELENE:** Long-term ISRU vision. No published fleet coordination architecture.

### 3.3 DARPA SubT Challenge — Closest Terrestrial Analog

The DARPA Subterranean Challenge (2018-2021) is the closest terrestrial analog to SELENE's operating environment: GPS-denied, communication-degraded, unknown terrain, heterogeneous robots. Key teams and their relevance:

#### Team CERBERUS (Competition Winner, ETH Zurich / UNR / NTNU)
- Heterogeneous fleet: ANYmal quadrupeds, aerial scouts, wheeled rovers
- **Used distributed auction** for frontier assignment -- robots bid on unexplored frontiers based on proximity and capability
- Designed for intermittent comms; robots operated autonomously during blackouts
- **Validates SELENE's auction-based approach** for comms-degraded environments

#### Team CoSTAR (JPL / MIT / Caltech)
- NeBula architecture: **belief-space planning under uncertainty**
- **Information-theoretic exploration** -- allocated robots to maximize information gain
- Closest to Bayesian resource mapping concepts
- **Validates SELENE's Bayesian mapping + information-gain survey approach**

#### Team Explorer (CMU)
- Centralized base station with decentralized fallback
- Utility-based allocation (similar to auction but centralized)
- Mesh network with breadcrumb communication relays

**Key finding:** No SubT team combined HTN + auction + Bayesian mapping. Each of SELENE's core components is independently validated by different SubT teams, but the integration is unique:
- Auction allocation validated by CERBERUS
- Bayesian/information-gain exploration validated by CoSTAR
- Hierarchical planning used by all teams (though not formal HTN)
- Delay tolerance designed into all architectures

### 3.4 OffWorld Architecture Deep-Dive

Based on available information, OffWorld uses **multi-agent reinforcement learning (MARL)** for coordination rather than symbolic planning:
- Robots learn cooperative behaviors through simulation training
- Coordination emerges from learned policies, not explicit bidding
- **Not HTN-based** (neural policy networks, not symbolic decomposition)
- **Not auction-based** (implicit coordination from learned policies)
- **No evidence of Bayesian resource mapping** (sensor fusion with learned exploration)

This is a fundamental architectural divergence from SELENE. OffWorld's approach = learned coordination (data-driven). SELENE's approach = symbolic planning + market mechanisms (knowledge-driven). Both are valid; they are not the same invention.

### 3.5 Gap Analysis Summary

```
                    Heterogeneous  Autonomous    ISRU Process   Delay-      ROS 2
                    Fleet          Auction/HTN   Chain          Tolerant    Native
                    -----------    -----------   -----------    --------    ------
SELENE              YES            YES           YES            YES         YES
NASA CADRE          NO (homog.)    NO (leader)   NO             YES         NO (F')
NASA SRCP2          YES            NO (central)  YES            NO          YES*
OffWorld            YES            NO (MARL)     YES            UNKNOWN     UNKNOWN
ESA PRO-ACT        YES            NO (central)  PARTIAL        NO          NO
REALMS2             YES            NO            NO (prospect)  PARTIAL     YES
Caterpillar         YES            NO (MILP)     YES (terr.)    NO (GPS)    NO
DARPA SubT          YES            PARTIAL**     NO             YES         YES*
LunarMiner (acad.)  YES            NO (swarm)    PARTIAL        NO          NO

** CERBERUS used auction; CoSTAR used Bayesian info-gain; no team used HTN
```

**No existing system occupies SELENE's niche: all five columns marked YES.**

---

## 4. Patent Landscape

> **Note:** A professional freedom-to-operate search by a registered patent attorney is strongly recommended before filing. The following analysis covers patents identified through database research and training knowledge.

### 4.1 Feature-by-Feature Patent Search Results

#### Feature 1: Robot Capability Descriptor Language (RCDL)
**Result: NO DIRECT PATENT MATCH**

Closest existing patents:
- **US7801644B2** -- "Generic Robot Architecture" (Battelle Energy Alliance / Humatics Corp, filed 2006). Covers config files per robot type specifying sensors/actuators/APIs. Uses class hierarchies and API bindings, NOT declarative YAML with schema validation.
- **US7925381B2** -- "Hardware Abstraction Layer (HAL) for a Robot" (Evolution Robotics / iRobot, priority 2001). Uniform abstract for hardware aggregates. Does NOT describe declarative capability descriptors.
- **US7590680B2** -- "Extensible Robotic Framework and Robot Modeling" (Microsoft, filed 2006). Service-based capability abstraction via runtime discovery. Different paradigm from static YAML descriptors.
- **US10009410B2** -- "Description Files and Web Service Protocols for IoT" (Samsung). JSON-based device capability description. Closest conceptual match but targets IoT broadly, not heterogeneous robot fleets.
- **US10929759B2** -- "Intelligent Robot Software Platform". Uses Robot Plan Markup Language (RPML/XML). Focused on plan definition, not capability description.

**Assessment:** SELENE's YAML + Pydantic validation + energy profile integration is in clear space. Existing patents use fundamentally different mechanisms (class hierarchies, runtime services, XML markup).

#### Feature 2: Virtual Task Resolution in HTN
**Result: NO PATENT MATCH**

Related patents:
- **US7383100B2** -- "Extensible Task Engine Framework for Humanoid Robots" (Honda, filed 2006, active through 2026-12-14). Task/skill decomposition across heterogeneous robots. Does NOT include deferred/virtual tasks gated on sensor data completion.
- **WO2019234702A2** -- "Actor Model Based Architecture for Multi Robot Systems". Dynamic bid-value task allocation. Does NOT include non-auctioned placeholder tasks that resolve by querying probabilistic maps.

**Assessment:** The concept of a virtual task in an HTN -- a non-auctioned placeholder that resolves when upstream sensor dependencies complete, querying a probabilistic resource map to conditionally generate downstream tasks -- appears to be **novel and unpatented**.

#### Feature 3: Adaptive Survey with Information-Gain Scoring
**Result: NO PATENT MATCH FOR SPECIFIC FORMULA**

Related patents:
- **US9404756B2** -- "Adaptive Mapping with Spatial Summaries of Sensor Data" (iRobot). Uncertainty-driven grid management. Does NOT cover information-gain-weighted waypoint scoring for geological survey.
- **US20240168480A1** -- "Autonomous Mapping by a Mobile Robot". Multi-objective waypoint optimization. Different scoring approach.
- **US11119216B1** -- "Efficient Coverage Planning of Mobile Robotic Devices". Bayesian SLAM-based coverage. Different formulation.

**Assessment:** The specific three-term scoring formula (`w_var * variance + w_sig * neighbor_signal - w_dist * distance`) with cross-candidate normalization is not patented.

#### Feature 4: Energy-Aware Auction Bidding
**Result: NO DIRECT MATCH (components exist separately)**

Related patents:
- **US10089586B2 / WO2013119942A1** -- "Job Management System for Fleet of Autonomous Mobile Robots" (Adept Technology / Omron Corp). Selects robot based on proximity, velocity, battery charge, and sensor configuration. **Closest match.** However: uses centralized selection, NOT decentralized auction with bid scores.
- **WO2019234702A2** -- "Actor Model Based Architecture for Multi Robot Systems". Bid-value-based task allocation with robot utility function. Does NOT specify energy/battery as a bid component.
- **US20220269284A1** -- "Systems and Methods for Management of a Robot Fleet" (Yokogawa Electric, 2021). Capability-based fleet assignment. Not auction-based.

**Assessment:** Individual components (energy-aware robot selection, auction-based allocation) exist in separate patents. The specific combination of Gaussian distance decay + round-trip energy affordability + capability matching in a decentralized auction appears to be novel. **This is the highest-risk area** -- a patent examiner could argue obviousness from combining US10089586B2 (multi-factor selection) with WO2019234702A2 (bid-value auctions).

#### Feature 5: Bayesian Grid Fusion with Spatial Footprint
**Result: NO DIRECT MATCH**

Related patents:
- **WO2018009263A1** -- "Systems and Methods for Mapping an Environment". Bayesian grid updates with multi-sensor fusion. Does NOT describe spatial footprint modeling with distance-decayed weights.
- **US20140052687A1** -- "Probability Mapping System". Bayesian resource probability mapping (oil/gas). Does NOT describe conjugate Gaussian grid updates or spatial footprint.
- **US20200213426A1** -- "Spatial Data Processing System". VoxelNET for mineral resource modeling from robot/UAV data. Different approach (ray-casting, not conjugate updates).
- **DE102016206631A1** -- "Device for Data Fusion of Measured Data for Spatial Occupancy Grid". Evidence-based grid fusion. Different formulation.

**Assessment:** Bayesian occupancy grids are well-patented in autonomous vehicles, but focus on binary occupancy (obstacle/free), not continuous resource concentration. SELENE's combination of conjugate Gaussian updates + distance-decayed footprint + information-gain integration for adaptive planning is in clear space.

#### Feature 6: Material Conservation Ledger
**Result: NO PATENT MATCH**

Related patents:
- **US20210116889A1 / US12005588B2** -- "Industrial Robotic Platforms" (**Off-World, Inc.**). Covers lunar robot mining squads with extraction and processing stages. Does NOT describe material conservation accounting (extracted = in_transit + deposited).
- **US20100057254A1** -- "Methods for Using Robotics in Mining and Post-Mining Processing" (MI Robotic Solutions). Full mining value chain automation. No material flow tracking with conservation invariants.
- **US9234426B2** -- "Mine Operation Monitoring System" (Technological Resources Pty). Equipment tracking, not material mass balance.
- **US11143026B2** -- "Radiant Gas Dynamic Mining of Permafrost" (Trans Astronautica Corp). Lunar ISRU extraction technology. No material flow accounting.

**Assessment:** Conservation-invariant material flow tracking is novel in the autonomous mining/ISRU context.

### 4.2 Critical Patent to Monitor: OffWorld

**US20210116889A1 / US12005588B2** -- "Industrial Robotic Platforms" (Off-World, Inc.)
- Covers squads of industrial robots with autonomous communication and swarm behavior
- Describes lunar tanker bot, dozer bot, digger bot
- Mining squads for excavation, crushing, flotation processing
- **Does NOT cover:** HTN planning, auction-based allocation, Bayesian resource mapping, virtual tasks, energy-aware bidding, RCDL, material conservation ledger
- **Risk:** LOW for SELENE's specific claims. OffWorld's patent covers hardware platforms and swarm behavior, not the orchestration algorithms SELENE implements.

### 4.3 Patent Risk Summary

| SELENE Feature | Direct Patent Match? | Risk Level | Closest Threat |
|---|---|---|---|
| RCDL (YAML + Pydantic) | **No** | LOW | US7801644B2 (different paradigm) |
| Virtual tasks in HTN | **No** | **VERY LOW** | No close prior art found |
| Adaptive survey scoring | **No** | LOW | US9404756B2 (different formulation) |
| Energy-aware auction bidding | **No** | **LOW-MEDIUM** | US10089586B2 + WO2019234702A2 (components exist separately) |
| Bayesian grid + footprint | **No** | LOW | WO2018009263A1 (no footprint model) |
| Material conservation ledger | **No** | **VERY LOW** | No close prior art found |
| Integrated system | **No** | **VERY LOW** | No system combines all elements |

### 4.4 Recommendation

A formal freedom-to-operate (FTO) search should still be conducted by a registered patent attorney, focusing on:
- OffWorld Inc. patent portfolio (additional filings may exist beyond US12005588B2)
- Caterpillar autonomous mining fleet patents (for overlap with fleet coordination claims)
- Recent filings (2024-2026) in lunar ISRU autonomy
- Specific search terms detailed in [Appendix A](#appendix-a-recommended-patent-search-queries)

---

## 5. Academic Prior Art

### 5.1 Multi-Robot ISRU Architectures

| Publication | Year | Type | Key Contribution | Overlap with SELENE |
|-------------|------|------|-----------------|-------------------|
| "Multi-robot cooperation for lunar ISRU" (Frontiers) | 2023 | Simulation | Scout/Excavator/Hauler + central planner + volatile map + FSMs | **HIGH** -- same robot roles, same problem domain |
| PRO-ACT (EU H2020, DFKI) | 2020-2023 | Hardware demo | Heterogeneous robots for ISRU assembly | MODERATE -- different ISRU phase (assembly vs. extraction) |
| LunarMiner (Biomimetics) | 2024 | Simulation | Bio-inspired swarm ISRU, 40% time reduction | MODERATE -- alternative coordination paradigm |
| AIAA ASCEND Autonomous ISRU H2O | 2022 | Conceptual | Modular rovers for PSR water extraction | LOW-MODERATE -- conceptual only |

### 5.2 Auction-Based Task Allocation

| Publication | Year | Type | Key Contribution | Overlap with SELENE |
|-------------|------|------|-----------------|-------------------|
| Zlot & Stentz, Market-Based MRTA | 2006 | Implemented | Task trees + auction clearing for complex tasks | FOUNDATIONAL -- SELENE extends this |
| TraderBots (CMU) | 2003 | Implemented | Market economy paradigm, hybrid centralized/distributed | FOUNDATIONAL -- SELENE's auctioneer model |
| CBBA (MIT) | 2009+ | Implemented | Decentralized consensus-based bundle algorithm | MODERATE -- alternative to SELENE's centralized auction |
| Auction Sensitivity (Automatica) | 2023 | Theoretical | Robustness guarantees for auction allocations | LOW -- theoretical framework |

### 5.3 HTN Planning for Space

| Publication | Year | Type | Key Contribution | Overlap with SELENE |
|-------------|------|------|-----------------|-------------------|
| HTN-Timeline Spacecraft Scheduling | 2024 | Simulated | HTN + timeline-based resource conflict resolution | MODERATE -- resource scheduling overlap |
| SHOP2 | 2003 | Implemented | Foundational HTN planner | FOUNDATIONAL -- methodology basis |
| Multi-arm Space Robot HTN | 2022 | Simulated | HTN under space constraints | LOW -- single-system, not fleet |

### 5.4 Adaptive Survey / Information-Gain Planning

| Publication | Year | Type | Key Contribution | Overlap with SELENE |
|-------------|------|------|-----------------|-------------------|
| Informative Path Planning with GPs | 2022/2025 | Simulated | GP-based info-gain for planetary surface mapping | **HIGH** -- closest to SELENE's adaptive survey |
| Risk-Aware Lunar Coverage Planning | 2024 | Field-tested | Hybrid global/local energy-coverage planning | MODERATE -- different objective function |
| Adaptive Non-Stationary GP Info Gathering | 2024 | Simulated | Streaming sparse GPs for changing environments | LOW -- theoretical extension |
| Scarab Rover (CMU) | 2008 | Hardware | Physical prospecting rover for PSR survey | MODERATE -- single robot, no fleet |

### 5.5 Delay-Tolerant Autonomy

| Publication | Year | Type | Key Contribution | Overlap with SELENE |
|-------------|------|------|-----------------|-------------------|
| CASPER (JPL) | 1999+ | **Flight-proven** | Iterative repair for continuous replanning | MODERATE -- single-agent focus |
| ASPEN (JPL) | 1997+ | Operational | Strategic planning/scheduling framework | MODERATE -- ground-side planning |
| NASA DTN / LunaNet | 2003+ | Flight-tested | Store-and-forward networking for space | LOW -- infrastructure layer, not fleet coordination |
| MARTA (CMU) | 2007 | Field demo | Multi-level autonomy telesupervision | MODERATE -- adjustable autonomy concept |

### 5.6 ROS 2 for Space Robotics

| Publication | Year | Type | Key Contribution | Overlap with SELENE |
|-------------|------|------|-----------------|-------------------|
| Space ROS | 2022+ | Framework | Space-certifiable ROS 2 (DO-178C aligned) | LOW -- infrastructure, not algorithm |
| REALMS2 | 2023-2025 | Field-tested | Multi-robot ROS 2 prospection + mesh networking | **HIGH** -- closest operational system |
| VIPER Software (NASA Ames) | 2021 | Flight SW | ROS 2 + Gazebo + OpenMCT for lunar rover | MODERATE -- single robot |
| ROS 2 Middleware Comparison | 2024 | Benchmark | Zenoh outperforms DDS for planetary mesh networks | LOW -- infrastructure selection |
| LunarSim | 2023 | Simulation | Unity + ROS 2 lunar simulation | LOW -- complementary tool |

### 5.7 ISRU Process Chain

| Publication | Year | Type | Key Contribution | Overlap with SELENE |
|-------------|------|------|-----------------|-------------------|
| RL for ISRU Planning (Acta Astronautica) | 2022 | Trained agent | RL agent for extraction sequencing | MODERATE -- alternative planning approach |
| ICE-RASSOR Deep RL (NASA KSC) | 2021 | Simulated | Autonomous excavation control via deep RL | LOW -- single-agent excavation |
| NASA ISRU Strategic Framework | 2022-2025 | Programmatic | Three-thrust ISRU development roadmap | LOW -- context, not competing system |

---

## 6. Element-by-Element Novelty Analysis

### 6.1 HTN Planner with Virtual Task Resolution

**SELENE's approach:**
- Decomposes `collect_ice(zone, radius, quantity)` into survey waypoints -> virtual `select_site` -> excavate/haul cycles
- Virtual tasks (non-auctioned) resolve by querying Bayesian resource map when all dependencies complete
- Dynamic cycle expansion: generates additional excavate/haul pairs on-demand based on `deposited_kg`
- Site selection scoring: `score = mean / (1 + variance)` (favors high concentration + low uncertainty)

**Prior art:**
- HTN planning methodology is well-established (SHOP2, 2003)
- HTN applied to spacecraft scheduling (HTN-Timeline, 2024)
- Task trees for multi-robot auction (Zlot & Stentz, 2006)

**Novelty assessment:**
- **Virtual task resolution** -- The concept of inserting non-executable placeholder tasks that conditionally trigger new task generation based on sensor-derived state is novel in the ISRU context. Zlot's task trees allow trading tasks at variable abstraction levels, but do not include the concept of virtual tasks that resolve by querying a probabilistic map.
- **Dynamic cycle expansion** -- Generating additional extraction cycles on-demand (rather than pre-planning all cycles) based on real-time deposited mass tracking is a novel operational pattern.
- **Integration with Bayesian map for site selection** -- Using posterior mean/variance from a Bayesian resource map as the decision criterion for HTN task generation is a novel combination.

**Verdict: MODERATE-HIGH NOVELTY.** The HTN methodology is known; the specific application with virtual tasks, Bayesian-informed site selection, and dynamic cycle expansion is novel.

---

### 6.2 Market-Based Auction with Energy-Aware Bid Scoring

**SELENE's approach:**
- Orchestrator broadcasts `TaskAnnouncement` (location, energy cost, capabilities, deadline)
- Agents compute `bid_score = w_dist * exp(-d^2/2*sigma^2) + w_energy * energy_score + w_cap * cap_score`
- Energy affordability: `can_afford_task()` checks go-task-return trip with 10% safety margin
- 5-second timeout tolerates Earth-Moon light delay
- Bid includes projected post-task battery state

**Prior art:**
- Market-based MRTA (Zlot & Stentz, 2006; TraderBots, 2003) -- foundational auction mechanisms
- CBBA (MIT, 2009) -- decentralized consensus-based allocation
- Terrestrial mining fleet dispatch (Caterpillar, Rio Tinto) -- distance-based assignment
- CADRE PS&E (JPL) -- leader election, not auction

**Novelty assessment:**
- **Auction-based allocation** itself is well-established (public domain)
- **Energy-aware bidding** with round-trip affordability checks is not commonly found in the MRTA literature. Most auction systems use distance or time as the primary cost metric. SELENE's bid scoring integrates: (1) Gaussian distance decay, (2) multi-leg energy budget (locomotion + idle + task execution + return), (3) capability matching, and (4) projected post-task battery state.
- **Delay-tolerant auction timeout** specifically designed for Earth-Moon latency is a novel design parameter.

**Verdict: MODERATE NOVELTY.** The auction mechanism is known; the specific energy-aware scoring function combining round-trip affordability with post-task battery projection in a delay-tolerant context is a defensible novelty.

---

### 6.3 Bayesian Spatial Grid Fusion with Footprint Model

**SELENE's approach:**
- Gaussian-Gaussian conjugate updates on a 500x500 grid (1m resolution)
- Distance-decayed footprint: `weight = exp(-dist^2 / 2*sigma^2)` within 5m radius
- Prior: mean=0, variance=100 (uninformed)
- Posterior precision = prior precision + observation precision * weight
- Tracked: mean, variance, observation count per cell
- O(1) updates (no iterative inference)

**Prior art:**
- Bayesian occupancy grid mapping (Thrun et al., 1990s) -- foundational
- Gaussian process mapping for planetary surfaces (arXiv:2503.16613, 2025) -- GP-based
- REALMS2 map merging (2025) -- multi-robot map fusion
- SRCP2 "volatile map" (2023) -- unspecified fusion method

**Novelty assessment:**
- **Bayesian grid mapping** is well-established.
- **Gaussian conjugate updates** are a standard technique.
- **The specific combination** of: (1) spatial footprint with distance-decayed weighting, (2) posterior variance tracking for information-gain scoring, (3) integration with adaptive survey planning, and (4) use as the decision input for HTN virtual task resolution -- this four-way integration has not been published.
- Most published planetary mapping work uses full Gaussian processes (O(N^3) complexity), not conjugate grid updates. SELENE's O(1) approach is a deliberate computational efficiency choice for space-rated processors.

**Verdict: MODERATE NOVELTY.** Individual components are known; the specific integration and the computational efficiency argument for space applications provide defensible novelty.

---

### 6.4 Adaptive Survey Planning via Information Gain

**SELENE's approach:**
- Score = `w_variance * norm_variance + w_signal * norm_neighbor_signal - w_distance * norm_distance`
- Variance term: posterior uncertainty from Bayesian map (exploration)
- Neighbor signal: average ice concentration of 8 neighbors (exploitation)
- Distance: Euclidean from robot position, normalized by PSR diameter (cost)
- Cross-candidate normalization for better ranking
- Spatial filtering: min_spacing=8m prevents revisits

**Prior art:**
- Informative path planning with GPs (arXiv:2503.16613) -- GP-based info-gain for planetary surfaces (closest published work)
- Risk-aware lunar coverage planning (arXiv:2404.18721) -- hybrid global/local planning
- Classical information-theoretic exploration (Stachniss et al., 2005)

**Novelty assessment:**
- **Information-gain exploration** is a well-established concept in robotics.
- **The specific scoring function** combining posterior variance, neighbor signal (exploitation), and distance cost in a three-term weighted sum is a novel formulation. Most published work uses pure information gain (entropy reduction) or mutual information, not a combined exploration-exploitation-cost score.
- **The neighbor signal term** specifically exploits spatial autocorrelation of ice deposits to guide scouts toward deposit clusters. This is conceptually similar to Upper Confidence Bound (UCB) in bandit problems but applied to spatial survey.
- **Cross-candidate normalization** is a practical improvement not typically found in the literature.

**Verdict: MODERATE NOVELTY.** The general approach has precedent; the specific three-term formulation with neighbor exploitation and cross-normalization is defensible.

---

### 6.5 Robot Capability Descriptor Language (RCDL)

**SELENE's approach:**
- YAML schema declaring robot capabilities: sensors (type, range, noise, power draw), actuators (type, capacity, transfer rate), battery profile (capacity, idle draw, locomotion draw), kinematic model
- Pydantic v2 validation at parse time (unique names, valid capabilities, field constraints)
- HAL factory constructs abstract interfaces from descriptors
- Agent code never touches hardware directly

**Prior art:**
- ROS URDF/SDF robot descriptions -- structural/kinematic models (not capability-level)
- RDDL (Relational Dynamic Influence Diagram Language) -- for planning, not hardware description
- CRCL (Canonical Robot Command Language) -- standardized robot command interfaces
- Space ROS hardware abstractions -- under development

**Novelty assessment:**
- **Robot description languages** exist (URDF, SDF) but describe geometry/kinematics, not operational capabilities.
- **RCDL's capability-centric approach** (declaring what a robot CAN DO, not what it LOOKS LIKE) combined with schema validation is a novel pattern for space robotics.
- **The integration** of battery energy profiles (idle_draw, locomotion_draw) directly into the descriptor, enabling automated energy modeling for auction bidding, is not found in existing robot description standards.

**Verdict: MODERATE NOVELTY.** The concept of robot descriptors is established; the capability-centric design with energy profiles and schema validation for heterogeneous ISRU fleets is defensible.

---

### 6.6 Material Conservation Ledger

**SELENE's approach:**
- Tracks: extracted_kg (per site), in_transit_kg (per robot), deposited_kg (depot)
- Conservation invariant: `extracted = in_transit + deposited` (within 0.01 kg tolerance)
- Extraction rate model: `rate = efficiency * power * (concentration/10) / energy_per_kg * depth_penalty`

**Prior art:**
- Terrestrial mining material tracking (ERP systems, fleet management software)
- ISRU mass balance models (NASA technical reports)

**Novelty assessment:**
- Material tracking is standard in mining operations.
- The conservation invariant enforcement with tolerance checking is a software engineering pattern, not a novel algorithm.
- The extraction rate model incorporating ice concentration and depth penalty is domain-specific but straightforward.

**Verdict: LOW-MODERATE NOVELTY.** Best positioned as a dependent claim supporting the broader system patent, not a standalone claim.

---

### 6.7 Agent FSM with Wildcard Transitions

**SELENE's approach:**
- Explicit transition table with (state, event) -> new_state mapping
- Wildcard rules: ENERGY_CRITICAL from any state -> RETURNING; FAULT from any state -> ERROR
- Event-driven (not state-polling)
- Pure Python (zero ROS dependencies, testable in isolation)
- Transition logging for diagnostics

**Prior art:**
- Finite state machines for robot control (ubiquitous in robotics)
- BehaviorTree.CPP (widely used in ROS 2)
- SRCP2 solutions use FSMs for individual robot control
- CADRE agent controllers

**Novelty assessment:**
- FSMs for robot autonomy are extremely well-established.
- Wildcard transitions for cross-cutting concerns (energy critical, fault) are a known design pattern.
- The specific state space (IDLE -> BIDDING -> ASSIGNED -> NAVIGATING -> WORKING -> RETURNING) is domain-specific but follows standard patterns.

**Verdict: LOW NOVELTY.** Not patentable as standalone; useful as implementation detail in broader claims.

---

### 6.8 Composable Skill-Based Task Execution

**SELENE's approach:**
- Skills (ProspectSkill, ExcavateSkill, HaulSkill, RechargeSkill) are multi-phase state machines
- Each skill has: start() -> update(dt) at 10Hz -> complete/abort
- Progress tracking (0.0-1.0) visible to orchestrator
- Skills are orthogonal to agent FSM (WORKING state delegates to active skill)
- HAL-agnostic (skills use abstract interfaces)

**Prior art:**
- Skill-based robot programming (Backus, 2016; SkiROS, 2020)
- Behavior trees with action nodes (BehaviorTree.CPP)
- ROS 2 action servers (lifecycle-managed actions)
- CADRE agent controllers with parameterized behaviors

**Novelty assessment:**
- Skill-based execution is well-established in robotics.
- The specific multi-phase skill designs (prospect: navigate -> settle -> sense -> record) are domain-specific implementations.

**Verdict: LOW-MODERATE NOVELTY.** The skill architecture pattern is known; the specific ISRU skill implementations could support dependent claims.

---

## 7. SELENE's Verifiably Unique Contributions

Based on the comprehensive analysis above, SELENE's verifiably unique contributions fall into two categories:

### 7.1 System-Level Integration (Strongest Claim)

**No published system, product, or patent integrates ALL of the following into a single operational framework:**

1. HTN-based mission decomposition with virtual task resolution
2. Market-based auction task allocation with energy-aware bid scoring
3. Bayesian spatial grid fusion driving adaptive survey planning
4. Delay-tolerant coordination (5s auction timeout > 2x RTT)
5. Full ISRU value chain orchestration (prospect -> extract -> haul -> deposit)
6. Hardware-agnostic robot abstraction via capability descriptors
7. Graceful degradation with automatic task recovery on robot failure

This integration is the primary patentable innovation. Each component has prior art; the combination does not.

**Supporting evidence:**
- NASA SRCP2 (closest) lacks: auction allocation, HTN planning, Bayesian mapping, adaptive survey, delay tolerance
- NASA CADRE lacks: ISRU process chain, auction mechanism, HTN planning
- OffWorld (if published) may overlap but architecture is proprietary and undisclosed
- PRO-ACT lacks: auction mechanism, delay tolerance, Bayesian mapping, extraction chain
- ASPEN/CASPER lacks: multi-robot auction, ISRU process chain, Bayesian resource mapping

### 7.2 Novel Algorithmic Combinations (Supporting Claims)

**A. HTN Virtual Task Resolution with Bayesian Map Query**
- Virtual (non-auctioned) tasks in the HTN that resolve by querying a probabilistic resource map
- When all survey dependencies complete, `select_site` queries `ResourceMap.score_cell = mean / (1 + variance)`
- This triggers conditional task generation (excavate/haul cycles) based on sensor-derived state
- **Not found in prior art**

**B. Dynamic Cycle Expansion Based on Material Tracking**
- HTN planner generates excavate/haul cycles on-demand (not pre-planned)
- Tracks `deposited_kg` from completed haul tasks
- Generates additional cycles until `deposited >= target_kg`
- Links HTN planning to material conservation ledger in a closed loop
- **Not found in prior art**

**C. Energy-Aware Auction Bidding with Round-Trip Affordability**
- Bid score combines: Gaussian distance decay + round-trip energy budget (go + task + return) + capability match
- Safety margin (1.10x) applied to energy cost estimates
- Bid includes projected post-task battery state for fleet-level energy planning
- Integrated with 15% critical battery threshold that overrides any active task via FSM wildcard
- **Energy-aware bidding exists in theory; this specific formulation with round-trip affordability and FSM override integration is novel**

**D. Three-Term Adaptive Survey Scoring on Bayesian Grid**
- `score = w_var * norm_variance + w_sig * norm_neighbor_signal - w_dist * norm_distance`
- Combines information gain (variance), spatial exploitation (neighbor signal), and travel cost
- Uses cross-candidate normalization for consistent ranking
- Maintains min_spacing constraint to prevent revisits
- **Information-gain exploration exists; this specific three-term formulation with neighbor exploitation is novel**

---

## 8. Recommended Patent Claims

### Claim Set 1: System Patent (Broadest Protection)

**Title:** "System and Method for Autonomous Multi-Robot Fleet Coordination for Extraterrestrial In-Situ Resource Utilization"

**Independent Claim 1:**
A computer-implemented method for coordinating a heterogeneous fleet of autonomous robots performing in-situ resource utilization on an extraterrestrial body, comprising:

(a) decomposing a high-level resource collection mission into a dependency-ordered set of primitive tasks using a hierarchical task network (HTN) planner, wherein the set includes at least one virtual task whose resolution is deferred until sensor-derived conditions are met;

(b) allocating primitive tasks to robots via a market-based auction mechanism, wherein each robot computes a bid score based on at least: (i) spatial proximity to the task location, (ii) energy affordability for a round-trip including task execution and return to a recharging station, and (iii) capability match against task requirements declared in a robot capability descriptor;

(c) maintaining a probabilistic resource map by fusing noisy sensor observations via Bayesian conjugate updates with spatially-decayed observation weights;

(d) resolving virtual tasks by querying the probabilistic resource map to select optimal resource extraction sites based on a score combining posterior mean and posterior uncertainty;

(e) dynamically generating additional extraction and transport task cycles based on real-time material accounting until a target quantity is achieved;

(f) detecting robot failures via heartbeat timeout monitoring and automatically recovering assigned tasks by reverting them to a pending state for re-auction to remaining fleet members.

**Dependent Claims:**

2. The method of claim 1, wherein the auction mechanism employs a timeout period greater than twice the round-trip communication latency between the fleet and a remote supervisory system.

3. The method of claim 1, wherein the bid score is computed as a weighted sum: `bid_score = w_distance * f(distance) + w_energy * g(energy_state) + w_capability * h(capability_match)`, where `f(distance) = exp(-d^2 / 2*sigma^2)`.

4. The method of claim 1, wherein the probabilistic resource map maintains per-cell posterior mean, posterior variance, and observation count, updated via Gaussian-Gaussian conjugate formulae with observation weights decayed by `exp(-distance^2 / 2*footprint_sigma^2)` within a sensor footprint radius.

5. The method of claim 1, further comprising an adaptive survey planner that scores candidate survey waypoints using: `score = w_var * normalized_variance + w_signal * normalized_neighbor_concentration - w_distance * normalized_travel_cost`.

6. The method of claim 1, wherein each robot executes tasks via composable skill modules, each skill comprising multiple sequential phases with progress tracking visible to the fleet orchestrator.

7. The method of claim 1, wherein robot capabilities are declared in a machine-readable descriptor language specifying sensor types, actuator types, battery energy profile, and kinematic model, validated by a schema enforcement layer.

8. The method of claim 1, further comprising a material conservation ledger tracking extracted, in-transit, and deposited material quantities with a conservation invariant: `total_extracted = total_in_transit + total_deposited`.

9. The method of claim 1, wherein each robot maintains a finite state machine with wildcard transitions for energy-critical and fault events that override any active state to initiate return-to-base behavior.

10. The method of claim 1, wherein the hierarchical task network generates hexagonal survey waypoints sorted by distance from zone center, and the virtual site-selection task scores extraction sites as `mean / (1 + variance)`.

---

### Claim Set 2: Adaptive Resource Mapping and Survey Patent

**Title:** "Method for Adaptive Survey Planning Using Information-Gain Scoring on a Bayesian Resource Map for Extraterrestrial Prospecting"

**Independent Claim 1:**
A computer-implemented method for adaptively planning survey waypoints for autonomous prospecting robots on an extraterrestrial body, comprising:

(a) maintaining a grid-based probabilistic resource map, each cell storing a posterior mean concentration and posterior variance, updated via Bayesian conjugate formulae with spatially-decayed observation weights based on sensor-to-cell distance;

(b) generating candidate survey waypoints on a grid within a designated survey zone, filtered by minimum spacing from previously visited or queued waypoints;

(c) scoring each candidate waypoint using a multi-objective function comprising: (i) an exploration term proportional to the posterior variance at the candidate location, normalized across all candidates; (ii) an exploitation term proportional to the average resource concentration of neighboring cells, normalized across all candidates; (iii) a cost term proportional to the Euclidean distance from the surveying robot's current position, normalized by the survey zone diameter;

(d) selecting the highest-scoring candidate as the next survey waypoint;

(e) upon receiving a sensor observation at the selected waypoint, updating the probabilistic resource map and repeating steps (b)-(d) for subsequent waypoint selection.

---

### Claim Set 3: HTN Virtual Task Patent

**Title:** "Method for Mission Decomposition Using Hierarchical Task Networks with Deferred Virtual Task Resolution for Autonomous Resource Extraction"

**Independent Claim 1:**
A computer-implemented method for decomposing a resource extraction mission into executable tasks for a fleet of autonomous robots, comprising:

(a) receiving a mission specification including a target zone, target quantity, and resource type;

(b) generating a set of survey tasks at waypoints within the target zone using a hierarchical task network (HTN) planner;

(c) inserting a virtual task node into the HTN dependency graph, the virtual task having dependencies on all survey tasks and being marked as non-auctionable;

(d) upon completion of all survey task dependencies, resolving the virtual task by querying a probabilistic resource map to identify an optimal extraction site based on a scoring function incorporating both estimated resource concentration and estimation uncertainty;

(e) generating a set of extraction and transport task pairs, each pair having an ordering dependency, and the first extraction task depending on the resolved virtual task;

(f) monitoring material deposited at a collection point from completed transport tasks;

(g) dynamically generating additional extraction and transport task pairs when the deposited quantity is less than the target quantity.

---

## 9. Freedom-to-Operate Considerations

### 9.1 Low-Risk Areas
- **ROS 2 / Gazebo usage:** Open-source (Apache 2.0 / BSD)
- **A* path planning:** Public domain algorithm
- **FSM-based robot control:** Ubiquitous, not patentable
- **Bayesian grid mapping (general):** Public domain (Thrun et al.)
- **HTN planning (general):** Public domain (SHOP2)
- **Auction-based MRTA (general):** Public domain (CMU, 2003-2006)

### 9.2 Areas Requiring Further Investigation
- **OffWorld Inc. IP:** Architecture undisclosed. May hold patents on swarm mining coordination.
- **Caterpillar fleet dispatch patents:** Review for potential overlap with lunar fleet management claims.
- **NASA technology licensing:** CASPER/ASPEN are NASA tech; verify licensing terms if architectural patterns borrowed.
- **ESA PRO-ACT IP:** EU H2020 funded; check publication/IP terms.

### 9.3 Recommended Actions
1. Engage a registered patent attorney for formal FTO search
2. Specifically search for OffWorld Inc. patent filings (USPTO, EPO, WIPO)
3. Review Caterpillar autonomous mining patents for overlap
4. Confirm NASA technology licensing terms for CASPER/ASPEN architectural patterns

---

## 10. Recommendations & Next Steps

### 10.1 Patent Filing Strategy

**Priority 1 (File First):** Claim Set 1 (System Patent)
- Broadest protection
- Covers the unique integration of all components
- Hardest for competitors to design around
- File as a provisional patent application to establish priority date

**Priority 2:** Claim Set 3 (HTN Virtual Task)
- Most algorithmically novel single contribution
- Virtual task resolution with Bayesian map query is not in the literature
- Dynamic cycle expansion is a practical innovation

**Priority 3:** Claim Set 2 (Adaptive Survey)
- Defensible but closest to existing information-gain literature
- Three-term scoring function with neighbor exploitation is the differentiator

### 10.2 Strengthening Patentability

1. **Document reduction to practice:** Ensure simulation demonstrations with measurable results (task completion time, energy efficiency, fault recovery) are recorded and dated.

2. **Publish a technical paper:** A peer-reviewed publication (e.g., IEEE Aerospace Conference, AIAA SciTech) establishes prior art in YOUR favor and strengthens the non-obviousness argument.

3. **Benchmark against prior art:** Run SRCP2-equivalent scenarios and demonstrate measurable improvement from the auction mechanism, adaptive survey, and Bayesian mapping.

4. **File provisional patent applications** to establish priority date while continuing development. Provisionals give 12 months to file the full application.

### 10.3 Professional Services Needed

1. **Patent Attorney** -- Registered patent attorney with experience in software/method patents and preferably space technology. Needed for: formal FTO search, claim drafting, prosecution.

2. **Prior Art Search Service** -- Professional patent search firm for comprehensive coverage of USPTO, EPO, WIPO, JPO databases.

3. **Technical Expert Declaration** -- An expert in multi-robot systems or space robotics who can provide a declaration of non-obviousness for the patent examiner.

---

## Appendix A: Recommended Patent Search Queries

For use with Google Patents, USPTO PatFT/AppFT, Espacenet, WIPO PATENTSCOPE:

### System-Level
```
"lunar ISRU" AND "autonomous" AND ("fleet" OR "multi-robot")
"in-situ resource utilization" AND "task allocation" AND "robot"
"extraterrestrial" AND "fleet management" AND "autonomous"
"space mining" AND "multi-robot" AND "coordination"
"lunar surface" AND "heterogeneous robot" AND "orchestration"
```

### HTN + Virtual Tasks
```
"hierarchical task network" AND "virtual task"
"HTN" AND "deferred" AND "task resolution"
"hierarchical planning" AND "conditional task generation"
"task decomposition" AND "resource map" AND "site selection"
"mission decomposition" AND "dynamic task expansion"
```

### Auction + Energy
```
"auction" AND "task allocation" AND "energy" AND "robot"
"market-based" AND "multi-robot" AND "battery" AND "bidding"
"energy-aware" AND "auction" AND ("fleet" OR "multi-robot")
"bid score" AND "energy affordability" AND "robot"
"round-trip energy" AND "task allocation"
```

### Bayesian Resource Mapping
```
"Bayesian" AND "resource map" AND "sensor fusion" AND "robot"
"probabilistic grid" AND "information gain" AND "survey"
"conjugate update" AND "spatial footprint" AND "mapping"
"posterior variance" AND "adaptive survey" AND "robot"
```

### Robot Capability Descriptors
```
"robot capability descriptor" AND "YAML"
"hardware abstraction" AND "capability" AND "space robot"
"robot descriptor language" AND "validation"
"heterogeneous robot" AND "capability description" AND "schema"
```

### ISRU Material Tracking
```
"material conservation" AND "autonomous mining" AND "ledger"
"extraction tracking" AND "in-transit" AND "deposited"
"ISRU" AND "material balance" AND "autonomous"
```

---

## Appendix B: Key References

### Commercial
1. OffWorld Inc. — https://www.offworld.ai/
2. Lunar Outpost MAPP — https://www.lunaroutpost.com/mapp
3. Astrobotic CubeRover — https://www.astrobotic.com/lunar-delivery/rovers/cuberover/
4. Caterpillar & NASA — https://www.cat.com/en_US/blog/nasa-using-caterpillar-technology.html

### Government Programs
5. NASA CADRE — https://www.nasa.gov/missions/tech-demonstration/cadre/
6. CADRE PS&E Architecture — https://arxiv.org/html/2502.14803v1
7. NASA SRCP2 — https://spacecenter.org/space-robotics-challenge/space-robotics-challenge-phase-2/
8. NASA IPEx — https://www.nasa.gov/isru-pilot-excavator/
9. ESA PROSPECT — https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/Prospect_searching_for_water_at_the_lunar_poles
10. ESA PRO-ACT — https://robotik.dfki-bremen.de/en/research/projects/pro-act-og11

### Academic — Multi-Robot ISRU
11. "Multi-robot cooperation for lunar ISRU" — Frontiers in Robotics and AI, 2023
12. LunarMiner Framework — Biomimetics, 9(11), 680, 2024
13. PRO-ACT Publications — Springer LNCS 2023

### Academic — Auction-Based Allocation
14. Zlot & Stentz, Market-Based MRTA — IJRR, 25(1), 2006
15. TraderBots — CMU-RI-TR-03-19, 2003
16. CBBA — Choi, Brunet, How (MIT), 2009

### Academic — HTN Planning
17. SHOP2 — Nau et al., JAIR 20, 2003
18. HTN-Timeline Spacecraft Scheduling — Aerospace, 11(5), 2024

### Academic — Adaptive Survey
19. Informative Path Planning with GPs — arXiv:2503.16613, 2025
20. Risk-Aware Lunar Coverage — arXiv:2404.18721, 2024
21. Scarab Rover — CMU, i-SAIRAS 2008

### Academic — Delay-Tolerant Autonomy
22. CASPER — JPL AI Group, 1999-present
23. ASPEN — JPL AI Group, 1997-present
24. MARTA — CMU, 2007

### Academic — ROS 2 Space
25. Space ROS — AIAA SciTech 2023-2709
26. REALMS2 — arXiv:2510.26638, 2025
27. VIPER Software — NASA NTRS, 2021-2022
28. ROS 2 Middleware Comparison — J. Intelligent & Robotic Systems, 2024

### Academic — ISRU Process
29. RL for ISRU Planning — Acta Astronautica, 2022
30. ICE-RASSOR Deep RL — NASA NTRS, 2021

---

## Appendix C: Specific Patents Reviewed

### Robot Hardware Abstraction
| Patent | Title | Assignee | Risk |
|--------|-------|----------|------|
| US7801644B2 | Generic Robot Architecture | Battelle / Humatics | LOW |
| US7925381B2 | HAL for a Robot | Evolution Robotics / iRobot | LOW |
| US7590680B2 | Extensible Robotic Framework | Microsoft | LOW |
| US10009410B2 | Description Files for IoT | Samsung | LOW |
| US10929759B2 | Intelligent Robot Software Platform | -- | LOW |

### Task Allocation / Planning
| Patent | Title | Assignee | Risk |
|--------|-------|----------|------|
| US7383100B2 | Extensible Task Engine for Humanoid Robots | Honda (active to 2026-12) | LOW |
| WO2019234702A2 | Actor Model for Multi Robot Systems | -- | LOW-MED |
| US10089586B2 | Job Management for Autonomous Mobile Robots | Omron (was Adept) | LOW-MED |
| US20220269284A1 | Management of a Robot Fleet | Yokogawa Electric | LOW |
| US8868241B2 | Robot Task Commander | -- | LOW |

### Mapping / Spatial Data
| Patent | Title | Assignee | Risk |
|--------|-------|----------|------|
| US9404756B2 | Adaptive Mapping with Spatial Summaries | iRobot | LOW |
| WO2018009263A1 | Systems for Mapping an Environment | -- | LOW |
| US20140052687A1 | Probability Mapping System | -- | LOW |
| US20200213426A1 | Spatial Data Processing (VoxelNET) | -- | LOW |
| US20240168480A1 | Autonomous Mapping by Mobile Robot | -- | LOW |
| US11119216B1 | Coverage Planning for Mobile Robots | -- | LOW |

### Space / Mining
| Patent | Title | Assignee | Risk |
|--------|-------|----------|------|
| **US12005588B2** | **Industrial Robotic Platforms** | **Off-World, Inc.** | **MONITOR** |
| US11143026B2 | Radiant Gas Dynamic Mining of Permafrost | Trans Astronautica | LOW |
| US20100057254A1 | Robotics in Mining and Post-Mining | MI Robotic Solutions | LOW |
| US9234426B2 | Mine Operation Monitoring System | Technological Resources | LOW |
| US9045003 | RASSOR Excavation Mechanism | NASA | NONE (gov't) |

---

*This analysis was prepared on 2026-04-05 and reflects the state of publicly available information as of that date. It is not a substitute for a formal freedom-to-operate opinion from a registered patent attorney.*
