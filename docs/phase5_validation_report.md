# SELENE Phase 5 Exit Gate Validation Report

_Generated Thu Jul 30 10:18:10 AM CDT 2026_

| | |
|---|---|
| Source commit | `251e84d` |
| Workspace | `/root/selene` |
| ROS 2 | jazzy |
| Gazebo (gz sim) | 8.11.0 |
| OS | Ubuntu 24.04.3 LTS |

| # | Check | Result | Details |
|---|---|---|---|
| 1 | Single launch command starts full system | PASS | ros2 launch process running |
| 3 | rosbridge listening on ws://localhost:9090 | PASS | TCP 9090 open |
| 4 | Dashboard shows all robots with correct real-time state | PASS | 4 robot state topics |
| 5 | Operator-injected task accepted via service | PASS | inject_task returned success |
| 6 | Task announced within 15s of injection | PASS | task_announcement emitted post-inject |
| 7 | Robot override (force_recharge) accepted | PASS | override_robot returned success |
| 8 | scout_01 fsm_state == RECHARGING after override | PASS | fsm_state: RECHARGING |
| 2 | Dashboard HTTP 200 on port 3000 | PASS | curl returned 200 |

**Summary:** 8 passed, 0 failed

**Deviations:** see `docs/phase5_deviation_register.md` (D-01..D-10), which records
what this gate does and does not cover. Note in particular that FR-MAP-4 (RViz2
resource-map visualization) is NOT delivered and is NOT waived — the previous
version of this line claimed it was skipped "per plan decision D9", and no such
decision exists anywhere in the repository or its history.

**What 8/8 here means:** the system launches, rosbridge and a web server answer,
two services accept calls, and one override propagates to a robot's state machine.
Of the PRD's seven exit-gate rows (docs/PRD.md:1499-1509) this script covers one
end to end, three with weak liveness proxies, and three not at all.

**Launch log:** /tmp/selene_unified_launch.log
