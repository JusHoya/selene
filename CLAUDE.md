# SELENE — Spacecraft & Extraterrestrial Logistics for Extraction, Navigation & Exploitation

## Project Overview
SELENE is an AI-driven lunar ISRU (In-Situ Resource Utilization) fleet management software suite. It commands, coordinates, and optimizes a heterogeneous fleet of autonomous lunar surface robots across the full ISRU value chain: prospecting, extraction, processing, and transportation.

## Architecture
- **Layered, modular, hardware-agnostic** design
- **Mission Control Layer** (Earth-side): Digital twin, mission planning, supervisory control
- **Fleet Orchestration Layer** (Lunar-side): Task decomposition, scheduling, resource allocation
- **Agent Autonomy Layer** (Per-robot): Perception, navigation, task execution, HAL
- **ISRU Process Control Layer**: Prospecting, extraction, processing, logistics

## Tech Stack
| Component | Technology |
|---|---|
| Robot middleware | ROS 2 (Humble+) |
| Simulation | Gazebo Harmonic / NVIDIA Isaac Sim |
| 3D Scene | OpenUSD |
| Task planning | PDDL + HTN planner |
| ML framework | PyTorch (training) / ONNX Runtime (inference) |
| Communication | DDS (Cyclone/FastDDS) |
| Dashboard | Three.js / Web-based |
| Languages | Python (orchestration), C++ (real-time), Rust (safety-critical) |
| Dashboard frontend | React (JSX) |

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
- Tests: `pytest` for Python, `gtest` for C++
- Dashboard: React with JSX

## Key Design Principles
1. **Delay-tolerant**: 1.3s Earth-Moon light delay, potential multi-minute comm blackouts
2. **Resource-constrained**: Space-rated processors are orders of magnitude less powerful
3. **Graceful degradation**: No single point of failure
4. **Extensible**: New robot types, ISRU processes, celestial bodies without re-architecting
5. **Hardware-agnostic**: Standard interfaces via HAL and RCDL

## Current Phase
Sprint 0 Prototype — simulation-based demonstration of core fleet orchestration.
