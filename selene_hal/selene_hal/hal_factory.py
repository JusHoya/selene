"""Factory for creating HAL instances from RCDL files."""

from __future__ import annotations
from pathlib import Path
from selene_hal.hal_interface import HalInterface
from selene_hal.robot_descriptor import RobotDescriptor

_HAL_BACKENDS: dict[str, type[HalInterface]] = {}


def register_hal_backend(name: str, cls: type[HalInterface]) -> None:
    """Register a HAL backend implementation."""
    _HAL_BACKENDS[name] = cls


def create_hal(
    rcdl_path: str | Path,
    robot_id: str,
    backend: str = "stub",
    ros_node=None,
) -> HalInterface:
    """Create a HAL instance from an RCDL file.

    Args:
        rcdl_path: Path to the RCDL YAML file.
        robot_id: Unique robot instance ID.
        backend: HAL backend name ("stub", "gazebo").
        ros_node: ROS 2 node handle (for ROS-based backends).
    """
    descriptor = RobotDescriptor.from_yaml(rcdl_path)

    # Lazy-load built-in backends on first use
    if not _HAL_BACKENDS:
        import selene_hal.stub_hal  # noqa: F401

    if backend not in _HAL_BACKENDS:
        available = list(_HAL_BACKENDS.keys())
        raise KeyError(
            f"Unknown HAL backend '{backend}'. Available: {available}")

    hal_cls = _HAL_BACKENDS[backend]
    return hal_cls(descriptor=descriptor, robot_id=robot_id, ros_node=ros_node)
