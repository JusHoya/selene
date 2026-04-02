# SELENE — Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation

## Comprehensive Project Plan: AI-Driven Lunar ISRU Fleet Management Software Suite

---

## 1. Executive Summary

SELENE is a proposed standardized software suite for commanding, coordinating, and optimizing a heterogeneous fleet of autonomous lunar surface robots tasked with In-Situ Resource Utilization (ISRU). The suite covers the full ISRU value chain — prospecting, identification, extraction, processing, and transportation of lunar resources — and is architected from the ground up to scale from a lunar prototype into a general-purpose spacecraft fleet management platform applicable to Mars, asteroids, and orbital operations.

The timing is exceptional. Artemis II is launching today (April 1, 2026), NASA's CADRE multi-rover cooperative autonomy demo is headed to the Moon aboard IM-3 in 2026, and the PRIME-1 ice-mining experiment recently flew. Meanwhile, commercial players like Ethos Space Resources, Redwire, Astroport, and SoftServe are racing to build robotic fleet capabilities. A standardized, open-architecture software layer that sits above heterogeneous hardware — analogous to what ROS became for terrestrial robotics — represents an enormous gap in the market.

---

## 2. Research Findings: State of the Art

### 2.1 Lunar ISRU Techniques — Current Landscape

#### Water Ice Extraction (Polar Regions)
The lunar south pole's permanently shadowed regions (PSRs) harbor water ice at concentrations of approximately 5.6 ± 2.9 wt%, as confirmed by the LCROSS impact experiment. Three primary extraction paradigms have emerged:

- **Thermal Mining (In-Situ):** Energy is transported into PSRs (via solar reflectors, lasers, or radioisotope waste heat), regolith is heated to sublimate ice, and water vapor is captured in cold traps. The concept, pioneered by George Sowers, has been validated experimentally — halogen lamp tests show extraction is effective in the top 2 cm of regolith under 1-solar illumination. The Chang'E-7 mission is exploring induction-heating-based extraction, which uses porous-media heat-mass transfer modeling validated by COMSOL simulations.
- **Drill-and-Haul (Remote Extraction):** Icy regolith is mechanically excavated inside the PSR and transported to a processing facility in sunlight. NASA's PRIME-1 experiment demonstrated the TRIDENT drill (extracting regolith to ~1 m depth) paired with the MSOLO mass spectrometer for volatile analysis.
- **Microwave Extraction:** Regolith is heated volumetrically using microwave energy, allowing deeper penetration than surface heating. Still largely at laboratory TRL.

**Key challenge for fleet software:** Thermal mining operations require precise coordination between scout robots (prospecting for ice signatures via neutron spectrometers and ground-penetrating radar), excavation/heating units, cold-trap transport vehicles, and energy-relay systems — all operating in PSR darkness at temperatures as low as 40 K.

#### Oxygen from Regolith (Dry Processing)
Lunar regolith contains approximately 40–45% oxygen by mass, chemically bound to silicate and oxide minerals. Three electrolytic/pyrometallurgical processes are advancing:

- **Molten Regolith Electrolysis (MRE):** Regolith is melted at 1600–2000°C and electrolyzed to split oxygen from metals. A ~1-tonne MRE plant could produce ~10 tonnes of O₂/year from highlands regolith at ~25 kW power draw, with ~70% extraction efficiency. By-products include iron, silicon, aluminum, and titanium alloys.
- **Molten Salt Electrolysis (FFC-Cambridge Process):** Operates at lower temperatures (800–1200°C) using molten calcium chloride as electrolyte. ESA's prototype plant at ESTEC is operational. Research shows 60% extraction optimizes throughput while 70–80% maximizes power efficiency.
- **Carbothermal Reduction:** Uses carbon (from methane) as a reductant at ~1600°C. Demonstrated in field tests by NASA using concentrated solar energy.
- **Vacuum Pyrolysis:** Heats regolith to extreme temperatures under vacuum to thermally dissociate oxides. Under active investigation using laser and concentrated solar heating.

