# SELENE Sprint 0 Prototype — Product Requirements Document

**Version:** 1.1
**Date:** April 1, 2026
**Status:** Draft
**Author:** JusHoya
**Project:** SELENE — Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Objectives & Success Criteria](#2-objectives--success-criteria)
3. [Stakeholders & User Personas](#3-stakeholders--user-personas)
4. [System Overview](#4-system-overview)
5. [Functional Requirements](#5-functional-requirements)
   - 5.1 [Simulation Environment](#51-simulation-environment)
   - 5.2 [Fleet Orchestration Engine](#52-fleet-orchestration-engine)
   - 5.3 [Agent Autonomy Stack](#53-agent-autonomy-stack)
   - 5.4 [Resource Mapping System](#54-resource-mapping-system)
   - 5.5 [ISRU Process Models](#55-isru-process-models)
   - 5.6 [Mission Control Dashboard](#56-mission-control-dashboard)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Data Requirements](#7-data-requirements)
8. [Interface Specifications](#8-interface-specifications)
9. [User Stories & Scenarios](#9-user-stories--scenarios)
10. [Acceptance Criteria & Integration Demos](#10-acceptance-criteria--integration-demos)
11. [Architecture & Design Constraints](#11-architecture--design-constraints)
12. [Dependencies & Assumptions](#12-dependencies--assumptions)
13. [Package Structure & Conventions](#13-package-structure--conventions)
14. [Phased Implementation Approach](#14-phased-implementation-approach)
15. [Risk Register (Prototype-Specific)](#15-risk-register-prototype-specific)
16. [Open Questions](#16-open-questions)
17. [Glossary](#17-glossary)

---

## 1. Introduction

### 1.1 Purpose

This PRD defines the requirements for the SELENE Sprint 0 Prototype — a simulation-based demonstration of the core fleet orchestration concept for autonomous lunar ISRU operations. The prototype is the foundational deliverable from which all subsequent development will build.

### 1.2 Scope

The Sprint 0 Prototype is scoped to demonstrate **end-to-end fleet coordination in simulation**: a heterogeneous fleet of 3 robot types (Scout, Excavator, Hauler) cooperating to prospect for, extract, and transport lunar water ice within a simulated lunar environment. The prototype will prove out core architectural decisions (task auction, HTN planning, FSM-based agent autonomy, probabilistic resource mapping) and provide a web-based mission control dashboard for human supervision.

### 1.3 Out of Scope (Sprint 0)

The following are explicitly deferred beyond Sprint 0:

- Integration with physical robot hardware
- Advanced ML models (learned terrain traversability, RL-based drilling, foundation model planners)
- Full ISRU process control (MRE/FFC reactor orchestration, electrolysis endpoint detection)
- Multi-body generalization (Mars, asteroid, orbital operations)
- Formal verification of safety-critical paths
- Cooperative SLAM and multi-agent map fusion (beyond basic resource map updates)
- Delay-tolerant networking simulation (Earth-Moon latency)
- Predictive maintenance and degradation models
- Production deployment, security hardening, or space-rated compute optimization

---

## 2. Objectives & Success Criteria

### 2.1 Primary Objectives

| ID | Objective | Rationale |
|---|---|---|
| OBJ-1 | Demonstrate autonomous multi-robot ISRU cycle in simulation | Validate core value proposition — heterogeneous fleet coordination across prospect → extract → transport |
| OBJ-2 | Prove task auction allocation works for heterogeneous fleets | Validate market-based task distribution as the orchestration paradigm |
| OBJ-3 | Show dynamic task reallocation on robot failure | Demonstrate graceful degradation — a core architectural requirement |
| OBJ-4 | Show adaptive survey behavior by scout robots | Demonstrate intelligent exploration, not just fixed grid patterns |
| OBJ-5 | Provide human-readable mission oversight via dashboard | Validate the human-in-the-loop supervision concept |

### 2.2 Success Criteria

| ID | Criterion | Measurement |
|---|---|---|
| SC-1 | Complete prospect → extract → transport cycle with 3+ cooperating robots | End-to-end scenario completes without manual intervention |
| SC-2 | Dynamic reallocation when a robot is disabled mid-mission | Remaining robots absorb tasks within 2 re-planning cycles; mission completes |
| SC-3 | Scout convergence on high-signal resource areas | Scouts demonstrably shift survey waypoints toward detected ice signatures vs. uniform grid |
| SC-4 | Dashboard displays real-time fleet state | Robot positions, states, battery levels, resource map update within 1 second of simulation state change |
| SC-5 | Task auction produces sensible allocations | Nearest capable robot with sufficient energy wins bid >80% of the time (vs. random assignment baseline) |
| SC-6 | System runs stable for 30+ simulated minutes | No crashes, deadlocks, or orphaned tasks during a continuous 30-minute simulation run |

---

## 3. Stakeholders & User Personas

### 3.1 Mission Operator

**Role:** Earth-based human supervisor monitoring fleet operations via the Mission Control Dashboard.

**Needs:**
- Real-time visibility into fleet state (positions, health, task assignments)
- Ability to understand the resource map and extraction progress
- Ability to manually inject tasks or override robot assignments
- Alerts when autonomous systems escalate decisions

**Interaction mode:** Web browser, primarily observation with occasional intervention.

### 3.2 Robotics Engineer (Developer)

**Role:** Developer building, testing, and extending the SELENE system.

**Needs:**
- Clear, modular code architecture with well-defined interfaces
- Ability to add new robot types without modifying orchestration logic
- Ability to swap simulation backends (Gazebo ↔ Isaac Sim)
- Rich logging and debugging tools (RViz2 visualization, ROS 2 topic introspection)
- Reproducible simulation scenarios for regression testing

**Interaction mode:** Terminal, IDE, RViz2, ROS 2 CLI tools.

### 3.3 Mission Planner

**Role:** Defines high-level mission objectives and constraints that the fleet should execute.

**Needs:**
- Ability to specify extraction targets (e.g., "Collect 100 kg ice from Zone A")
- Ability to define no-go zones, energy budgets, and scheduling constraints
- Visibility into how objectives decompose into robot-level tasks

**Interaction mode:** Dashboard task injection interface.

---

## 4. System Overview

### 4.1 Context Diagram

```
                    ┌──────────────────────┐
                    │   Mission Operator    │
                    │   (Web Browser)       │
                    └──────────┬───────────┘
                               │ HTTP/WebSocket
                    ┌──────────▼───────────┐
                    │  Mission Control      │
                    │  Dashboard            │
                    │  (selene_dashboard)   │
                    └──────────┬───────────┘
                               │ rosbridge / REST API
┌──────────────────────────────▼──────────────────────────────┐
│                  ROS 2 Computation Graph                      │
│                                                              │
│  ┌─────────────────────┐    ┌──────────────────────────┐    │
│  │ Fleet Orchestrator   │◄──►│ Resource Map Manager     │    │
│  │ (selene_orchestrator)│    │ (selene_orchestrator)    │    │
│  └─────┬───┬───┬───────┘    └──────────────────────────┘    │
│        │   │   │                                             │
│   ┌────▼┐ ┌▼───▼┐ ┌─────┐                                  │
│   │Scout│ │Excav│ │Haulr│   (selene_agent instances)        │
│   │Agent│ │Agent│ │Agent│                                    │
│   └──┬──┘ └──┬──┘ └──┬──┘                                  │
│      │       │       │                                       │
│  ┌───▼───────▼───────▼───┐                                  │
│  │  Simulation Bridge     │                                  │
│  │  (selene_sim)          │                                  │
│  └───────────┬────────────┘                                  │
│              │                                               │
└──────────────▼───────────────────────────────────────────────┘
        ┌──────▼──────┐
        │ Gazebo /    │
        │ Isaac Sim   │
        └─────────────┘
```

### 4.2 Technology Stack (Sprint 0)

| Component | Technology | Version/Notes |
|---|---|---|
| Robot middleware | ROS 2 Humble Hawksbill | LTS, DDS-based |
| Simulation | Gazebo Harmonic (primary), Isaac Sim (stretch) | High-fidelity physics |
| Build system | colcon | Standard ROS 2 build |
| Orchestration language | Python 3.10+ | Type-annotated |
| Agent autonomy | Python 3.10+ | Performance-critical paths may use C++ in future |
| Path planning | A* on occupancy grid | Python implementation, NumPy-accelerated |
| Resource map | NumPy + SciPy | Probabilistic grid with Bayesian updates |
| Dashboard frontend | React (JSX) | Single-page application |
| Dashboard transport | rosbridge_suite / roslibjs | WebSocket bridge to ROS 2 |
| Visualization | RViz2 | Developer debugging + resource map overlay |
| Testing | pytest, launch_testing | Unit + integration |
| CI | GitHub Actions | Lint, test, sim-in-docker |

---

## 5. Functional Requirements

### 5.1 Simulation Environment

**Package:** `selene_sim`

#### FR-SIM-1: Lunar Terrain World

| Field | Value |
|---|---|
| **ID** | FR-SIM-1 |
| **Priority** | P0 (Must Have) |
| **Description** | Provide a Gazebo Harmonic world file representing a lunar surface operational area. |
| **Details** | The terrain must include: (a) an illuminated zone with gentle slopes (0-15 deg) suitable for a processing base, (b) at least one permanently shadowed region (PSR) represented as a darkened, flat-bottomed crater zone, (c) varied terrain with rocks, small craters, and slopes to test navigation, (d) a defined operational boundary (~500m x 500m area). Ground texture should use a regolith-like appearance. Gravity must be set to lunar (1.62 m/s^2). |
| **Acceptance** | World loads in Gazebo Harmonic. Robots spawn and can drive on the terrain. PSR zone is visually and logically distinct. |

#### FR-SIM-2: Scout Robot Model

| Field | Value |
|---|---|
| **ID** | FR-SIM-2 |
| **Priority** | P0 |
| **Description** | Provide a Scout robot model (URDF/SDF) with sensor suite for prospecting. |
| **Details** | Four-wheeled rover chassis. Sensors: (a) simulated neutron spectrometer — publishes scalar "ice concentration" reading based on proximity to hidden ice deposits in the world, (b) simulated ground-penetrating radar — publishes subsurface profile data, (c) stereo camera pair for navigation, (d) IMU, (e) wheel odometry. Must include a battery plugin that depletes energy proportional to distance traveled and sensor activation time. Mass: ~50 kg class. Max speed: 0.5 m/s. |
| **Acceptance** | Scout spawns, drives, publishes sensor topics, battery depletes over time. |

#### FR-SIM-3: Excavator Robot Model

| Field | Value |
|---|---|
| **ID** | FR-SIM-3 |
| **Priority** | P0 |
| **Description** | Provide an Excavator robot model with drilling/heating actuator for ice extraction. |
| **Details** | Six-wheeled rover chassis (heavier, more powerful than Scout). Actuators: (a) simulated drill/heating element — when activated at a location with ice, produces "extracted material" at a rate proportional to ice concentration and power applied, (b) onboard hopper with capacity limit (e.g., 20 kg). Sensors: stereo camera, IMU, wheel odometry, hopper fill-level sensor. Battery: larger than Scout but depletes faster during extraction operations. Mass: ~150 kg class. Max speed: 0.3 m/s. |
| **Acceptance** | Excavator spawns, drives, activates drill at ice location, hopper fill level increases, battery depletes faster during extraction. |

#### FR-SIM-4: Hauler Robot Model

| Field | Value |
|---|---|
| **ID** | FR-SIM-4 |
| **Priority** | P0 |
| **Description** | Provide a Hauler robot model with transport bin for material logistics. |
| **Details** | Six-wheeled rover chassis optimized for load carrying. Actuators: (a) transport bin with capacity limit (e.g., 50 kg), (b) load/unload interface — can receive material from Excavator hopper or dump at processing site. Sensors: stereo camera, IMU, wheel odometry, bin load-cell sensor. Battery: large capacity, moderate drain. Mass: ~100 kg class (empty). Max speed: 0.4 m/s (empty), 0.25 m/s (loaded). |
| **Acceptance** | Hauler spawns, drives, receives load from Excavator (simulated transfer), speed reduces when loaded, dumps load at designated point. |

#### FR-SIM-5: Physics & Energy Model

| Field | Value |
|---|---|
| **ID** | FR-SIM-5 |
| **Priority** | P0 |
| **Description** | Simulate basic physics affecting robot operations. |
| **Details** | (a) Terrain friction varies by surface type (regolith vs. rock), (b) slope effects on energy consumption (uphill costs more, downhill costs less), (c) energy consumption model: base idle draw + locomotion draw (proportional to speed and slope) + actuator draw (drill/sensors), (d) simulated solar charging zone — robots in the illuminated area can recharge at a defined rate, (e) no recharging in PSR zones. |
| **Acceptance** | Measurable difference in energy consumption between flat travel, uphill travel, and extraction operations. Robots recharge in solar zone. |

#### FR-SIM-6: Ice Deposit Placement

| Field | Value |
|---|---|
| **ID** | FR-SIM-6 |
| **Priority** | P0 |
| **Description** | Define hidden ice deposits within the PSR that scouts can detect. |
| **Details** | Ice deposits are defined as volumetric regions within the PSR with associated concentration values (0–10 wt%). Multiple deposits with varying concentrations and sizes. Deposits are not directly visible — they are sensed through the Scout's simulated neutron spectrometer. A ground truth file defines deposit locations and concentrations for validation. Sensor readings include Gaussian noise proportional to distance from deposit center. |
| **Acceptance** | Scout sensor readings correlate with proximity to deposits. Noise is present. Ground truth file can be compared against sensed data. |

#### FR-SIM-7: Launch Configuration

| Field | Value |
|---|---|
| **ID** | FR-SIM-7 |
| **Priority** | P0 |
| **Description** | ROS 2 launch files that start the full simulation scenario. |
| **Details** | (a) A primary launch file that starts Gazebo, spawns all robots (configurable count per type), starts the orchestrator, and starts all agent nodes, (b) a dashboard launch file that starts the web server and rosbridge, (c) parameterized: number of scouts (default 2), excavators (default 1), haulers (default 1), (d) configurable world file and ice deposit layout. |
| **Acceptance** | Single `ros2 launch` command brings up full system. Robot counts are parameterized. |

---

### 5.2 Fleet Orchestration Engine

**Package:** `selene_orchestrator`

#### FR-ORC-1: Orchestrator ROS 2 Node

| Field | Value |
|---|---|
| **ID** | FR-ORC-1 |
| **Priority** | P0 |
| **Description** | A ROS 2 lifecycle node that serves as the central fleet orchestrator. |
| **Details** | The orchestrator node: (a) subscribes to all robot state topics, (b) publishes task assignments, (c) manages the task queue, (d) runs the HTN planner and task auction, (e) maintains the global resource map, (f) exposes services for mission control interactions (task injection, robot override). Must be a lifecycle node supporting configure → activate → deactivate transitions. Publishes a heartbeat topic at 1 Hz for liveness detection. |
| **Acceptance** | Node starts, transitions through lifecycle states, subscribes to robot state, publishes task assignments. |

#### FR-ORC-2: Task Auction Protocol

| Field | Value |
|---|---|
| **ID** | FR-ORC-2 |
| **Priority** | P0 |
| **Description** | Market-based task allocation where the orchestrator broadcasts tasks and agents bid. |
| **Details** | Protocol flow: (1) Orchestrator publishes a `TaskAnnouncement` message with task type, location, estimated effort, and required capabilities. (2) Eligible agents (matching capability + sufficient energy) respond with a `BidResponse` containing a utility score computed as: `bid = w1 * (1/distance) + w2 * (energy_remaining/energy_required) + w3 * capability_match`. Weights w1, w2, w3 are configurable. (3) Orchestrator selects the highest-bidding agent and publishes a `TaskAssignment`. (4) If no bids are received within a timeout (configurable, default 5s sim-time), the task is re-announced or queued. (5) If the assigned agent fails or rejects, the task is re-auctioned. |
| **Acceptance** | Tasks are distributed to the most suitable available robot. Reassignment occurs on failure. Suboptimal assignments (e.g., faraway robot with low battery) are avoided. |

#### FR-ORC-3: HTN Task Planner

| Field | Value |
|---|---|
| **ID** | FR-ORC-3 |
| **Priority** | P0 |
| **Description** | Hierarchical Task Network planner that decomposes mission objectives into robot-level tasks. |
| **Details** | The planner accepts high-level objectives and decomposes them into ordered primitive tasks. **Supported decompositions for Sprint 0:** (a) `CollectIce(zone, quantity)` → `Survey(zone)` → `SelectSite(zone)` → `Excavate(site, quantity)` → `Haul(site, depot, quantity)`. (b) `Survey(zone)` → Multiple `Prospect(waypoint)` tasks distributed across available scouts. (c) `Excavate(site, quantity)` → `Navigate(site)` → `Extract(quantity)` → `SignalHauler()`. (d) `Haul(site, depot, quantity)` → `Navigate(site)` → `Load()` → `Navigate(depot)` → `Unload()`. Each primitive task has preconditions (e.g., robot must have sufficient energy, excavator must be at site) and effects (e.g., ice deposited at depot). Temporal ordering is enforced — extraction cannot begin before survey identifies a site. |
| **Acceptance** | Given "Collect 100 kg ice from Zone A," the planner produces a valid task graph with correct ordering and robot-type constraints. |

#### FR-ORC-4: Fleet State Monitor

| Field | Value |
|---|---|
| **ID** | FR-ORC-4 |
| **Priority** | P0 |
| **Description** | Aggregates health telemetry from all agents and detects anomalies. |
| **Details** | The monitor: (a) subscribes to each robot's `RobotState` topic (published at 2 Hz minimum), (b) maintains a fleet state table: robot ID, type, position (x, y, theta), current FSM state, battery level (%), current task ID, velocity, last heartbeat timestamp, (c) detects robot failure via heartbeat timeout (configurable, default 10s sim-time), (d) on failure detection: marks robot as OFFLINE, triggers task reallocation for any task the robot held, publishes a `FleetAlert` message, (e) publishes aggregated fleet state at 1 Hz for the dashboard. |
| **Acceptance** | Disabling a robot in simulation triggers failure detection within the timeout window. Its tasks are reallocated. Dashboard reflects the updated state. |

#### FR-ORC-5: Dynamic Task Reallocation

| Field | Value |
|---|---|
| **ID** | FR-ORC-5 |
| **Priority** | P0 |
| **Description** | When a robot fails or cannot complete its assigned task, the orchestrator reassigns the task. |
| **Details** | Reallocation triggers: (a) robot heartbeat timeout (FR-ORC-4), (b) robot reports task failure (actuator error, stuck detection), (c) robot's energy drops below task-completion threshold. On trigger: (1) the in-progress task is marked as INTERRUPTED with progress metadata (e.g., "50 kg of 100 kg extracted"), (2) the task (or remaining portion) is re-entered into the auction, (3) any dependent downstream tasks are paused until the interrupted task is reassigned. The system must handle cascading failures — if the only excavator fails, extraction tasks are queued until the excavator recovers or a new one becomes available, while scouts continue prospecting independently. |
| **Acceptance** | SC-2: Disabling one robot mid-mission causes reallocation; the mission still completes using remaining robots. |

#### FR-ORC-6: Energy-Aware Scheduling

| Field | Value |
|---|---|
| **ID** | FR-ORC-6 |
| **Priority** | P1 (Should Have) |
| **Description** | Task scheduling accounts for robot energy state and recharging logistics. |
| **Details** | (a) Before assigning a task, the orchestrator estimates the energy required (travel to site + task execution + return to recharge zone) using a simple model: `energy_cost = distance * rate_per_meter + task_energy_estimate`. (b) If a robot's current energy is insufficient for the round-trip, the task is not assigned to it (it won't bid). (c) The orchestrator proactively schedules recharge tasks when a robot's energy drops below a configurable threshold (default 30%). (d) Recharge tasks have higher priority than regular tasks to prevent robots from stranding. |
| **Acceptance** | Robots do not accept tasks they cannot complete energy-wise. Robots recharge before stranding. No robots run out of energy in unexpected locations during normal operation. |

---

### 5.3 Agent Autonomy Stack

**Package:** `selene_agent`

#### FR-AGT-1: Agent ROS 2 Node

| Field | Value |
|---|---|
| **ID** | FR-AGT-1 |
| **Priority** | P0 |
| **Description** | A ROS 2 lifecycle node that runs the autonomy stack for a single robot. |
| **Details** | Each robot instance runs one agent node parameterized by: robot ID (unique string), robot type (scout/excavator/hauler), initial position, robot capability descriptor (loaded from RCDL YAML file). The node: (a) publishes `RobotState` at 2 Hz, (b) subscribes to `TaskAnnouncement` and `TaskAssignment`, (c) runs the FSM, navigator, energy manager, and skill executor, (d) exposes a service for direct override commands from mission control. |
| **Acceptance** | Multiple agent nodes run concurrently, each controlling its own simulated robot independently. |

#### FR-AGT-2: Finite State Machine

| Field | Value |
|---|---|
| **ID** | FR-AGT-2 |
| **Priority** | P0 |
| **Description** | FSM governing robot behavioral state transitions. |
| **Details** | States: `IDLE` → `BIDDING` → `ASSIGNED` → `NAVIGATING` → `WORKING` → `RETURNING` → `RECHARGING` → `IDLE`. Additional states: `ERROR` (recoverable fault), `OFFLINE` (shutdown/failed). Transitions: (a) IDLE → BIDDING: on receiving a TaskAnnouncement matching capabilities, (b) BIDDING → ASSIGNED: on winning the auction (receiving TaskAssignment), (c) BIDDING → IDLE: on losing the auction or timeout, (d) ASSIGNED → NAVIGATING: immediately, with target = task location, (e) NAVIGATING → WORKING: on arrival at task location (within tolerance radius), (f) WORKING → RETURNING: on task completion or hopper full, (g) RETURNING → RECHARGING: on arrival at recharge station and energy below threshold, (h) RETURNING → IDLE: on arrival at recharge station and energy above threshold, (i) RECHARGING → IDLE: on energy reaching full (or configurable threshold, default 90%), (j) Any state → ERROR: on fault detection, (k) ERROR → IDLE: on recovery (automatic retry up to 3 times, then escalate). The FSM must be event-driven and log all state transitions with timestamps. |
| **Acceptance** | FSM state transitions are observable via RobotState topic. All listed transitions fire correctly. No invalid state transitions occur. |

#### FR-AGT-3: Path Planning (A*)

| Field | Value |
|---|---|
| **ID** | FR-AGT-3 |
| **Priority** | P0 |
| **Description** | Global path planning using A* on an occupancy grid. |
| **Details** | (a) The agent maintains a local copy of the terrain occupancy grid (received from the orchestrator's shared map or built from local perception), (b) A* search on a 2D grid with 8-connectivity, (c) cost function includes: distance + slope penalty + known-hazard penalty, (d) path is recomputed if obstacles are detected en route (local replanning), (e) path is published as a `nav_msgs/Path` for visualization in RViz2, (f) grid resolution: 1m x 1m cells (configurable). |
| **Acceptance** | Robots navigate around obstacles. Paths are visible in RViz2. Paths avoid steep slopes and known hazards. |

#### FR-AGT-4: Local Obstacle Avoidance

| Field | Value |
|---|---|
| **ID** | FR-AGT-4 |
| **Priority** | P0 |
| **Description** | Reactive obstacle avoidance for obstacles not on the global map. |
| **Details** | (a) Uses simulated stereo camera depth data to detect obstacles within a configurable range (default 5m), (b) if an obstacle is detected on the planned path, the robot slows and steers around it using a Vector Field Histogram (VFH) or simple potential field approach, (c) if avoidance fails (e.g., dead end), the robot stops and requests a global replan, (d) publishes detected obstacles to the shared map for future planning by all robots. |
| **Acceptance** | Robot avoids a rock placed in its path that was not on the initial map. Robot does not collide with other robots. |

#### FR-AGT-5: Energy Manager

| Field | Value |
|---|---|
| **ID** | FR-AGT-5 |
| **Priority** | P0 |
| **Description** | Tracks battery state and enforces energy budgets. |
| **Details** | (a) Subscribes to the battery state topic from simulation, (b) estimates remaining range based on current consumption rate, (c) triggers a `RETURN_TO_BASE` override if energy drops below critical threshold (configurable, default 15%) — this preempts any current task, (d) refuses to bid on tasks that exceed estimated energy budget, (e) publishes energy state as part of `RobotState` message. |
| **Acceptance** | Robot autonomously returns to recharge before battery is fully depleted. Robot does not bid on tasks it cannot energy-afford. |

#### FR-AGT-6: Skill Library

| Field | Value |
|---|---|
| **ID** | FR-AGT-6 |
| **Priority** | P0 |
| **Description** | Modular task skills that the FSM's WORKING state dispatches. |
| **Details** | Each skill is a self-contained Python class with `start()`, `update()` (called per tick), `is_complete()`, `abort()`, and `get_progress()` methods. **Sprint 0 skills:** (a) **Prospect**: Drive to waypoint, activate neutron spectrometer for configurable duration, record reading, report result to resource map. (b) **Excavate**: Activate drill/heater at current location, monitor hopper fill level, stop when hopper is full or deposit is exhausted. (c) **Haul**: Navigate to Excavator, receive load (simulated transfer when co-located), navigate to depot, dump load. (d) **Recharge**: Navigate to solar charging zone, remain stationary until battery threshold reached. Skills publish progress as a float [0.0, 1.0] for dashboard display. |
| **Acceptance** | Each skill executes its behavior correctly. Skills can be aborted mid-execution. Progress is reported. |

#### FR-AGT-7: Hardware Abstraction Layer

| Field | Value |
|---|---|
| **ID** | FR-AGT-7 |
| **Priority** | P1 |
| **Description** | Standardized interfaces that decouple agent logic from specific robot hardware. |
| **Details** | (a) A `RobotCapabilityDescriptor` YAML schema (RCDL) that declares: robot type, sensor list (name, type, topic, frame), actuator list (name, type, topic, limits), kinematic properties (max speed, turning radius), energy properties (battery capacity, consumption rates). (b) The HAL exposes uniform Python interfaces: `get_sensor(name)` → sensor reader, `get_actuator(name)` → actuator commander, `get_kinematics()` → motion constraints. (c) Agent code uses HAL interfaces exclusively — never subscribes to hardware-specific topics directly. (d) Sprint 0: HAL wraps Gazebo simulation interfaces. The same agent code should be able to run against a different simulator by swapping the HAL implementation. |
| **Acceptance** | Agent autonomy code contains zero direct references to Gazebo-specific topics. A new robot type can be added by providing an RCDL file and HAL driver without modifying agent logic. |

---

### 5.4 Resource Mapping System

**Package:** `selene_orchestrator` (submodule)

#### FR-MAP-1: Probabilistic Resource Grid

| Field | Value |
|---|---|
| **ID** | FR-MAP-1 |
| **Priority** | P0 |
| **Description** | A probabilistic occupancy grid representing ice concentration estimates across the operational area. |
| **Details** | (a) Grid covers the full operational area at 1m x 1m resolution, (b) each cell stores: mean ice concentration estimate (wt%), variance (uncertainty), number of observations, last update timestamp, (c) initialized with uniform prior (no information), (d) stored as NumPy arrays for efficient computation, (e) published as a custom `ResourceMap` message at configurable rate (default 0.5 Hz), (f) supports serialization/deserialization for persistence. |
| **Acceptance** | Grid initializes with uniform uncertainty. Grid dimensions match the operational area. |

#### FR-MAP-2: Bayesian Sensor Fusion

| Field | Value |
|---|---|
| **ID** | FR-MAP-2 |
| **Priority** | P0 |
| **Description** | Scout sensor readings update the resource map using Bayesian inference. |
| **Details** | When a Scout reports a prospecting result: (a) the reading is modeled as a Gaussian observation with known sensor noise characteristics, (b) the map cell (and neighboring cells within the sensor footprint) are updated using Bayesian update: posterior = prior * likelihood, (c) multiple observations at the same cell reduce variance (uncertainty decreases with more data), (d) observations from different scouts at the same cell are fused consistently, (e) the update propagates to a configurable neighborhood (sensor footprint radius, default 5m) with distance-decayed influence. |
| **Acceptance** | Multiple scout observations at the same location reduce map uncertainty. Map converges toward ground truth ice concentrations with sufficient observations. |

#### FR-MAP-3: Adaptive Survey Planning

| Field | Value |
|---|---|
| **ID** | FR-MAP-3 |
| **Priority** | P0 |
| **Description** | Scout waypoints are dynamically chosen to maximize information gain. |
| **Details** | Instead of a fixed grid survey, the orchestrator selects the next prospect waypoint for each scout based on: (a) **information gain**: cells with highest uncertainty (variance) are prioritized, (b) **proximity**: nearby high-uncertainty cells preferred over distant ones (energy cost), (c) **signal follow-up**: cells adjacent to detected high-concentration readings are prioritized for boundary delineation. Algorithm: rank candidate cells by `score = w_unc * variance + w_sig * neighbor_signal - w_dist * distance_to_robot`, select the top-scoring cell as the next waypoint. Weights are configurable. |
| **Acceptance** | SC-3: Scouts visibly converge on ice deposit areas rather than uniformly sampling the entire terrain. Survey coverage is non-uniform, focusing on high-value areas. |

#### FR-MAP-4: RViz2 Visualization

| Field | Value |
|---|---|
| **ID** | FR-MAP-4 |
| **Priority** | P1 |
| **Description** | Resource map displayed as a color-coded overlay in RViz2. |
| **Details** | (a) Published as an `OccupancyGrid` or `Marker` array topic, (b) color coding: blue (low concentration / no ice) → red (high concentration), (c) alpha channel encodes certainty (transparent = uncertain, opaque = confident), (d) updates in real-time as scouts prospect. |
| **Acceptance** | Map is visible in RViz2 and updates as scouts explore. Color coding is readable and matches underlying data. |

---

### 5.5 ISRU Process Models

**Package:** `selene_isru`

#### FR-ISRU-1: Thermal Mining Model

| Field | Value |
|---|---|
| **ID** | FR-ISRU-1 |
| **Priority** | P1 |
| **Description** | Simplified thermal mining process model for extraction rate calculation. |
| **Details** | When an Excavator activates its drill/heater at a location with ice: (a) extraction rate (kg/s) = `efficiency * power_applied * ice_concentration / energy_per_kg`, (b) efficiency is a configurable parameter (default 0.3 for Sprint 0), (c) the extraction rate is affected by depth — surface ice is easier to extract, (d) the model publishes telemetry: current extraction rate, cumulative extracted mass, estimated remaining deposit at site, (e) deposit depletion is tracked — extraction reduces the ice concentration at that grid cell. |
| **Acceptance** | Extraction rate correlates with ice concentration. Deposit depletes over time. Telemetry is published. |

#### FR-ISRU-2: Logistics Model

| Field | Value |
|---|---|
| **ID** | FR-ISRU-2 |
| **Priority** | P1 |
| **Description** | Track material flow through the extract → haul → deposit pipeline. |
| **Details** | (a) Track total material extracted per site, (b) track material in transit (on haulers), (c) track material deposited at the processing depot, (d) maintain a running inventory: `total_deposited = Σ(hauler_dumps)`, (e) the orchestrator uses inventory data to determine mission progress toward the extraction target (e.g., "67 of 100 kg collected"). |
| **Acceptance** | Material quantities are consistent — what is extracted equals what is hauled plus what is in transit. No material is lost or duplicated. |

---

### 5.6 Mission Control Dashboard

**Package:** `selene_dashboard`

#### FR-DASH-1: Fleet Map View

| Field | Value |
|---|---|
| **ID** | FR-DASH-1 |
| **Priority** | P0 |
| **Description** | 2D top-down map showing robot positions, states, and paths in real time. |
| **Details** | (a) Displays the operational area as a 2D overhead view, (b) each robot shown as an icon with: unique color per type (scout=blue, excavator=orange, hauler=green), label with robot ID, state indicator (color-coded by FSM state), (c) battery level shown as a small gauge next to each robot icon, (d) current planned path displayed as a line from robot to destination, (e) updates at 1 Hz minimum via WebSocket from rosbridge, (f) map is pannable and zoomable. |
| **Acceptance** | All robots visible on map with correct positions. State changes are reflected within 1 second. |

#### FR-DASH-2: Resource Heatmap Overlay

| Field | Value |
|---|---|
| **ID** | FR-DASH-2 |
| **Priority** | P0 |
| **Description** | Overlay the probabilistic resource map as a heatmap on the fleet map. |
| **Details** | (a) Toggle-able layer on top of the fleet map, (b) color scale: transparent/gray (no data / low confidence) → blue (low concentration) → red (high concentration), (c) opacity modulated by confidence — unexplored areas are transparent, well-surveyed areas are opaque, (d) updates as scouts report new data, (e) legend showing the color-concentration scale. |
| **Acceptance** | Heatmap visually matches the resource map data. Explored areas are clearly distinguishable from unexplored areas. |

#### FR-DASH-3: Task Queue Panel

| Field | Value |
|---|---|
| **ID** | FR-DASH-3 |
| **Priority** | P0 |
| **Description** | Display the current task queue with status of each task. |
| **Details** | (a) Table/list showing all tasks: task ID, type, assigned robot (or "unassigned"), status (PENDING, ASSIGNED, IN_PROGRESS, COMPLETED, FAILED), priority, progress (0-100%), (b) tasks sorted by status (in-progress first, then pending, then completed), (c) completed tasks shown in a collapsible history section, (d) clicking a task highlights the assigned robot and destination on the map. |
| **Acceptance** | Task list reflects the orchestrator's task queue. Status updates propagate within 1 second. |

#### FR-DASH-4: Robot Detail Panel

| Field | Value |
|---|---|
| **ID** | FR-DASH-4 |
| **Priority** | P1 |
| **Description** | Detailed view of a selected robot's state and telemetry. |
| **Details** | Clicking a robot on the map or in a list opens a detail panel showing: (a) robot ID, type, and capabilities, (b) current FSM state, (c) battery level with time-to-empty estimate, (d) current task and progress, (e) position (x, y, heading), (f) velocity, (g) recent state transition history (last 10 transitions with timestamps). |
| **Acceptance** | Detail panel shows accurate, real-time data for the selected robot. |

#### FR-DASH-5: Manual Task Injection

| Field | Value |
|---|---|
| **ID** | FR-DASH-5 |
| **Priority** | P1 |
| **Description** | Allow the operator to manually create and inject tasks into the orchestrator. |
| **Details** | (a) Form to create a new task: select task type (Survey Zone, Extract at Site, Haul to Depot), specify target location (click on map or enter coordinates), specify parameters (e.g., quantity), optionally assign to a specific robot, (b) submitted tasks enter the auction like any other task, (c) confirmation dialog before submission. |
| **Acceptance** | Operator can inject a task via the dashboard. The task enters the auction and is assigned to a robot. |

#### FR-DASH-6: Robot Override

| Field | Value |
|---|---|
| **ID** | FR-DASH-6 |
| **Priority** | P2 (Nice to Have) |
| **Description** | Allow the operator to override a robot's current task or send it to a specific location. |
| **Details** | (a) From the robot detail panel: "Send to Location" button — operator clicks a point on the map, robot navigates there, (b) "Cancel Current Task" button — robot aborts current task and returns to IDLE, (c) "Force Recharge" — robot immediately navigates to recharge zone, (d) overrides are logged and visible in the task history. |
| **Acceptance** | Override commands are executed by the target robot. The task system handles the interrupted task gracefully. |

#### FR-DASH-7: Mission Progress Summary

| Field | Value |
|---|---|
| **ID** | FR-DASH-7 |
| **Priority** | P1 |
| **Description** | Summary panel showing overall mission progress. |
| **Details** | (a) Current mission objective and target (e.g., "Collect 100 kg ice from Zone A"), (b) progress bar showing current vs. target, (c) key metrics: total ice extracted, total ice deposited at depot, total distance traveled (fleet), total energy consumed, fleet uptime, (d) elapsed simulation time. |
| **Acceptance** | Metrics are accurate and update in real-time. Progress bar reflects material deposited at depot. |

---

## 6. Non-Functional Requirements

### NFR-1: Performance

| ID | Requirement |
|---|---|
| NFR-1.1 | The orchestrator must process a task auction cycle (announce → collect bids → assign) in under 2 seconds of simulation time for a fleet of up to 10 robots. |
| NFR-1.2 | Agent nodes must maintain a 10 Hz minimum control loop (perception → decision → actuation) for smooth robot operation. |
| NFR-1.3 | The resource map Bayesian update must complete in under 100ms per sensor reading. |
| NFR-1.4 | The dashboard must maintain 1 Hz update rate with up to 10 robots without frame drops. |
| NFR-1.5 | The full simulation (Gazebo + orchestrator + 4 agents + dashboard) must run on a workstation with 16 GB RAM and a mid-range GPU at minimum 0.5x real-time speed. |

### NFR-2: Reliability

| ID | Requirement |
|---|---|
| NFR-2.1 | The system must run for 30+ simulated minutes without crashes, deadlocks, or memory leaks (SC-6). |
| NFR-2.2 | No single robot failure may cause the orchestrator or other agents to crash. |
| NFR-2.3 | The orchestrator must recover from a transient communication dropout with any agent (reconnect within 30 seconds). |

### NFR-3: Modularity & Extensibility

| ID | Requirement |
|---|---|
| NFR-3.1 | Adding a new robot type requires only: (a) an RCDL YAML file, (b) a HAL driver, (c) any new skill classes. No modification to orchestrator or existing agent code. |
| NFR-3.2 | Adding a new skill requires only: (a) a new Python class implementing the Skill interface, (b) registration in the skill registry. No modification to FSM or agent node code. |
| NFR-3.3 | The simulation environment (Gazebo) must be replaceable with an alternative (Isaac Sim) by swapping `selene_sim` and HAL drivers without changing `selene_orchestrator` or `selene_agent`. |

### NFR-4: Observability

| ID | Requirement |
|---|---|
| NFR-4.1 | All ROS 2 topics follow a consistent naming convention: `/<robot_id>/<subsystem>/<topic_name>` (e.g., `/scout_01/state`, `/scout_01/sensors/neutron_spec`). |
| NFR-4.2 | All state transitions, task assignments, and task completions are logged with timestamps at INFO level. |
| NFR-4.3 | Anomalies and errors are logged at WARN/ERROR level with sufficient context for debugging. |
| NFR-4.4 | The system supports ROS 2 bag recording for full scenario replay. |

### NFR-5: Testability

| ID | Requirement |
|---|---|
| NFR-5.1 | Unit tests for: HTN planner decompositions, auction bidding logic, Bayesian map updates, FSM transitions, energy manager thresholds. Minimum 80% code coverage on core logic modules. |
| NFR-5.2 | Integration tests using `launch_testing`: full scenario startup, single auction cycle, robot failure and reallocation. |
| NFR-5.3 | A deterministic simulation mode (fixed random seeds, no wall-clock dependencies) for reproducible test runs. |

---

## 7. Data Requirements

### 7.1 ROS 2 Message Definitions

**Package:** `selene_msgs`

#### MSG-1: RobotState.msg

```
string robot_id
string robot_type               # "scout", "excavator", "hauler"
string fsm_state                # "IDLE", "NAVIGATING", "WORKING", etc.
geometry_msgs/Pose2D pose       # x, y, theta
geometry_msgs/Twist velocity
float32 battery_level           # 0.0 to 1.0
string current_task_id          # "" if no task
float32 task_progress           # 0.0 to 1.0
string[] capabilities           # ["prospect", "excavate", "haul"]
builtin_interfaces/Time stamp
```

#### MSG-2: TaskAnnouncement.msg

```
string task_id
string task_type                # "prospect", "excavate", "haul", "recharge"
geometry_msgs/Point target_location
float32 estimated_energy_cost
string[] required_capabilities
float32 priority                # 0.0 (low) to 1.0 (critical)
float32 estimated_duration      # seconds
string parent_task_id           # HTN parent, "" if root
builtin_interfaces/Time deadline
```

#### MSG-3: BidResponse.msg

```
string task_id
string robot_id
float32 bid_score               # higher = more suitable
float32 estimated_arrival_time
float32 energy_after_task       # projected remaining energy
```

#### MSG-4: TaskAssignment.msg

```
string task_id
string robot_id
string task_type
geometry_msgs/Point target_location
string[] parameters             # task-specific key=value pairs
builtin_interfaces/Time assigned_at
```

#### MSG-5: ResourceMapUpdate.msg

```
string scout_id
geometry_msgs/Point location
float32 ice_concentration       # wt% reading
float32 sensor_uncertainty      # standard deviation
builtin_interfaces/Time stamp
```

#### MSG-6: FleetAlert.msg

```
string alert_id
string severity                 # "INFO", "WARN", "ERROR", "CRITICAL"
string source_robot_id
string message
builtin_interfaces/Time stamp
```

#### MSG-7: MissionProgress.msg

```
string objective_description
float32 target_quantity         # kg
float32 extracted_quantity      # kg
float32 in_transit_quantity     # kg
float32 deposited_quantity      # kg
float32 fleet_distance_total   # meters
float32 fleet_energy_total     # kWh consumed
float32 elapsed_sim_time       # seconds
```

### 7.2 Service Definitions

#### SRV-1: InjectTask.srv

```
# Request
string task_type
geometry_msgs/Point target_location
float32 quantity
string assigned_robot_id        # "" for auction
---
# Response
bool success
string task_id
string message
```

#### SRV-2: OverrideRobot.srv

```
# Request
string robot_id
string command                  # "go_to", "cancel_task", "force_recharge"
geometry_msgs/Point target      # for "go_to" command
---
# Response
bool success
string message
```

### 7.3 Configuration Files

#### RCDL Robot Descriptor (YAML)

```yaml
robot_type: scout
kinematic_model: differential_drive
max_speed: 0.5  # m/s
turn_radius: 0.0  # point-turn capable
mass: 50  # kg
battery:
  capacity: 500  # Wh
  idle_draw: 5  # W
  locomotion_draw: 20  # W per m/s
sensors:
  - name: neutron_spectrometer
    type: scalar_field
    topic: sensors/neutron_spec
    range: 10.0  # meters
    noise_stddev: 0.5  # wt%
    power_draw: 10  # W
  - name: stereo_camera
    type: depth_image
    topic: sensors/depth
    range: 20.0
    fov: 90  # degrees
    power_draw: 8
  - name: imu
    type: imu
    topic: sensors/imu
    power_draw: 1
actuators: []  # scouts have no actuators beyond locomotion
capabilities:
  - prospect
```

---

## 8. Interface Specifications

### 8.1 Orchestrator ↔ Agent Interface

| Interface | Type | Direction | Topic/Service | Rate |
|---|---|---|---|---|
| Robot heartbeat/state | Topic | Agent → Orchestrator | `/<robot_id>/state` | 2 Hz |
| Task announcement | Topic | Orchestrator → All Agents | `/orchestrator/task_announce` | Event-driven |
| Bid response | Topic | Agent → Orchestrator | `/orchestrator/bids` | Event-driven |
| Task assignment | Topic | Orchestrator → Specific Agent | `/<robot_id>/task_assign` | Event-driven |
| Resource map update | Topic | Agent → Orchestrator | `/orchestrator/map_update` | Event-driven |
| Fleet alert | Topic | Orchestrator → All | `/orchestrator/alerts` | Event-driven |
| Override command | Service | Dashboard → Agent | `/<robot_id>/override` | On-demand |

### 8.2 Dashboard ↔ ROS 2 Interface

| Interface | Transport | Direction | Details |
|---|---|---|---|
| Fleet state | rosbridge WebSocket | ROS → Dashboard | Subscribe to `/orchestrator/fleet_state` |
| Resource map | rosbridge WebSocket | ROS → Dashboard | Subscribe to `/orchestrator/resource_map` |
| Task queue | rosbridge WebSocket | ROS → Dashboard | Subscribe to `/orchestrator/task_queue` |
| Mission progress | rosbridge WebSocket | ROS → Dashboard | Subscribe to `/orchestrator/mission_progress` |
| Task injection | rosbridge service call | Dashboard → ROS | Call `/orchestrator/inject_task` |
| Robot override | rosbridge service call | Dashboard → ROS | Call `/<robot_id>/override` |

### 8.3 Simulation ↔ Agent Interface

All simulation interfaces are abstracted through the HAL. The HAL implementation for Gazebo maps to:

| HAL Interface | Gazebo Implementation |
|---|---|
| `get_sensor("stereo_camera")` | Subscribes to Gazebo camera plugin topic |
| `get_sensor("neutron_spectrometer")` | Subscribes to custom Gazebo plugin that queries ice deposit ground truth |
| `get_sensor("imu")` | Subscribes to Gazebo IMU plugin topic |
| `get_actuator("drive")` | Publishes to Gazebo diff-drive plugin `cmd_vel` topic |
| `get_actuator("drill")` | Publishes to custom Gazebo plugin controlling extraction |
| `get_battery()` | Subscribes to custom Gazebo battery plugin |

---

## 9. User Stories & Scenarios

### US-1: Full ISRU Cycle (Primary Demo)

**As a** mission operator,
**I want to** issue a "Collect 100 kg ice from the PSR" command and watch the fleet autonomously prospect, extract, and deliver the ice,
**So that** I can validate that the fleet orchestration concept works end-to-end.

**Scenario:**
1. Operator opens the dashboard and sees the fleet at the base station (illuminated zone).
2. Operator injects task: "Collect 100 kg ice from PSR Zone A."
3. HTN planner decomposes: Survey → SelectSite → Excavate → Haul.
4. Scouts are dispatched to survey the PSR. Dashboard shows scouts moving toward the PSR.
5. Resource heatmap updates as scouts report findings. High-concentration areas light up red.
6. Planner selects the best extraction site based on concentration and accessibility.
7. Excavator is dispatched to the selected site. Dashboard shows its path.
8. Excavator arrives and begins extraction. Progress bar shows fill level.
9. When hopper is full, Hauler is dispatched. Hauler loads material from Excavator.
10. Hauler transports material to depot. Depot inventory increases.
11. Cycle repeats (Excavator continues, Hauler shuttles) until 100 kg is deposited.
12. Mission progress panel shows 100/100 kg. Mission marked complete.

**Duration:** ~20-30 simulated minutes.

### US-2: Dynamic Reallocation on Failure

**As a** mission operator,
**I want** the fleet to continue operating when a robot fails mid-mission,
**So that** I can trust the system is resilient.

**Scenario:**
1. Full ISRU cycle is in progress (US-1 underway, ~50 kg collected).
2. Operator disables the Excavator via simulation (simulating hardware failure).
3. Fleet monitor detects heartbeat timeout. Dashboard shows Excavator as OFFLINE with alert.
4. Excavator's in-progress extraction task is marked INTERRUPTED.
5. If a second excavator is available: task is re-auctioned and the backup excavator takes over.
6. If no excavator is available: extraction tasks are queued. Scouts continue prospecting (independent work is not blocked). Dashboard shows queued tasks clearly.
7. Operator re-enables the Excavator. It reconnects, reports IDLE.
8. Queued extraction task is auctioned. The recovered Excavator wins and resumes extraction.
9. Mission eventually completes.

### US-3: Adaptive Scout Convergence

**As a** robotics engineer,
**I want** scouts to converge on detected ice deposits rather than uniformly surveying the area,
**So that** I can validate the adaptive survey algorithm.

**Scenario:**
1. Two scouts begin surveying the PSR with initial high-uncertainty waypoints spread across the zone.
2. Scout 1 detects a moderate ice signal in the northeast of the PSR.
3. The adaptive planner shifts subsequent waypoints for both scouts toward the northeast to delineate the deposit boundary.
4. Scout 2 detects a strong ice signal in the southeast — a separate, richer deposit.
5. The planner now balances scouts between the two deposits: one delineates northeast, the other delineates southeast.
6. RViz2 resource map shows two distinct hot spots emerging from initially uniform uncertainty.
7. Survey concludes with well-delineated deposit boundaries and low uncertainty in deposit areas.

### US-4: Energy-Constrained Operations

**As a** mission operator,
**I want** robots to manage their energy autonomously and never strand themselves,
**So that** I don't need to manually monitor battery levels.

**Scenario:**
1. Hauler is executing a long-distance haul from PSR to depot.
2. Mid-route, the energy manager estimates that the Hauler cannot complete the haul AND return to the recharge zone.
3. Hauler does not attempt the impossible round trip. Instead, it reports the task as INTERRUPTED and returns to recharge.
4. After recharging, the Hauler re-enters the auction for the remaining haul task.
5. No robot is ever stranded with zero battery in an unreachable location.

### US-5: Manual Task Injection

**As a** mission planner,
**I want to** manually direct a scout to investigate a specific location,
**So that** I can override the autonomous survey plan with human insight.

**Scenario:**
1. Operator observes an interesting pattern on the resource heatmap edge.
2. Operator clicks "Inject Task" on the dashboard, selects "Survey," clicks the location on the map.
3. The task enters the auction. A scout bids and is assigned.
4. The scout navigates to the specified location and prospects.
5. Results update the resource map. The operator can now see if their hunch was correct.

---

## 10. Acceptance Criteria & Integration Demos

### 10.1 Integration Demo 1: End-to-End ISRU Cycle

**Preconditions:** Full system launched (Gazebo + orchestrator + 2 scouts + 1 excavator + 1 hauler + dashboard).

**Steps:**
1. Inject mission: "Collect 100 kg ice from PSR Zone A."
2. Observe: scouts survey, resource map builds, extraction site selected, excavator extracts, hauler delivers.
3. Verify: mission progress reaches 100 kg deposited.
4. Verify: no manual intervention required.
5. Verify: total simulation time < 30 minutes.

**Pass/Fail:** All 5 verifications pass.

### 10.2 Integration Demo 2: Robot Failure and Recovery

**Preconditions:** ISRU cycle in progress, ~30-50% complete.

**Steps:**
1. Kill the excavator's agent node (simulate failure).
2. Observe: fleet monitor detects failure within timeout, alert raised.
3. Observe: extraction task marked INTERRUPTED, scouts continue working.
4. Restart the excavator's agent node.
5. Observe: excavator re-registers, wins re-auctioned task, extraction resumes.
6. Verify: mission eventually completes.

**Pass/Fail:** Failure detected, tasks reallocated, mission completes.

### 10.3 Integration Demo 3: Adaptive Survey Convergence

**Preconditions:** Resource map initialized with uniform uncertainty. Known ice deposit locations (ground truth).

**Steps:**
1. Launch 2 scouts to survey PSR.
2. Record the sequence of survey waypoints chosen by adaptive planner.
3. Compare waypoint density near deposits vs. empty areas.
4. Verify: waypoint density near deposits is significantly higher (>2x) than in empty areas by the second half of the survey.

**Pass/Fail:** Quantitative analysis shows convergence.

### 10.4 Integration Demo 4: Energy Management

**Preconditions:** Hauler configured with limited battery (enough for ~1.5 round trips without recharge).

**Steps:**
1. Assign hauling task requiring 2 round trips.
2. Observe: hauler completes first trip, returns to recharge, completes second trip.
3. Verify: hauler never drops below critical energy threshold (15%) outside the recharge zone.
4. Verify: hauler does not attempt a second trip without recharging if insufficient energy.

**Pass/Fail:** No energy threshold violations.

---

## 11. Architecture & Design Constraints

### 11.1 Hard Constraints

| ID | Constraint | Rationale |
|---|---|---|
| AC-1 | ROS 2 Humble (LTS) as the middleware | Industry standard for robotics; DDS-based; real-time capable |
| AC-2 | Python 3.10+ for all orchestration and agent logic | Rapid development; ecosystem compatibility; type annotations |
| AC-3 | Gazebo Harmonic as the primary simulator | Free, open-source, well-integrated with ROS 2 |
| AC-4 | Hardware abstraction via HAL — no direct simulator coupling in agent code | Enables simulator swaps and future hardware integration |
| AC-5 | Event-driven pub/sub via DDS (ROS 2 topics/services) | Standard robotics communication pattern; decoupled modules |
| AC-6 | All agent logic must be stateless with respect to other agents | Agents only communicate via ROS 2 interfaces, not shared memory |

### 11.2 Design Decisions

| ID | Decision | Alternatives Considered | Rationale |
|---|---|---|---|
| DD-1 | Market-based task auction (not central assignment) | Central planner, contract net, swarm consensus | Scalable, respects agent heterogeneity, proven in multi-robot systems |
| DD-2 | HTN planner (not STRIPS/PDDL for Sprint 0) | PDDL solver, behavior trees, pure FSM | HTN gives natural hierarchical decomposition; PDDL can be added later |
| DD-3 | FSM for agent behavior (not behavior trees) | Behavior trees, HFSM, Petri nets | Simplest correct approach for Sprint 0; behavior trees as a future upgrade |
| DD-4 | A* on occupancy grid (not RRT/PRM) | RRT, PRM, Dijkstra | Deterministic, optimal on grid, easy to implement and debug |
| DD-5 | Bayesian grid fusion (not particle filter/GP) | Gaussian processes, particle filters | Computationally simple, works well on fixed grids, good enough for Sprint 0 |
| DD-6 | React + rosbridge for dashboard (not native ROS viz) | RViz2 panels, Qt, Electron | Web-based = accessible from any machine; rosbridge is standard |

---

## 12. Dependencies & Assumptions

### 12.1 Software Dependencies

| Dependency | Version | Purpose | Installation |
|---|---|---|---|
| ROS 2 Humble | LTS | Middleware, build system, launch | `apt` (Ubuntu 22.04) or Docker |
| Gazebo Harmonic | Latest | Physics simulation, sensor plugins | ROS 2 package repos |
| Python | 3.10+ | Primary development language | System or pyenv |
| NumPy | ≥1.23 | Resource map computation | pip |
| SciPy | ≥1.9 | Bayesian updates, path planning utilities | pip |
| rosbridge_suite | ROS 2 compatible | WebSocket bridge for dashboard | ROS 2 package repos |
| Node.js | 18+ LTS | Dashboard build toolchain | nvm |
| React | 18+ | Dashboard frontend framework | npm |
| roslibjs | Latest | JavaScript ROS 2 client for dashboard | npm |
| colcon | Latest | ROS 2 build tool | pip |
| pytest | ≥7.0 | Python testing | pip |

### 12.2 Assumptions

| ID | Assumption | Impact if Wrong |
|---|---|---|
| A-1 | Development occurs on Ubuntu 22.04 (native or WSL2) | Different ROS 2 install procedures; Gazebo may not work natively on Windows |
| A-2 | Gazebo Harmonic plugins for custom sensors (neutron spec, ice deposits) can be implemented as Gazebo plugins or ROS 2 node wrappers | May need to simplify sensor simulation to pure ROS 2 nodes publishing synthetic data |
| A-3 | rosbridge_suite provides sufficient bandwidth and latency for dashboard updates at 1 Hz with 10 robots | May need to batch/compress messages or use a custom WebSocket server |
| A-4 | A single workstation (16 GB RAM, mid-range GPU) can run the full simulation stack | May need to split simulation and ROS nodes across machines, or reduce physics fidelity |
| A-5 | The lunar terrain can be adequately modeled with a static heightmap mesh | Dynamic terrain deformation (from excavation) is deferred beyond Sprint 0 |

---

## 13. Package Structure & Conventions

### 13.1 Repository Layout

```
selene/
├── CLAUDE.md                    # Project context for Claude Code
├── SELENE_Project_Plan_1.md     # Master project plan
├── docs/
│   └── PRD.md                   # This document
├── selene_msgs/                 # Custom ROS 2 message/service definitions
│   ├── CMakeLists.txt
│   ├── package.xml
│   ├── msg/
│   │   ├── RobotState.msg
│   │   ├── TaskAnnouncement.msg
│   │   ├── BidResponse.msg
│   │   ├── TaskAssignment.msg
│   │   ├── ResourceMapUpdate.msg
│   │   ├── FleetAlert.msg
│   │   └── MissionProgress.msg
│   └── srv/
│       ├── InjectTask.srv
│       └── OverrideRobot.srv
├── selene_orchestrator/         # Fleet orchestration engine
│   ├── package.xml
│   ├── setup.py
│   ├── setup.cfg
│   ├── selene_orchestrator/
│   │   ├── __init__.py
│   │   ├── orchestrator_node.py
│   │   ├── task_planner.py      # HTN decomposition
│   │   ├── task_auction.py      # Market-based allocation
│   │   ├── fleet_monitor.py     # Health aggregation & failure detection
│   │   ├── resource_map.py      # Probabilistic map manager
│   │   └── energy_scheduler.py  # Energy-aware task scheduling
│   ├── config/
│   │   └── orchestrator_params.yaml
│   └── test/
│       ├── test_task_planner.py
│       ├── test_task_auction.py
│       ├── test_resource_map.py
│       └── test_fleet_monitor.py
├── selene_agent/                # Per-robot autonomy stack
│   ├── package.xml
│   ├── setup.py
│   ├── setup.cfg
│   ├── selene_agent/
│   │   ├── __init__.py
│   │   ├── agent_node.py
│   │   ├── fsm.py               # Finite state machine
│   │   ├── navigator.py         # A* path planning + obstacle avoidance
│   │   ├── energy_manager.py    # Battery tracking + energy budgets
│   │   ├── perception.py        # Sensor fusion pipeline
│   │   └── skills/
│   │       ├── __init__.py
│   │       ├── base_skill.py    # Abstract skill interface
│   │       ├── prospect.py
│   │       ├── excavate.py
│   │       ├── haul.py
│   │       └── recharge.py
│   ├── config/
│   │   ├── scout.yaml           # RCDL for scout
│   │   ├── excavator.yaml       # RCDL for excavator
│   │   └── hauler.yaml          # RCDL for hauler
│   └── test/
│       ├── test_fsm.py
│       ├── test_navigator.py
│       └── test_energy_manager.py
├── selene_hal/                  # Hardware Abstraction Layer
│   ├── package.xml
│   ├── setup.py
│   ├── setup.cfg
│   └── selene_hal/
│       ├── __init__.py
│       ├── hal_interface.py     # Abstract HAL interfaces
│       ├── robot_descriptor.py  # RCDL parser
│       ├── gazebo_hal.py        # Gazebo-specific implementation
│       ├── sensor_interface.py
│       └── actuator_interface.py
├── selene_sim/                  # Simulation environment
│   ├── package.xml
│   ├── setup.py (or CMakeLists.txt for Gazebo plugins)
│   ├── worlds/
│   │   └── lunar_psr.sdf        # Main lunar terrain world
│   ├── models/
│   │   ├── scout/
│   │   │   ├── model.sdf
│   │   │   └── meshes/
│   │   ├── excavator/
│   │   │   ├── model.sdf
│   │   │   └── meshes/
│   │   └── hauler/
│   │       ├── model.sdf
│   │       └── meshes/
│   ├── plugins/                 # Custom Gazebo plugins
│   │   ├── ice_deposit_plugin/
│   │   ├── neutron_spec_plugin/
│   │   └── battery_plugin/
│   ├── config/
│   │   └── ice_deposits.yaml    # Ground truth deposit definitions
│   └── launch/
│       ├── simulation.launch.py  # Full sim launch
│       └── dashboard.launch.py   # Dashboard + rosbridge launch
├── selene_dashboard/            # Web-based mission control
│   ├── package.json
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.jsx
│   │   ├── components/
│   │   │   ├── FleetMap.jsx      # 2D fleet visualization
│   │   │   ├── ResourceHeatmap.jsx
│   │   │   ├── TaskQueue.jsx
│   │   │   ├── RobotDetail.jsx
│   │   │   ├── MissionProgress.jsx
│   │   │   ├── TaskInjector.jsx
│   │   │   └── AlertPanel.jsx
│   │   ├── hooks/
│   │   │   └── useRosBridge.js   # ROS 2 WebSocket connection hook
│   │   └── utils/
│   │       └── rosTopics.js      # Topic name constants
│   └── public/
│       └── index.html
├── selene_isru/                 # ISRU process models
│   ├── package.xml
│   ├── setup.py
│   ├── setup.cfg
│   └── selene_isru/
│       ├── __init__.py
│       ├── thermal_mining.py    # Extraction rate models
│       ├── logistics.py         # Material flow tracking
│       └── inventory.py         # Depot inventory management
└── docker/
    ├── Dockerfile               # Full dev environment
    └── docker-compose.yaml      # Multi-container setup
```

### 13.2 Naming Conventions

| Entity | Convention | Example |
|---|---|---|
| ROS 2 packages | `snake_case`, prefixed `selene_` | `selene_orchestrator` |
| Python modules | `snake_case` | `task_planner.py` |
| Python classes | `PascalCase` | `TaskAuction`, `EnergyManager` |
| Python functions | `snake_case` | `compute_bid_score()` |
| ROS 2 message types | `PascalCase` | `RobotState`, `TaskAssignment` |
| ROS 2 topics | `snake_case`, hierarchical | `/scout_01/state` |
| ROS 2 services | `snake_case` | `/orchestrator/inject_task` |
| Config parameters | `snake_case` | `auction_timeout_sec` |
| React components | `PascalCase` | `FleetMap.jsx`, `TaskQueue.jsx` |
| YAML configs | `snake_case` | `orchestrator_params.yaml` |

---

## 14. Phased Implementation Approach

### 14.1 Overview

Sprint 0 is divided into six phases. Each phase produces a self-contained, testable increment. Later phases depend on earlier ones — no phase may begin until the prior phase's exit gate is passed. This structure allows progress to be validated continuously rather than only at the end.

```
Phase 1          Phase 2          Phase 3          Phase 4          Phase 5          Phase 6
Scaffolding  ──► Single Agent ──► Multi-Agent  ──► Orchestration ──► Dashboard &  ──► Polish &
& Sim World      Autonomy         Coordination     Intelligence     Integration      Hardening

Wk 1          Wk 2-3           Wk 4-5          Wk 6-7           Wk 8-9           Wk 10
```

### 14.2 Requirement-to-Phase Mapping

Every functional requirement is assigned to a single phase. This table serves as the authoritative build order.

| Phase | Requirements Delivered | Packages Affected |
|---|---|---|
| 1 — Scaffolding & Sim World | FR-SIM-1, FR-SIM-2, FR-SIM-3, FR-SIM-4, FR-SIM-5, FR-SIM-6, FR-SIM-7 (partial) | `selene_msgs`, `selene_sim`, `selene_hal` (interfaces only) |
| 2 — Single Agent Autonomy | FR-AGT-1, FR-AGT-2, FR-AGT-3, FR-AGT-4, FR-AGT-5, FR-AGT-6 (Prospect + Recharge), FR-AGT-7 | `selene_agent`, `selene_hal` (Gazebo impl) |
| 3 — Multi-Agent Coordination | FR-ORC-1, FR-ORC-2, FR-ORC-4, FR-MAP-1, FR-MAP-2 | `selene_orchestrator` (core), `selene_agent` (bidding) |
| 4 — Orchestration Intelligence | FR-ORC-3, FR-ORC-5, FR-ORC-6, FR-MAP-3, FR-AGT-6 (Excavate + Haul), FR-ISRU-1, FR-ISRU-2 | `selene_orchestrator` (planner), `selene_agent` (skills), `selene_isru` |
| 5 — Dashboard & Integration | FR-DASH-1 through FR-DASH-7, FR-SIM-7 (full), FR-MAP-4 | `selene_dashboard`, `selene_sim` (launch) |
| 6 — Polish & Hardening | NFR-1 through NFR-5 validation, all integration demos | All packages (fixes only) |

### 14.3 Dependency Graph

```
                    ┌──────────────────────┐
                    │  Phase 1: Scaffolding │
                    │  & Sim World          │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Phase 2: Single      │
                    │  Agent Autonomy       │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Phase 3: Multi-Agent │
                    │  Coordination         │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Phase 4: Orchestration│
                    │  Intelligence          │
                    └─────┬────────┬────────┘
                          │        │
              ┌───────────▼─┐  ┌──▼────────────┐
              │  Phase 5:   │  │  Phase 6:      │
              │  Dashboard  │  │  Polish &      │
              │  & Integr.  ├─►│  Hardening     │
              └─────────────┘  └────────────────┘
```

Phase 5 (Dashboard) and Phase 4 (Orchestration Intelligence) can overlap: dashboard development against Phase 3's working multi-agent system can begin while Phase 4 orchestration intelligence features are finalized. Phase 6 requires both Phase 4 and Phase 5 to be complete.

---

### Phase 1: Scaffolding & Simulation World

**Duration:** Week 1
**Goal:** Empty robots moving in a physically accurate lunar sim. The entire build and launch pipeline works end-to-end.

#### 1a. Repository & Build Skeleton

| Item | Details |
|---|---|
| **Work** | Initialize all 7 ROS 2 packages (`selene_msgs`, `selene_orchestrator`, `selene_agent`, `selene_hal`, `selene_sim`, `selene_isru`, `selene_dashboard`) with `package.xml`, `setup.py`/`CMakeLists.txt`, and empty `__init__.py` stubs. Create Docker dev environment. Set up CI (GitHub Actions: lint + `colcon build` + `colcon test`). |
| **FRs** | None (infrastructure only) |
| **Deliverable** | `colcon build` succeeds on clean checkout. CI pipeline green. Docker container builds. |

#### 1b. Message Definitions

| Item | Details |
|---|---|
| **Work** | Implement all 7 message types (MSG-1 through MSG-7) and 2 service definitions (SRV-1, SRV-2) in `selene_msgs`. |
| **FRs** | Data Requirements §7 |
| **Deliverable** | Messages compile. A test node can publish and subscribe to each message type. |

#### 1c. Simulation Environment

| Item | Details |
|---|---|
| **Work** | Build the Gazebo Harmonic lunar world (FR-SIM-1). Implement 3 robot models — Scout (FR-SIM-2), Excavator (FR-SIM-3), Hauler (FR-SIM-4) — as URDF/SDF with diff-drive plugins. Implement basic physics and energy model (FR-SIM-5): terrain friction, slope energy cost, battery drain. Define ice deposit ground truth file and simulated sensor plugin/node (FR-SIM-6). Create a minimal launch file that starts Gazebo and spawns robots (FR-SIM-7 partial). |
| **FRs** | FR-SIM-1, FR-SIM-2, FR-SIM-3, FR-SIM-4, FR-SIM-5, FR-SIM-6 |
| **Deliverable** | Single `ros2 launch` brings up Gazebo with 3 robot types on lunar terrain. Robots respond to `cmd_vel`. Battery topics publish. Scout sensor readings change near ice deposits. |

#### 1d. HAL Interfaces

| Item | Details |
|---|---|
| **Work** | Define abstract HAL interfaces in `selene_hal` (`hal_interface.py`, `sensor_interface.py`, `actuator_interface.py`). Define the RCDL YAML schema. Write RCDL files for Scout, Excavator, and Hauler. Implementation stubs only — Gazebo HAL driver comes in Phase 2. |
| **FRs** | FR-AGT-7 (interface definition only) |
| **Deliverable** | RCDL files parse without error. HAL abstract classes importable. |

#### Phase 1 Exit Gate

| Check | Method |
|---|---|
| `colcon build` succeeds | CI green |
| All 3 robot types spawn in Gazebo | Visual confirmation + `ros2 topic list` shows expected topics |
| Robots move via `cmd_vel` | Manual `ros2 topic pub` drives each robot |
| Battery depletes during locomotion | Subscribe to battery topic, confirm depletion |
| Scout sensor detects ice proximity | Drive scout near deposit, confirm sensor topic value changes |
| All messages compile and can be published/subscribed | Test node round-trips each message type |
| Docker container runs full stack | `docker-compose up` succeeds |

---

### Phase 2: Single Agent Autonomy

**Duration:** Weeks 2-3
**Goal:** A single robot can autonomously execute a mission: navigate a sequence of waypoints, prospect, manage its own energy, and return to recharge — all without any fleet coordination layer.

#### 2a. Gazebo HAL Driver

| Item | Details |
|---|---|
| **Work** | Implement `gazebo_hal.py` that maps abstract HAL calls to Gazebo-specific ROS 2 topics. Implement `robot_descriptor.py` RCDL parser that loads YAML and exposes robot capabilities. |
| **FRs** | FR-AGT-7 (implementation) |
| **Deliverable** | Agent code can read sensors and command actuators exclusively through HAL, with zero Gazebo-specific topic names in agent code. |

#### 2b. FSM & Agent Node

| Item | Details |
|---|---|
| **Work** | Implement the FSM (FR-AGT-2) with all defined states and transitions. Implement the agent lifecycle node (FR-AGT-1) that runs the FSM loop, publishes `RobotState`, and dispatches to the navigator and skill executor. In this phase the agent accepts hardcoded waypoint lists (no orchestrator yet). |
| **FRs** | FR-AGT-1, FR-AGT-2 |
| **Deliverable** | Agent node starts, transitions through lifecycle states, publishes `RobotState` at 2 Hz. FSM transitions are logged. |
| **Tests** | `test_fsm.py`: verify all valid transitions fire, invalid transitions raise errors, watchdog timeout triggers ERROR state. |

#### 2c. Navigation Stack

| Item | Details |
|---|---|
| **Work** | Implement A* path planner on occupancy grid (FR-AGT-3). Implement local obstacle avoidance (FR-AGT-4) using depth camera data. Integrate both into `navigator.py` with path publication for RViz2. |
| **FRs** | FR-AGT-3, FR-AGT-4 |
| **Deliverable** | Robot navigates from point A to point B, avoiding obstacles. Path is visible in RViz2. |
| **Tests** | `test_navigator.py`: A* finds shortest path on test grids, avoids obstacles, handles no-path-exists. |

#### 2d. Energy Manager

| Item | Details |
|---|---|
| **Work** | Implement energy tracking, range estimation, critical-threshold return-to-base override, and bid energy feasibility check (FR-AGT-5). |
| **FRs** | FR-AGT-5 |
| **Deliverable** | Robot autonomously returns to recharge zone when energy drops below 15%. Robot refuses tasks exceeding energy budget (tested with manual task assignment). |
| **Tests** | `test_energy_manager.py`: threshold triggers, range estimation accuracy, bid rejection logic. |

#### 2e. Initial Skills (Prospect + Recharge)

| Item | Details |
|---|---|
| **Work** | Define the `BaseSkill` abstract class with `start()`, `update()`, `is_complete()`, `abort()`, `get_progress()`. Implement `Prospect` skill (navigate to waypoint, activate sensor, record reading) and `Recharge` skill (navigate to solar zone, wait until charged). |
| **FRs** | FR-AGT-6 (Prospect + Recharge only) |
| **Deliverable** | Scout executes a full prospect-return-recharge loop autonomously using a hardcoded waypoint list. |

#### Phase 2 Exit Gate

| Check | Method |
|---|---|
| Scout completes 5-waypoint prospect loop autonomously | Launch scout with hardcoded waypoints, observe completion |
| Scout avoids mid-path obstacle | Place rock on planned path, confirm avoidance |
| Scout returns to recharge at 15% battery | Observe battery topic and FSM transition |
| Agent code has zero Gazebo-specific imports | `grep -r "gz\|gazebo\|ign" selene_agent/` returns nothing |
| All unit tests pass | `colcon test --packages-select selene_agent` |
| RViz2 shows planned path and robot state | Visual confirmation |

**Demo checkpoint:** Screen-record a single scout autonomously prospecting 5 locations, avoiding an obstacle, returning to recharge, and resuming.

---

### Phase 3: Multi-Agent Coordination

**Duration:** Weeks 4-5
**Goal:** Multiple robots operate simultaneously. The orchestrator allocates tasks via auction, monitors fleet health, and detects failures. The resource map accumulates data from multiple scouts.

#### 3a. Orchestrator Node & Fleet Monitor

| Item | Details |
|---|---|
| **Work** | Implement the orchestrator lifecycle node (FR-ORC-1). Implement fleet state monitor (FR-ORC-4): subscribe to all `RobotState` topics, build fleet state table, detect heartbeat timeouts, publish `FleetAlert` and aggregated fleet state. |
| **FRs** | FR-ORC-1, FR-ORC-4 |
| **Deliverable** | Orchestrator starts, discovers all agents, aggregates state. Killing an agent triggers failure detection and alert within timeout window. |
| **Tests** | `test_fleet_monitor.py`: heartbeat timeout detection, fleet state table accuracy, alert publication. |

#### 3b. Task Auction Protocol

| Item | Details |
|---|---|
| **Work** | Implement the task auction (FR-ORC-2) — announcement, bidding, winner selection, timeout handling. Add bidding logic to the agent FSM (IDLE → BIDDING → ASSIGNED transitions). |
| **FRs** | FR-ORC-2 |
| **Deliverable** | Orchestrator announces a "prospect waypoint X" task. Multiple scouts bid. The nearest scout with sufficient energy wins. |
| **Tests** | `test_task_auction.py`: highest bid wins, no-bid timeout re-announces, capability filtering, energy filtering. |

#### 3c. Resource Map Core

| Item | Details |
|---|---|
| **Work** | Implement the probabilistic resource grid (FR-MAP-1) — NumPy-backed grid with mean, variance, observation count per cell. Implement Bayesian sensor fusion (FR-MAP-2) — update cells when scouts report prospecting results. Wire scout Prospect skill to publish `ResourceMapUpdate` messages. |
| **FRs** | FR-MAP-1, FR-MAP-2 |
| **Deliverable** | Two scouts prospect different areas. Resource map shows lower uncertainty where scouts have visited. Multiple observations at the same cell reduce variance. |
| **Tests** | `test_resource_map.py`: single-observation update correctness, multi-observation variance reduction, sensor noise handling, spatial decay within footprint. |

#### 3d. Multi-Agent Launch & Orchestrated Prospecting

| Item | Details |
|---|---|
| **Work** | Update launch files to start orchestrator + N agents. Wire the orchestrator to generate prospect tasks from a simple uniform grid (adaptive planning comes in Phase 4). Demonstrate 2 scouts prospecting the PSR concurrently, with orchestrator distributing waypoints via auction. |
| **FRs** | FR-SIM-7 (multi-agent launch) |
| **Deliverable** | `ros2 launch` brings up orchestrator + 2 scouts. Scouts receive tasks from auction, prospect different areas, and build a shared resource map. |

#### Phase 3 Exit Gate

| Check | Method |
|---|---|
| 2+ scouts prospect concurrently via auctioned tasks | Observe task assignments in logs + robot movement |
| Resource map accumulates data from both scouts | Inspect resource map topic: cells visited by either scout show reduced variance |
| Killing a scout triggers failure detection + alert | Kill agent node, observe FleetAlert within timeout |
| Task held by failed scout is not permanently lost | Verify task re-enters queue (re-announced or marked INTERRUPTED) |
| No auction starvation (tasks eventually assigned) | Run for 10 min, confirm no tasks stuck in PENDING indefinitely |
| All unit + integration tests pass | `colcon test` |

**Demo checkpoint:** Screen-record 2 scouts cooperatively prospecting the PSR via task auction, with resource map building over time. Kill one scout mid-mission and show the alert + task recovery.

---

### Phase 4: Orchestration Intelligence

**Duration:** Weeks 6-7
**Goal:** The system executes a full ISRU cycle: prospect → extract → haul. The planner decomposes high-level objectives, the survey adapts to findings, failures trigger reallocation, and material flow is tracked.

#### 4a. HTN Task Planner

| Item | Details |
|---|---|
| **Work** | Implement the HTN planner (FR-ORC-3) that decomposes `CollectIce(zone, quantity)` into the subtask chain: Survey → SelectSite → Excavate → Haul. Implement temporal ordering (extraction cannot begin before survey identifies a site). Wire planner output into the auction system. |
| **FRs** | FR-ORC-3 |
| **Deliverable** | Given "Collect 100 kg ice from Zone A," the planner produces a valid, temporally ordered task graph. Subtasks enter the auction at appropriate times. |
| **Tests** | `test_task_planner.py`: decomposition correctness, temporal ordering, precondition enforcement, robot-type constraints. |

#### 4b. Excavate & Haul Skills

| Item | Details |
|---|---|
| **Work** | Implement `Excavate` skill — activate drill at location, monitor hopper fill, stop when full or deposit exhausted. Implement `Haul` skill — navigate to excavator, load (proximity-based transfer), navigate to depot, unload. Add these to the skill registry so the FSM can dispatch them. |
| **FRs** | FR-AGT-6 (Excavate + Haul) |
| **Deliverable** | Excavator arrives at a deposit, fills its hopper. Hauler arrives at excavator, loads, transports to depot, dumps. |

#### 4c. ISRU Process Models

| Item | Details |
|---|---|
| **Work** | Implement thermal mining model (FR-ISRU-1) — extraction rate as function of power, concentration, and depth. Implement logistics model (FR-ISRU-2) — track material through extract → haul → deposit pipeline with conservation invariant. Implement inventory tracking at the depot. |
| **FRs** | FR-ISRU-1, FR-ISRU-2 |
| **Deliverable** | Extraction rate correlates with ice concentration. Material quantities are conserved (extracted = in-transit + deposited). Telemetry published. |

#### 4d. Adaptive Survey Planning

| Item | Details |
|---|---|
| **Work** | Replace Phase 3's uniform-grid waypoint generator with the adaptive survey planner (FR-MAP-3). Scout waypoints are now chosen by ranking candidates on uncertainty, neighbor signal, and distance. |
| **FRs** | FR-MAP-3 |
| **Deliverable** | Scouts visibly converge on ice deposit areas. Waypoint density near deposits is >2x higher than in empty areas. |

#### 4e. Dynamic Reallocation & Energy-Aware Scheduling

| Item | Details |
|---|---|
| **Work** | Implement full task reallocation logic (FR-ORC-5) — interrupted tasks re-enter auction with progress metadata, dependent tasks pause, cascading failure handled. Implement energy-aware scheduling (FR-ORC-6) — proactive recharge scheduling, energy-feasibility gating on bid acceptance. |
| **FRs** | FR-ORC-5, FR-ORC-6 |
| **Deliverable** | Killing the excavator mid-extraction causes its task to be re-auctioned (or queued). Scouts continue working independently. Robots proactively recharge before stranding. |

#### 4f. End-to-End ISRU Integration

| Item | Details |
|---|---|
| **Work** | Wire all Phase 4 components together. Run the full cycle: inject "Collect 100 kg ice" → scouts survey adaptively → site selected → excavator extracts → hauler delivers → repeat until target met. Validate material conservation. Validate reallocation on failure. |
| **FRs** | All Phase 4 FRs working together |
| **Deliverable** | US-1 (Full ISRU Cycle) and US-2 (Dynamic Reallocation) scenarios complete successfully in the terminal/RViz2 (no dashboard yet). |

#### Phase 4 Exit Gate

| Check | Method |
|---|---|
| "Collect 100 kg ice" mission completes autonomously | Inject objective, observe 100 kg deposited at depot |
| HTN produces correct subtask chain with temporal ordering | Log inspection: Survey completes before Excavate starts |
| Scouts converge on deposits (adaptive survey) | Waypoint density analysis: >2x near deposits vs. empty |
| Excavator failure triggers reallocation; mission still completes | Kill excavator at ~50%, restart, verify completion |
| Hauler failure: excavator pauses, hauler recovers, cycle resumes | Kill hauler mid-haul, verify material is not lost |
| No robot strands with zero energy | Run 30-min scenario, check no robot below 5% outside recharge zone |
| Material conservation invariant holds | `extracted == in_transit + deposited` at all times (log check) |
| All unit + integration tests pass | `colcon test` |

**Demo checkpoint:** Screen-record the complete ISRU cycle including a mid-mission robot failure and recovery. This is the core technical demo of Sprint 0.

---

### Phase 5: Dashboard & Integration

**Duration:** Weeks 8-9
**Goal:** Human-readable mission oversight. The operator can monitor, understand, and intervene in fleet operations through a web dashboard. The entire system launches with a single command.

**Note:** Phase 5 front-end scaffolding (React app setup, rosbridge connection, basic map rendering) can begin during Phase 4 once Phase 3's multi-agent system provides a stable data source for development.

#### 5a. Dashboard Foundation & Fleet Map

| Item | Details |
|---|---|
| **Work** | Set up React app with rosbridge WebSocket connection (`useRosBridge` hook). Implement the fleet map view (FR-DASH-1) — 2D top-down map with robot icons, state indicators, battery gauges, and planned paths. |
| **FRs** | FR-DASH-1 |
| **Deliverable** | Dashboard connects to ROS 2 via rosbridge and displays all robots with correct positions, types, states, and battery levels updating at 1 Hz. |

#### 5b. Resource Heatmap & Mission Progress

| Item | Details |
|---|---|
| **Work** | Implement the resource heatmap overlay (FR-DASH-2) — color-coded ice concentration with confidence-modulated opacity. Implement mission progress summary panel (FR-DASH-7) — objective, progress bar, key metrics. Implement RViz2 resource map visualization (FR-MAP-4). |
| **FRs** | FR-DASH-2, FR-DASH-7, FR-MAP-4 |
| **Deliverable** | Heatmap overlays fleet map, updates as scouts explore. Progress panel shows "67/100 kg collected" with metrics. |

#### 5c. Task Queue & Robot Detail

| Item | Details |
|---|---|
| **Work** | Implement task queue panel (FR-DASH-3) with status, assignment, and progress for each task. Implement robot detail panel (FR-DASH-4) with telemetry and state transition history. |
| **FRs** | FR-DASH-3, FR-DASH-4 |
| **Deliverable** | Clicking a task highlights its assigned robot. Clicking a robot shows detailed telemetry. |

#### 5d. Operator Interaction

| Item | Details |
|---|---|
| **Work** | Implement manual task injection (FR-DASH-5) — form with map-click target selection, task type, and parameters. Implement robot override (FR-DASH-6) — send-to-location, cancel task, force recharge. Implement alert panel displaying `FleetAlert` messages. |
| **FRs** | FR-DASH-5, FR-DASH-6 |
| **Deliverable** | Operator can inject tasks and override robots through the dashboard. Actions are reflected in the fleet state. |

#### 5e. Full System Launch

| Item | Details |
|---|---|
| **Work** | Create the unified launch file (FR-SIM-7 full) — single `ros2 launch` starts Gazebo, orchestrator, all agents, rosbridge, and dashboard server. Parameterize robot counts. Create the dashboard-only launch file. |
| **FRs** | FR-SIM-7 (complete) |
| **Deliverable** | `ros2 launch selene_sim simulation.launch.py` brings up the entire system. Dashboard accessible at `http://localhost:3000`. |

#### Phase 5 Exit Gate

| Check | Method |
|---|---|
| Dashboard shows all robots with correct real-time state | Visual inspection against `ros2 topic echo` |
| Resource heatmap matches RViz2 visualization | Side-by-side comparison |
| Task queue reflects orchestrator state within 1 second | Inject task via CLI, observe dashboard update |
| Operator-injected task enters auction and gets assigned | Inject via dashboard, observe robot execution |
| Robot override (send-to-location) works | Override via dashboard, observe robot navigation |
| Single launch command starts full system | `ros2 launch selene_sim simulation.launch.py` → everything runs |
| Dashboard renders at 1 Hz with 4 robots without lag | Performance profiling in browser dev tools |

**Demo checkpoint:** Screen-record dashboard walkthrough showing fleet map, heatmap, task queue, mission progress, task injection, and robot override during a live ISRU cycle.

---

### Phase 6: Polish & Hardening

**Duration:** Week 10
**Goal:** All acceptance criteria pass. The system is stable, performant, documented, and demo-ready.

#### 6a. Integration Demo Execution

| Item | Details |
|---|---|
| **Work** | Execute all 4 integration demos (§10) with pass/fail recording. Fix any failures. Run each demo at least twice to confirm reproducibility. |
| **Demos** | Demo 1: End-to-End ISRU Cycle, Demo 2: Robot Failure and Recovery, Demo 3: Adaptive Survey Convergence, Demo 4: Energy Management |
| **Deliverable** | All 4 demos pass. Results documented with logs and screen recordings. |

#### 6b. Performance Validation

| Item | Details |
|---|---|
| **Work** | Profile and validate all NFR-1 performance targets. Address bottlenecks: auction cycle time, agent control loop rate, Bayesian update latency, dashboard frame rate, overall simulation speed. |
| **NFRs** | NFR-1.1 through NFR-1.5 |
| **Deliverable** | Performance report with measured values vs. targets for each NFR-1 requirement. |

#### 6c. Reliability & Stability

| Item | Details |
|---|---|
| **Work** | Run 30-minute unattended simulation (NFR-2.1). Monitor for crashes, deadlocks, memory leaks. Test agent disconnection/reconnection (NFR-2.3). Fix any issues found. |
| **NFRs** | NFR-2.1 through NFR-2.3 |
| **Deliverable** | 30-minute run completes without incident. Memory profiling shows no leaks. |

#### 6d. Test Coverage & CI

| Item | Details |
|---|---|
| **Work** | Audit test coverage against NFR-5.1 (80% on core logic). Add missing unit tests. Add launch_testing integration tests (NFR-5.2). Implement deterministic simulation mode with fixed seeds (NFR-5.3). Ensure CI runs all tests. |
| **NFRs** | NFR-5.1 through NFR-5.3 |
| **Deliverable** | Coverage report meets 80% threshold on core modules. CI pipeline runs unit + integration tests. |

#### 6e. Documentation

| Item | Details |
|---|---|
| **Work** | Write README with: project overview, quick-start guide (Docker + native), architecture diagram, launch instructions, parameter reference. Ensure all ROS 2 topics and services are documented in a reference table. |
| **Deliverable** | A new developer can get the system running from README alone within 30 minutes. |

#### Phase 6 Exit Gate (Sprint 0 Completion)

| Check | Method |
|---|---|
| SC-1: End-to-end ISRU cycle with 3+ robots | Integration Demo 1 passes |
| SC-2: Dynamic reallocation on robot failure | Integration Demo 2 passes |
| SC-3: Adaptive scout convergence | Integration Demo 3 passes |
| SC-4: Dashboard real-time updates within 1 second | Integration Demo 1 observed via dashboard |
| SC-5: Auction selects best robot >80% of time | Log analysis across all demos |
| SC-6: 30-minute stable run | 30-min unattended run completes |
| All NFR-1 performance targets met | Performance report |
| 80% unit test coverage on core modules | Coverage report |
| CI pipeline green (lint + build + test) | GitHub Actions dashboard |
| README enables 30-minute cold start | Dry-run by someone unfamiliar with the project |

---

### 14.4 Phase Timeline Summary

```
Week  1  ║  2  ║  3  ║  4  ║  5  ║  6  ║  7  ║  8  ║  9  ║ 10
──────────╬─────╬─────╬─────╬─────╬─────╬─────╬─────╬─────╬─────
Phase 1   ║     ║     ║     ║     ║     ║     ║     ║     ║
██████████║     ║     ║     ║     ║     ║     ║     ║     ║
          ║     ║     ║     ║     ║     ║     ║     ║     ║
Phase 2   ║     ║     ║     ║     ║     ║     ║     ║     ║
          ║█████║█████║     ║     ║     ║     ║     ║     ║
          ║     ║     ║     ║     ║     ║     ║     ║     ║
Phase 3   ║     ║     ║     ║     ║     ║     ║     ║     ║
          ║     ║     ║█████║█████║     ║     ║     ║     ║
          ║     ║     ║     ║     ║     ║     ║     ║     ║
Phase 4   ║     ║     ║     ║     ║     ║     ║     ║     ║
          ║     ║     ║     ║     ║█████║█████║     ║     ║
          ║     ║     ║     ║     ║     ║     ║     ║     ║
Phase 5   ║     ║     ║     ║     ║     ║     ║     ║     ║
          ║     ║     ║     ║     ║     ║ ░░░ ║█████║█████║
          ║     ║     ║     ║     ║     ║     ║     ║     ║
Phase 6   ║     ║     ║     ║     ║     ║     ║     ║     ║
          ║     ║     ║     ║     ║     ║     ║     ║     ║█████

█ = primary work    ░ = early scaffolding (can overlap)
```

### 14.5 Critical Path

The longest dependency chain determines the minimum duration:

**Phase 1** (sim world) → **Phase 2** (single agent) → **Phase 3** (multi-agent + auction) → **Phase 4** (HTN + full ISRU cycle) → **Phase 6** (integration demos)

Phase 5 (Dashboard) is off the critical path — it can be developed in parallel against the Phase 3 data interfaces and integrated once Phase 4 completes. However, Phase 6 requires both Phase 4 and Phase 5, so dashboard delays directly impact the final exit gate.

### 14.6 Phase Overlap & Parallelism Opportunities

| Opportunity | Details | Risk |
|---|---|---|
| Dashboard scaffolding during Phase 4 | React app, rosbridge hook, and fleet map can be built against Phase 3's stable multi-agent topics | Low — interface contracts are frozen after Phase 3 |
| ISRU models during Phase 3 | `selene_isru` has no dependencies on orchestration; thermal mining + logistics models can be unit-tested independently | None — purely additive |
| RCDL files during Phase 1 | Defining robot descriptors overlaps with robot model creation | None — same person likely does both |

### 14.7 Go/No-Go Decision Points

At each phase exit gate, the project has a natural decision point:

| After Phase | Decision |
|---|---|
| Phase 1 | **Sim viability:** Does Gazebo Harmonic meet performance/fidelity needs, or should we pivot to a lighter sim (e.g., 2D pygame prototype first, Gazebo later)? |
| Phase 2 | **Autonomy viability:** Is the FSM + A* + energy manager approach sufficient, or do we need behavior trees / RRT / more sophisticated planners? |
| Phase 3 | **Auction viability:** Does the task auction produce sensible allocations, or do we need a different coordination paradigm (central planner, contract net)? |
| Phase 4 | **Scope check:** Is the full ISRU cycle working well enough to justify dashboard investment, or should we extend Phase 4 and reduce Phase 5 scope? |
| Phase 5 | **Demo readiness:** Is the system demo-ready, or does Phase 6 need more than 1 week? |

---

## 15. Risk Register (Prototype-Specific)

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| PR-1 | Gazebo custom plugins (ice deposits, neutron spec) are complex to implement | Delays Milestone 1 | Medium | Fallback: simulate sensors as pure ROS 2 nodes publishing synthetic data based on robot position vs. ground truth, bypassing Gazebo plugin API |
| PR-2 | Task auction produces degenerate allocations (oscillation, starvation) | Broken orchestration demo | Medium | Implement bid cooldown (robot cannot re-bid on same task within N seconds), task timeout escalation, and allocation logging for debugging |
| PR-3 | Gazebo + ROS 2 + 4 agents + dashboard exceeds workstation resources | Cannot run full demo | Low-Medium | Profile early (Milestone 1); reduce physics fidelity, lower update rates, or split across Docker containers on separate machines |
| PR-4 | rosbridge latency/bandwidth insufficient for dashboard | Dashboard feels laggy | Low | Batch fleet state updates into single messages, reduce update rate to 0.5 Hz, compress resource map data |
| PR-5 | A* path planning is too slow on large grids | Robots freeze while planning | Low | Use hierarchical A* (coarse grid for long paths, fine grid for local), cache paths, or switch to JPS (Jump Point Search) |
| PR-6 | FSM deadlocks (robot stuck in a state with no valid transition) | Robot stops working | Medium | Add watchdog timer per state — if exceeded, force transition to ERROR → recovery. Log all transitions for debugging. |
| PR-7 | ROS 2 Humble / Gazebo Harmonic version incompatibilities | Build failures, runtime crashes | Medium | Pin all dependency versions in Docker. Test on clean environment early (Week 1). |

---

## 16. Open Questions

| ID | Question | Impact | Decision Needed By |
|---|---|---|---|
| OQ-1 | Development environment: native Ubuntu, WSL2, or Docker-first? | Setup complexity, Gazebo GPU access, developer experience | Milestone 1 start |
| OQ-2 | Should the prototype support Isaac Sim as an alternative simulator from Sprint 0, or defer to Sprint 1? | Scope and timeline of HAL implementation | Milestone 1 start |
| OQ-3 | What scale of ice deposits (size, concentration range) produces the most interesting/demonstrable survey behavior? | Simulation tuning for demo quality | Milestone 1 (world design) |
| OQ-4 | Should the material transfer between Excavator and Hauler be proximity-based (auto-transfer when co-located) or require an explicit docking maneuver? | Complexity of Haul skill | Milestone 2 (skill design) |
| OQ-5 | Is RViz2 sufficient for developer visualization, or do we need a custom 3D viewer from Sprint 0? | Dashboard scope | Milestone 4 start |
| OQ-6 | License model: Apache 2.0, MIT, or GPL? | Community adoption, commercial viability | Before any public release |

---

## 17. Glossary

| Term | Definition |
|---|---|
| **CADRE** | Cooperative Autonomous Distributed Robotic Exploration — NASA's multi-rover demo mission |
| **CRDT** | Conflict-Free Replicated Data Type — data structure for eventual consistency in distributed systems |
| **DDS** | Data Distribution Service — pub/sub middleware standard used by ROS 2 |
| **FSM** | Finite State Machine — behavioral model with discrete states and transitions |
| **HAL** | Hardware Abstraction Layer — interface decoupling software from specific hardware |
| **HTN** | Hierarchical Task Network — planning formalism that decomposes tasks into subtasks |
| **ISRU** | In-Situ Resource Utilization — using local resources rather than transporting from Earth |
| **MRE** | Molten Regolith Electrolysis — process for extracting oxygen and metals from lunar soil |
| **PDDL** | Planning Domain Definition Language — formal language for automated planning problems |
| **PSR** | Permanently Shadowed Region — lunar crater areas that never receive sunlight |
| **RCDL** | Robot Capability Description Language — declarative schema for robot properties |
| **RViz2** | ROS 2 visualization tool for 3D data |
| **SRCP2** | Space Robotics Challenge Phase 2 — NASA competition for multi-robot lunar ISRU |
| **URDF/SDF** | Unified Robot Description Format / Simulation Description Format — robot model file formats |
| **VFH** | Vector Field Histogram — reactive obstacle avoidance algorithm |
| **wt%** | Weight percent — concentration measurement (mass of solute / mass of solution × 100) |

---

*End of document.*
