# SELENE — Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation

## Project Overview
SELENE is an AI-driven lunar ISRU (In-Situ Resource Utilization) fleet management software suite. It commands, coordinates, and optimizes a heterogeneous fleet of autonomous lunar surface robots across the full ISRU value chain: prospecting, extraction, processing, and transportation.

## Architecture
- **Layered, modular, hardware-agnostic** design
- **Mission Control Layer** (Earth-side): Mission planning, supervisory control, fleet visualization
  (currently a 2D canvas fleet map — a 3D digital twin is an architectural goal, not built)
- **Fleet Orchestration Layer** (Lunar-side): Task decomposition, scheduling, resource allocation
- **Agent Autonomy Layer** (Per-robot): Perception, navigation, task execution, HAL
- **ISRU Process Control Layer**: Prospecting, extraction, processing, logistics

## Tech Stack

### Implemented (present in the repository today)
| Component | Technology |
|---|---|
| Robot middleware | ROS 2 — CI builds in `ros:humble-ros-base-jammy` (`.github/workflows/ci.yaml`); the WSL2 dev/validation path targets Jazzy (`scripts/setup_wsl2.sh`, `scripts/validate_phase5.sh`). Keep both in mind when adding dependencies. |
| Simulation | Gazebo Harmonic (`gz-harmonic`, installed in `docker/Dockerfile` and `scripts/setup_wsl2.sh`) |
| Task planning | HTN planner (`selene_orchestrator/selene_orchestrator/htn_planner.py`) |
| Communication | DDS — Fast DDS, the default RMW; no Cyclone configuration is checked in |
| Dashboard frontend | React 18 + JSX, roslib over rosbridge WebSocket; 2D HTML canvas rendering |
| Languages | Python only |
| Schema validation | Pydantic v2 (RCDL robot descriptors) |
| Tests | pytest (Python) |

### Planned / not yet implemented
Nothing in this list has any code in the repository. Do not describe these as current capabilities.

| Component | Technology | Status |
|---|---|---|
| Simulation (high-fidelity) | NVIDIA Isaac Sim | No imports, no assets, no config |
| 3D scene description | OpenUSD | No `.usd`/`.usda` files, no `pxr` imports |
| Classical planning | PDDL | No `.pddl` files, no parser, no solver. `docs/PRD.md:959` (DD-2) explicitly chose an HTN planner *instead of* STRIPS/PDDL for Sprint 0 |
| ML framework | PyTorch (training) / ONNX Runtime (inference) | No `torch`/`onnx`/`onnxruntime` imports anywhere |
| 3D dashboard view | Three.js | `three@^0.160.0` is declared in `selene_dashboard/package.json` but is imported by no source file |
| Real-time components | C++ | No `.cpp`/`.hpp` files. `selene_msgs/CMakeLists.txt` exists only to run `rosidl` message generation |
| Safety-critical components | Rust | No `.rs` files, no `Cargo.toml` |
| C++ tests | gtest | No C++ code to test |

## Package Structure
```
selene/
├── selene_msgs/          # Custom ROS 2 message/service definitions
├── selene_orchestrator/  # Fleet orchestration engine
├── selene_agent/         # Per-robot autonomy stack
├── selene_hal/           # Hardware Abstraction Layer
├── selene_sim/           # Simulation environment
├── selene_dashboard/     # Web-based mission control
├── selene_isru/          # ISRU process models
```

## Development Conventions
- Python packages use `snake_case`
- ROS 2 message types use `PascalCase`
- All ROS 2 nodes should be composable (lifecycle nodes preferred)
- Use `colcon` for building ROS 2 workspace
- Tests: `pytest` for Python (`gtest` applies only if/when C++ code is added — there is none today)
- Dashboard: React with JSX

## Key Design Principles
1. **Delay-tolerant**: 1.3s Earth-Moon light delay, potential multi-minute comm blackouts
2. **Resource-constrained**: Space-rated processors are orders of magnitude less powerful
3. **Graceful degradation**: No single point of failure
4. **Extensible**: New robot types, ISRU processes, celestial bodies without re-architecting
5. **Hardware-agnostic**: Standard interfaces via HAL and RCDL

## Current Phase
Sprint 0. Phase definitions are in `docs/PRD.md:1169` (summary table) and `docs/PRD.md:1212`–`1559`
(per-phase detail). Honest status:

| Phase | PRD scope | Status |
|---|---|---|
| 1 — Scaffolding & Sim World | FR-SIM-1..6, FR-SIM-7 (partial) | Implemented |
| 2 — Single Agent Autonomy | FR-AGT-1..7 | Implemented |
| 3 — Multi-Agent Coordination | FR-ORC-1/2/4, FR-MAP-1/2 | Implemented |
| 4 — Orchestration Intelligence | FR-ORC-3/5/6, FR-MAP-3, excavate+haul skills, FR-ISRU-1/2 | Implemented |
| 5 — Dashboard & Integration | FR-DASH-1..7, FR-SIM-7 (full), FR-MAP-4 | Code implemented; **exit gate not passed** |
| 6 — Polish & Hardening | NFR-1..5 validation, integration demos | Not started |

Caveats a reader should know:
- The Phase 5 exit gate is an executable script, `scripts/validate_phase5.sh`, which requires WSL2 with
  ROS 2 Jazzy + a built colcon workspace. No `phase5_validation_report.md` is committed to this repository,
  so there is no recorded evidence in-tree that the gate has passed end to end.
- FR-MAP-4 (RViz2 resource-map visualization) is not implemented. The "Known deviation" note in
  `scripts/validate_phase5.sh` records it as intentionally descoped "per plan decision D9", but **no document
  defining decision D9 exists in this repository** — the descope is currently undocumented apart from that
  one line. `selene_sim/rviz/selene_sim.rviz` contains only Grid and TF displays.
- Some components are implemented and unit-tested but not wired into the running system. Known cases:
  `OrchestratorNode.__init__` constructs an `AdaptiveSurveyPlanner` and no method on it is ever called
  (`self._adaptive_survey` appears exactly once in the file); `MaterialInventory.register_site` /
  `record_extraction` / `record_load` / `record_unload` have no production callers, so the ledger stays at zero
  in a live run even though `_publish_mission_progress` reads it for the `MissionProgress` message.
- There is no resource-map publisher of any kind. The orchestrator has exactly four `create_publisher` calls
  (`task_announcement`, `task_assignment`, `alerts`, `mission_progress`). The `resource_map_publish_rate`
  parameter is declared but never read. The dashboard heatmap is built client-side from raw per-reading
  `ResourceMapUpdate` messages published by agents, not from the orchestrator's fused posterior grid.