**Key challenge for fleet software:** MRE/FFC plants require continuous feedstock delivery. An excavation rover must haul regolith to a hopper, a conveyor lifts it into the reactor, and processed slag must be removed. The entire pipeline — excavation scheduling, hauling logistics, reactor batch timing, product storage — needs orchestration.

#### Construction & Manufacturing
- **ICON's Olympus system** uses Laser Vitreous Multi-material Transformation to 3D-print structures from melted regolith.
- **Laser Powder Bed Fusion (LPBF)** of regolith simulants (targeting Chang'E-8) has produced specimens with flexural strengths of 5.79 MPa for highland types.
- **Regolith-PEEK composites** achieve 14.6 MPa flexural strength at 15 wt% binder for landing pad construction.
- **Astroport's Lunatron** envisions an autonomous rover converting regolith into interlocking bricks.

### 2.2 Multi-Robot Coordination — State of the Art

#### NASA CADRE (Cooperative Autonomous Distributed Robotic Exploration)
The most directly relevant mission. Three suitcase-sized rovers launching aboard IM-3 in 2026 to Reiner Gamma. Key architectural decisions:
- **Semi-centralized autonomy:** Rovers elect a leader that distributes work assignments; each rover plans its own safe path execution.
- **Mesh network communication** via a base station.
- **Cooperative exploration algorithm** that partitions unexplored areas into non-overlapping regions assigned to individual agents, minimizing inter-robot communication.
- **Adaptive replanning:** When one rover's battery is low, the team pauses and replans collectively.

#### NASA SRCP2 (Space Robotics Challenge Phase 2)
A $1M prize competition that drove significant advances in multi-robot lunar ISRU software. The competition defined a heterogeneous fleet of Scouts, Excavators, and Haulers operating in a Gazebo/ROS simulation of the lunar surface. Top solutions featured:
- **Central task planners** with **decentralized finite state machines (FSMs)** for individual robot control.
- **Volatile mapping** with shared global maps updated by scout sensor data.
- **Rover-to-rover and rover-to-infrastructure docking** maneuvers using bounding-box detection.
- **Mobility hazard estimation** (slippage detection, stuck-status recognition) with autonomous recovery strategies.
- **ROS-based software architectures** with SLAM, YOLO-based object detection, and visual odometry.

#### Lunarminer Framework
A bio-inspired swarm robotics approach to lunar water ice extraction using finite state machines governing a three-phase mining lifecycle: resource prospecting/localization → mineral excavation/transportation → maintenance/sustainability. Simulated in Shackleton Crater using ROS, achieving 181 L/day water extraction rate. Uses firefly-inspired synchronized flashing for navigation in dark PSR environments.

#### SoftServe Multi-Robot Orchestrator
A commercially-oriented, hardware-agnostic fleet management platform. Key features: simulation-first validation using NVIDIA Omniverse and Isaac Sim, AI-driven task assignment with failure adaptation, and a design philosophy of treating robotic fleets as modular teams.

### 2.3 AI/ML Capabilities — Emerging Opportunities

#### Onboard AI for Space Robotics
Stanford researchers demonstrated the first ML-based robot control on the ISS in 2025, achieving 50–60% faster autonomous movement planning on the Astrobee robot. Key insight: space-rated flight computers are far more resource-constrained than terrestrial ones, requiring mathematically grounded, safety-focused AI with formal guarantees.

#### Physical AI
NVIDIA's 2026 "Physical AI" framework — enabling autonomous systems to perceive, reason, and act in the physical world — is directly applicable. Key concepts: sim-to-real transfer, imitation-learned models where robots learn from each other, and edge deployment of reasoning models for local autonomy without cloud dependency.

#### Foundation Models for Robotics
The convergence of large language models, reinforcement learning, and robotic control is creating opportunities for more flexible task planning. ANN-based controllers for multi-robot lunar tasks have shown advantages in discovering creative cooperative strategies.

---

## 3. Where AI Can Augment and Improve Current ISRU

### 3.1 Prospecting & Resource Assessment

| Current Approach | AI-Augmented Improvement |
|---|---|
| Manual interpretation of neutron spectrometer / GPR data | **Learned spectral classifiers** that fuse multi-modal sensor data (neutron, NIR, GPR, thermal) to generate real-time probabilistic resource maps with uncertainty quantification |
| Pre-planned survey grids | **Adaptive survey planning** using Bayesian optimization — each measurement informs the next waypoint, maximizing information gain per unit energy |
| Ground-truth requires human analysis | **Onboard mineral identification** using trained vision models on regolith imagery, classifying composition without Earth-link |

### 3.2 Extraction Operations

| Current Approach | AI-Augmented Improvement |
|---|---|
| Fixed heating profiles for thermal mining | **Adaptive thermal control** using learned models of regolith thermal-diffusion behavior — adjusting power dynamically based on real-time sublimation feedback |
| Manual drill parameter selection | **Reinforcement-learned drilling policies** that optimize penetration rate, energy consumption, and bit wear based on real-time force/torque feedback |
| Batch processing with fixed timing | **Predictive process control** for MRE/FFC reactors — ML models trained on electrolysis data predict optimal batch durations and endpoint detection |

### 3.3 Fleet Coordination

| Current Approach | AI-Augmented Improvement |
|---|---|
| FSM-based state transitions | **Hierarchical task networks (HTNs)** with LLM-based high-level planning — natural language mission objectives decomposed into executable task graphs |
| Fixed role assignment (scout/excavator/hauler) | **Dynamic role allocation** based on fleet health, energy state, and operational demand — any robot can be reassigned as conditions change |
| Reactive replanning on failure | **Predictive maintenance + proactive scheduling** — ML models predict component degradation, triggering preemptive task redistribution before failures occur |
| Central coordinator as single point of failure | **Federated consensus protocols** with graceful degradation — fleet maintains operation if any single node (including the coordinator) fails |

### 3.4 Navigation & Mobility

| Current Approach | AI-Augmented Improvement |
|---|---|
| Pre-mapped terrain with local obstacle avoidance | **Self-supervised terrain traversability learning** — rovers build and share traversability models from their own driving experience |
| GPS-denied navigation via visual odometry | **Multi-agent cooperative SLAM** with shared feature maps — rovers collaboratively build and refine a global map, correcting each other's drift |
| Conservative path planning for safety | **Risk-aware planning** with learned terrain models — distinguish between "unknown" and "dangerous," allowing more efficient exploration |

### 3.5 Communications & Data

| Current Approach | AI-Augmented Improvement |
|---|---|
| Store-and-forward to Earth | **Onboard data triage** — AI models prioritize which data to transmit during limited comm windows, compressing or summarizing low-priority telemetry |
| Mesh networking with fixed protocols | **Adaptive mesh routing** that accounts for rover positions, terrain shadowing, and relay opportunities to maximize connectivity |
| Human-in-the-loop decision making | **Supervised autonomy with exception escalation** — AI handles routine decisions, only escalating novel situations to human operators with rich context summaries |

---

## 4. System Architecture

### 4.1 Architectural Philosophy

SELENE follows a **layered, modular, hardware-agnostic** architecture. It does not build robots — it makes heterogeneous robots work together. The architecture is designed for:

- **Delay-tolerant operation:** 1.3-second Earth-Moon light delay, potential multi-minute comm blackouts
- **Resource-constrained compute:** Space-rated processors are orders of magnitude less powerful than terrestrial equivalents
- **Graceful degradation:** No single point of failure; fleet continues operating if any component fails
- **Extensibility:** New robot types, new ISRU processes, and new celestial bodies can be integrated without re-architecting

### 4.2 Layer Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   MISSION CONTROL LAYER                 │
│   Earth-based: Mission planning, monitoring, override   │
│   Human-in-the-loop interface, digital twin, analytics  │
└────────────────────────┬────────────────────────────────┘
                         │ Delay-tolerant comm link
┌────────────────────────▼────────────────────────────────┐
│              FLEET ORCHESTRATION LAYER                   │
│   Lunar-surface: Task decomposition, scheduling,        │
│   resource allocation, inter-agent negotiation           │
│   Runs on: Base station / lander / dedicated compute    │
└────────┬───────────┬───────────┬───────────┬────────────┘
         │           │           │           │
    ┌────▼────┐ ┌────▼────┐ ┌────▼────┐ ┌───▼─────┐
    │ SCOUT   │ │EXCAVATOR│ │ HAULER  │ │PROCESSOR│
    │ AGENT   │ │ AGENT   │ │ AGENT   │ │ AGENT   │
    ├─────────┤ ├─────────┤ ├─────────┤ ├─────────┤
    │Autonomy │ │Autonomy │ │Autonomy │ │Autonomy │
    │ Layer   │ │ Layer   │ │ Layer   │ │ Layer   │
    ├─────────┤ ├─────────┤ ├─────────┤ ├─────────┤
    │Hardware │ │Hardware │ │Hardware │ │Hardware │
    │Abstract.│ │Abstract.│ │Abstract.│ │Abstract.│
    └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### 4.3 Core Subsystems

#### A. Mission Control Interface (Earth-Side)

**Digital Twin Engine**
- Real-time 3D visualization of the lunar operational area
- Simulated fleet state synchronized via delay-tolerant networking
- "What-if" scenario planning for mission operators
- Built on open standards (OpenUSD for 3D scene description)

**Mission Planning Console**
- High-level objective definition (e.g., "Extract 500 kg water from PSR-Alpha within 30 lunar days")
- Constraint specification (no-go zones, energy budgets, maintenance windows)
- Automated plan generation with human review and approval
- Historical mission analytics and performance dashboards

**Supervisory Control**
- Exception handling queue for AI-escalated decisions
- Direct teleop override for any individual robot (with latency compensation)
- Fleet health monitoring with predictive alerts

#### B. Fleet Orchestration Engine (Lunar-Side)

**Task Decomposition & Planning**
- Hierarchical Task Network (HTN) planner decomposes mission objectives into robot-level tasks
- Temporal constraint propagation ensures task ordering and deadlines
- Energy-aware scheduling accounts for solar availability, battery state, and recharge logistics
- Implements a market-based task auction protocol where robots bid on tasks based on capability, proximity, and energy state

**Resource Map Manager**
- Maintains the global probabilistic resource map (water ice concentration, mineral composition, terrain traversability)
- Fuses data from all scout sensors using Bayesian update framework
- Provides query API for other subsystems ("Where is the nearest high-confidence ice deposit?")
- Versioned map snapshots for temporal change detection

**Fleet State Monitor**
- Aggregates health telemetry from all agents
- Predictive maintenance models for each robot class
- Anomaly detection for early fault identification
- Consensus-based leader election (inspired by CADRE's approach)

**Communication Manager**
- Adaptive mesh network routing
- Priority-based message queuing
- Store-and-forward for Earth link intermittency
- Bandwidth-aware data compression policies

#### C. Agent Autonomy Layer (Per-Robot)

**Perception Pipeline**
- Sensor fusion (cameras, LiDAR, IMU, wheel odometry, spectrometers)
- Onboard object detection and classification (terrain features, other robots, hazards, resources)
- Local traversability mapping with uncertainty propagation
- Cooperative SLAM contribution (local map segments shared to fleet)

**Navigation & Mobility**
- Global path planning on shared traversability map
- Local obstacle avoidance with safety-critical guarantees
- Terrain-adaptive locomotion control (slip compensation, soft-soil handling)
- Formation driving and convoy operations
- Docking maneuvers (rover-to-rover, rover-to-infrastructure)

**Task Execution Engine**
- Finite state machine for behavioral sequencing
- Skill library: prospect, drill, excavate, haul, dump, dock, recharge, relay-comm
- Execution monitoring with automatic retry and failure escalation
- Energy budgeting per task with abort thresholds

**Hardware Abstraction Layer (HAL)**
- Standardized interfaces for actuators, sensors, and power systems
- Robot Capability Description Language (RCDL) — a declarative schema describing each robot's physical capabilities, sensor suite, and operational constraints
- Hot-swappable sensor/actuator drivers
- Enables the same autonomy stack to run on different robot hardware

#### D. ISRU Process Control Layer

**Prospecting Module**
- Adaptive survey planning algorithms
- Multi-sensor data fusion for resource characterization
- Deposit boundary delineation and volume estimation
- Confidence-scored resource reports

**Extraction Module**
- Thermal mining control (power modulation, vapor capture optimization)
- Drilling control (adaptive feed rate, bit health monitoring)
- Excavation planning (cut geometry, spoil management)
- Real-time process telemetry and yield estimation

**Processing Module**
- MRE/FFC reactor batch orchestration
- Feedstock quality monitoring and blending optimization
- Product collection and routing (O₂ to storage, metals to fabrication)
- Electrolysis endpoint detection via ML models

**Logistics Module**
- Hauling route optimization (minimize energy, maximize throughput)
- Load planning and vehicle utilization
- Storage inventory management (water, LOX, metals)
- Supply chain scheduling across the full ISRU pipeline

### 4.4 Data Architecture

```
┌────────────────────────────────────────┐
│          Shared Data Fabric            │
├────────────────────────────────────────┤
│  Resource Map Store (probabilistic)    │
│  Terrain/Traversability Map (2.5D)     │
│  Fleet State Database (time-series)    │
│  Task Queue & Execution Log            │
│  ISRU Process Telemetry                │
│  Communication Network Topology        │
│  Maintenance & Degradation Models      │
└────────────────────────────────────────┘
```

- All data stores use **conflict-free replicated data types (CRDTs)** for eventual consistency across distributed nodes
- **Event-driven architecture** with pub/sub messaging (DDS — Data Distribution Service, the standard for robotics middleware)
- **Time-stamped, versioned** data with causal ordering for accurate replay and debugging

### 4.5 Technology Stack (Prototype)

| Component | Technology | Rationale |
|---|---|---|
| Robot middleware | ROS 2 (Humble+) | Industry standard, DDS-based, real-time capable |
| Simulation | Gazebo Harmonic / NVIDIA Isaac Sim | High-fidelity physics, sensor simulation |
| 3D Scene | OpenUSD | Interoperable digital twin format |
| Task planning | PDDL + HTN planner | Well-understood, formally verifiable |
| ML framework | PyTorch (training) / ONNX Runtime (inference) | Portable, edge-deployable |
| Communication | DDS (Cyclone/FastDDS) | Designed for distributed real-time systems |
| Digital twin viz | Three.js / Open 3D Engine | Web-based, accessible mission control |
| Language | Python (orchestration) / C++ (real-time) / Rust (safety-critical) | Performance + safety where needed |

---

## 5. Operational Concept (ConOps)

### Phase 1: Deployment & Commissioning
1. Lander touches down in illuminated zone near PSR
2. Robots are deployed from lander (tether lowering system, as in CADRE)
3. Base station activates; mesh network established
4. Fleet performs self-check and reports readiness
5. Orchestrator initializes with pre-loaded terrain map from orbital data

### Phase 2: Prospecting Campaign
1. Scout robots fan out in adaptive survey pattern
2. Neutron spectrometers and GPR scan for water ice signatures
3. Resource map builds iteratively; high-interest areas trigger concentrated survey
4. Scouts relay data through mesh network to orchestrator
5. Orchestrator generates extraction site recommendations with confidence scores

### Phase 3: Site Preparation & Extraction
1. Excavator robots are dispatched to highest-confidence sites
2. Haulers stage near extraction sites for material transport
3. Thermal mining / drilling operations begin with adaptive process control
4. Vapor is captured and transported to processing facility
5. Extracted regolith or water is hauled to processing infrastructure

### Phase 4: Processing & Storage
1. Feedstock is delivered to MRE/FFC plant
2. Reactor batch operations are orchestrated by process control module
3. O₂ is cryogenically condensed and stored; metals are collected
4. Inventory management tracks product accumulation
5. Real-time yield data feeds back to optimize extraction site selection

### Phase 5: Sustained Operations
1. Fleet operates continuously across lunar day/night cycles
2. Solar-powered units hibernate during night; RPS-powered units continue
3. Predictive maintenance schedules trigger preventive servicing
4. New areas are prospected as existing deposits are depleted
5. Earth mission control receives summarized reports and intervenes only on exceptions

---

## 6. Extensibility Roadmap: From Moon to Fleet Management Platform

### Phase I — Lunar ISRU Prototype (Year 1–2)
- Core fleet orchestration engine
- Simulated lunar environment with 3–5 robot types
- Basic ISRU process models (thermal mining, regolith hauling)
- Mission control digital twin

### Phase II — Lunar Operational Software (Year 2–4)
- Integration with real hardware via HAL
- Full ISRU process control (extraction through processing)
- Advanced AI: adaptive survey, predictive maintenance, learned terrain models
- Field testing with analog environments (desert, volcanic sites)

### Phase III — Multi-Body Fleet Management Platform (Year 4–7)
- Generalized to Mars surface operations (CO₂ processing, Sabatier reaction)
- Orbital fleet management (satellite servicing, debris removal)
- Asteroid mining operations
- Commercial API for third-party robot integration

### Terrestrial Spin-Off Applications
The same fleet management architecture applies to:
- Autonomous mining operations (open pit, underground)
- Disaster response robot fleets
- Agricultural swarm robotics
- Construction site automation (directly aligned with ICON's Olympus vision)

---

## 7. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Communication blackouts | Robots halt operations | High | Autonomous operation continues with local decision-making; store-and-forward |
| Robot hardware failure | Reduced fleet capacity | High | Dynamic task reallocation; N+1 redundancy in fleet sizing |
| Resource map inaccuracy | Wasted extraction energy | Medium | Bayesian uncertainty tracking; adaptive re-survey triggers |
| Regolith variability | Process yields below targets | Medium | Adaptive process control; multi-sensor feedstock characterization |
| Software bugs in autonomy | Dangerous robot behavior | Medium | Formal verification of safety-critical paths; simulation-exhaustive testing |
| Thermal extremes | Electronics damage | High | Thermal management integration in scheduling; hibernation protocols |
| Lunar dust contamination | Sensor/mechanism degradation | High | Dust-tolerant mechanical design (outside software scope); predictive maintenance for degradation |
| Communication latency (Earth-Moon) | Delayed intervention | Certain | Supervised autonomy architecture; exception-based escalation only |

---

## 8. Development Plan for Prototype Handoff

### What the Code Instance Should Build (Sprint 0 Prototype)

The initial prototype should demonstrate the core fleet orchestration concept in simulation. Scope for the first development cycle:

**Simulation Environment**
- Gazebo or Isaac Sim lunar terrain with PSR zones
- 3 robot types: Scout (sensors), Excavator (drill/heating), Hauler (transport bin)
- Basic physics: terrain friction, slope effects, energy consumption model

**Fleet Orchestrator (Python/ROS 2)**
- Task auction protocol: Orchestrator broadcasts tasks; agents bid based on capability + proximity + energy
- Simple HTN planner: Decompose "Collect 100 kg ice from Zone A" into scout → excavate → haul subtasks
- Fleet state monitor aggregating robot health via ROS topics
- Event-driven architecture with DDS pub/sub

**Agent Autonomy Stack (Per Robot)**
- FSM-based task execution (Idle → Assigned → Navigating → Working → Returning → Recharging)
- A* path planning on occupancy grid
- Basic obstacle avoidance
- Energy budget tracking with low-energy return-to-base behavior
- HAL with standardized sensor/actuator interfaces

**Resource Map**
- Probabilistic occupancy grid for ice concentration
- Scouts update the map via simulated sensor readings
- Bayesian fusion of multi-scout observations
- Visualization overlay in RViz2

**Mission Control Dashboard (Web)**
- Real-time fleet visualization (robot positions, states, battery levels)
- Resource map heatmap display
- Task queue visibility
- Manual task injection and robot override

**Key Integration Points**
- Demonstrate a full prospecting → extraction → transport cycle with 3+ robots cooperating
- Show dynamic task reallocation when one robot is disabled mid-mission
- Show adaptive survey behavior where scouts converge on high-signal areas

### File/Package Structure Recommendation

```
selene/
├── selene_msgs/                # Custom ROS 2 message/service definitions
│   ├── msg/
│   │   ├── RobotState.msg
│   │   ├── ResourceMap.msg
│   │   ├── TaskAssignment.msg
│   │   └── BidResponse.msg
│   └── srv/
│       ├── RequestTask.srv
│       └── UpdateMap.srv
├── selene_orchestrator/        # Fleet orchestration engine
│   ├── task_planner.py         # HTN decomposition
│   ├── task_auction.py         # Market-based allocation
│   ├── fleet_monitor.py        # Health aggregation
│   ├── resource_map.py         # Probabilistic map manager
│   └── orchestrator_node.py    # Main ROS 2 node
├── selene_agent/               # Per-robot autonomy
│   ├── fsm.py                  # Finite state machine
│   ├── navigator.py            # Path planning + obstacle avoidance
│   ├── energy_manager.py       # Battery tracking + budget
│   ├── perception.py           # Sensor fusion pipeline
│   ├── skills/                 # Modular task skills
│   │   ├── prospect.py
│   │   ├── excavate.py
│   │   ├── haul.py
│   │   └── recharge.py
│   └── agent_node.py           # Main ROS 2 node
├── selene_hal/                 # Hardware Abstraction Layer
│   ├── robot_description.py    # RCDL parser
│   ├── actuator_interface.py
│   └── sensor_interface.py
├── selene_sim/                 # Simulation environment
│   ├── worlds/                 # Gazebo world files
│   ├── models/                 # Robot URDF/SDF models
│   └── launch/                 # ROS 2 launch files
├── selene_dashboard/           # Web-based mission control
│   ├── src/
│   │   ├── App.jsx
│   │   ├── FleetMap.jsx
│   │   ├── ResourceHeatmap.jsx
│   │   ├── TaskQueue.jsx
│   │   └── RobotDetail.jsx
│   └── package.json
├── selene_isru/                # ISRU process models
│   ├── thermal_mining.py
│   ├── electrolysis.py
│   └── logistics.py
└── README.md
```

---

## 9. Competitive Landscape & Differentiation

| Competitor / Project | Focus | SELENE Differentiator |
|---|---|---|
| NASA CADRE | Multi-rover exploration autonomy demo | SELENE adds ISRU process control, full value chain orchestration, and is designed for operational scale |
| SRCP2 Solutions | Competition-grade ISRU coordination | SELENE is designed as production software, not competition code — modular, extensible, commercially viable |
| SoftServe Orchestrator | Hardware-agnostic fleet orchestration | SELENE adds deep ISRU domain models (resource maps, process control, extraction optimization) |
| Lunarminer | Bio-inspired swarm ISRU framework | SELENE uses proven engineering architectures (HTN, task auction) rather than bio-inspired paradigms |
| Astrobotic / Intuitive Machines | Lander and delivery platforms | SELENE is complementary — the software layer that runs on top of delivered hardware |

**SELENE's unique position:** The only proposed software suite that spans the entire ISRU value chain (prospect → extract → process → transport → store) with a fleet management architecture designed to generalize beyond the Moon.

---

## 10. Key References & Prior Art

- Martinez Rocamora et al. (2023) — "Multi-robot cooperation for lunar ISRU" (Frontiers in Robotics and AI). Comprehensive SRCP2 solution with task planning, docking, and hazard estimation.
- NASA CADRE Mission — Semi-centralized cooperative exploration with Voronoi-based area partitioning.
- Lunarminer Framework (2024) — Bio-inspired swarm robotics for Shackleton Crater water extraction using ROS simulation.
- NASA SRCP2 Federal Register (2019) — $1M prize competition defining the heterogeneous robot fleet ISRU problem.
- Sowers & Dreyer (2019) — Original thermal mining concept for lunar PSR volatiles.
- Schreiner et al. — Parametric sizing model for Molten Regolith Electrolysis reactors.
- Banerjee et al. (2025) — First ML-based robot control on ISS, 50–60% faster planning (Stanford/iSpaRo).
- SoftServe (2025) — Multi-robot orchestration platform using NVIDIA Omniverse/Isaac Sim.
- NASA Progress Review of Lunar ISRU Development: 2019–2025 (NTRS, April 2025).

---

*Document prepared: April 1, 2026*
*Project codename: SELENE*
*Status: Pre-prototype planning — ready for development handoff*
