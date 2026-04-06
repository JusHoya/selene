"""ISRU inventory tracking and resource accounting module.

Tracks material flow through the extraction pipeline:
  site extraction -> robot cargo -> depot deposit

Maintains the conservation invariant:
  total_extracted == total_in_transit + total_deposited
"""

from dataclasses import dataclass


@dataclass
class SiteInventory:
    """Inventory state for a single extraction site."""
    site_id: str
    position: tuple[float, float]
    estimated_total_kg: float
    extracted_kg: float = 0.0


@dataclass
class RobotCargo:
    """Current cargo state for a single robot."""
    robot_id: str
    cargo_kg: float = 0.0
    source_site: str = ""


class ExtractionRateModel:
    """Compute extraction rate based on power, concentration, and depth.

    rate_kg_s = efficiency * power_fraction * (concentration_wt_pct / 10.0)
                / energy_per_kg
    Depth penalty: rate *= max(0.1, 1.0 - depth_m * 0.3)
    """

    def __init__(self, efficiency: float = 0.3, energy_per_kg: float = 20.0):
        self._efficiency = efficiency
        self._energy_per_kg = energy_per_kg

    def compute_rate(self, power_fraction: float,
                     concentration_wt_pct: float,
                     depth_m: float = 0.0) -> float:
        """Return extraction rate in kg/s.

        Args:
            power_fraction: Available power fraction 0.0-1.0.
            concentration_wt_pct: Ice concentration in weight percent.
            depth_m: Current excavation depth in metres.

        Returns:
            Extraction rate in kg/s (always >= 0).
        """
        rate = (self._efficiency * power_fraction
                * (concentration_wt_pct / 10.0)
                / self._energy_per_kg)
        depth_penalty = max(0.1, 1.0 - depth_m * 0.3)
        return max(0.0, rate * depth_penalty)


class MaterialInventory:
    """Central ledger for all material in the ISRU pipeline.

    Tracks three stages: extracted from sites, in-transit on robots,
    and deposited at the depot.
    """

    def __init__(self):
        self._sites: dict[str, SiteInventory] = {}
        self._robot_cargo: dict[str, RobotCargo] = {}
        self._depot_total_kg: float = 0.0

    def register_site(self, site_id: str, position: tuple[float, float],
                      estimated_kg: float) -> None:
        """Register a new extraction site with its estimated reserves."""
        self._sites[site_id] = SiteInventory(
            site_id=site_id,
            position=position,
            estimated_total_kg=estimated_kg,
        )

    def record_extraction(self, site_id: str, robot_id: str,
                          kg: float) -> None:
        """Record material extracted from a site (not yet loaded onto robot).

        This increments the site's extracted_kg counter. The material is
        considered to be at the site awaiting pickup until record_load is
        called.
        """
        if site_id not in self._sites:
            raise KeyError(f"Unknown site: {site_id}")
        self._sites[site_id].extracted_kg += kg

    def record_load(self, robot_id: str, from_site: str,
                    kg: float) -> None:
        """Record material loaded onto a robot from a site."""
        if robot_id not in self._robot_cargo:
            self._robot_cargo[robot_id] = RobotCargo(robot_id=robot_id)
        self._robot_cargo[robot_id].cargo_kg += kg
        self._robot_cargo[robot_id].source_site = from_site

    def record_unload(self, robot_id: str, kg: float) -> float:
        """Record material unloaded from a robot at the depot.

        Returns:
            The amount actually unloaded (clamped to current cargo).
        """
        if robot_id not in self._robot_cargo:
            return 0.0
        cargo = self._robot_cargo[robot_id]
        actual = min(kg, cargo.cargo_kg)
        cargo.cargo_kg -= actual
        self._depot_total_kg += actual
        return actual

    def get_total_extracted(self) -> float:
        """Total kg extracted from all sites."""
        return sum(s.extracted_kg for s in self._sites.values())

    def get_total_in_transit(self) -> float:
        """Total kg currently on robots."""
        return sum(c.cargo_kg for c in self._robot_cargo.values())

    def get_total_deposited(self) -> float:
        """Total kg delivered to the depot."""
        return self._depot_total_kg

    def get_site_remaining(self, site_id: str) -> float:
        """Estimated kg remaining at a site."""
        if site_id not in self._sites:
            raise KeyError(f"Unknown site: {site_id}")
        site = self._sites[site_id]
        return max(0.0, site.estimated_total_kg - site.extracted_kg)

    def get_robot_cargo(self, robot_id: str) -> float:
        """Current cargo mass on a robot."""
        if robot_id not in self._robot_cargo:
            return 0.0
        return self._robot_cargo[robot_id].cargo_kg

    def check_conservation(self, tolerance: float = 0.01) -> bool:
        """Verify extracted == in_transit + deposited within tolerance.

        Returns True if the conservation invariant holds.
        """
        extracted = self.get_total_extracted()
        accounted = self.get_total_in_transit() + self.get_total_deposited()
        return abs(extracted - accounted) <= tolerance

    def get_mission_progress(self) -> dict:
        """Return dict with keys: extracted, in_transit, deposited."""
        return {
            "extracted": self.get_total_extracted(),
            "in_transit": self.get_total_in_transit(),
            "deposited": self.get_total_deposited(),
        }
