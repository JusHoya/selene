"""ISRU inventory tracking and resource accounting module.

Tracks material flow through the extraction pipeline:
  site extraction -> material lying at the site -> robot cargo -> depot

Maintains the conservation identity:
  total_extracted == at_site + in_transit + deposited

plus a cross-instrument check (``get_unaccounted_kg``) that has no
structural guarantee behind it and is therefore the clause that can
actually fail. See ``MaterialInventory.check_conservation``.
"""

from dataclasses import dataclass


@dataclass
class SiteInventory:
    """Inventory state for a single extraction site.

    ``extracted_kg`` is everything an excavator ever reported pulling out of
    this site; ``loaded_kg`` is the part of it a hauler has since reported
    picking up. The difference is material still lying at the site, which is
    the term the shipped conservation check was missing.
    """
    site_id: str
    position: tuple[float, float]
    estimated_total_kg: float
    extracted_kg: float = 0.0
    loaded_kg: float = 0.0


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

    Tracks four stages: extracted from a site, still lying at that site,
    in transit on a robot, and deposited at the depot.

    Every kilogram in here is a MEASURED difference of two
    ``FillLevelReading.mass_kg`` values, reported by an agent on
    ``/orchestrator/material_event``. Nothing is estimated: a skill that
    cannot read its fill sensor publishes no event, so the ledger under-reports
    rather than inventing a number. Until 2026-07-30 this class had no
    production writers at all (register entry D-06) and every total below
    was permanently 0.0.
    """

    def __init__(self):
        self._sites: dict[str, SiteInventory] = {}
        self._robot_cargo: dict[str, RobotCargo] = {}
        self._depot_total_kg: float = 0.0
        # Mass a hauler claimed to load beyond what any excavator claimed to
        # extract from that site. See check_conservation() for why this, and
        # not the identity, is the clause with information in it.
        self._unaccounted_kg: float = 0.0

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
                    kg: float, tolerance_kg: float = 0.0) -> float:
        """Record material loaded onto a robot from a site.

        The accepted mass is clamped to what the site actually has waiting
        (``extracted_kg - loaded_kg``). Anything above that is a disagreement
        between two instruments -- the excavator's hopper sensor and the
        hauler's load cell -- so it is banked in ``_unaccounted_kg`` instead of
        being silently created. FR-ISRU-2's acceptance ("no material is lost or
        duplicated") is exactly a statement about that number staying zero.

        ``tolerance_kg`` IS WHAT KEEPS THAT NUMBER MEANINGFUL. Every mass here
        has been through float32 on the wire (``FillLevel.level``,
        ``MaterialEvent.mass_kg``) and back through a multiply by
        ``capacity_kg``, so the two instruments cannot agree to the bit even
        when they agree perfectly. On 2026-07-31 they differed by 1.0109e-4 kg
        on a 19 kg load -- 53 float32 ulps -- and with no tolerance the ledger
        banked all of it, so ``unaccounted_kg`` was non-zero on a haul in which
        nothing whatever went wrong. A check that fires on a correct run is a
        check nobody reads. An overdraw at or below the tolerance is credited to
        the load (it is real material, measured by the load cell, and the
        conservation identity must keep balancing); only the excess is banked.

        The default is 0.0, i.e. the previous behaviour, so a caller that has
        not thought about instrument resolution gets the strict version rather
        than a silently loosened one. ``orchestrator_node`` passes
        ``material_overdraw_tolerance_kg`` from its config.

        Raises:
            KeyError: if *from_site* was never registered. Matching
                record_extraction, because crediting a load to a site nobody
                declared would open a bucket the conservation identity knows
                nothing about, and the identity would then hold trivially again
                -- the precise failure mode this class shipped with.

        Returns:
            The mass actually accepted onto the robot, in kg.
        """
        if from_site not in self._sites:
            raise KeyError(f"Unknown site: {from_site}")
        site = self._sites[from_site]
        available = max(0.0, site.extracted_kg - site.loaded_kg)
        requested = max(0.0, kg)
        tolerance = max(0.0, float(tolerance_kg))
        overdraw = max(0.0, requested - available)
        if overdraw <= tolerance:
            # Within instrument resolution: take the load cell's word for it.
            # The site's own counter is raised to match so that
            # `extracted == at_site + in_transit + deposited` still closes --
            # crediting the robot without crediting the site would break the
            # identity, which is the one thing this class must never do.
            accepted = requested
            if overdraw > 0.0:
                site.extracted_kg += overdraw
        else:
            accepted = available
            self._unaccounted_kg += (requested - available)

        if robot_id not in self._robot_cargo:
            self._robot_cargo[robot_id] = RobotCargo(robot_id=robot_id)
        site.loaded_kg += accepted
        self._robot_cargo[robot_id].cargo_kg += accepted
        self._robot_cargo[robot_id].source_site = from_site
        return accepted

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

    def get_total_at_site(self) -> float:
        """Total kg extracted but not yet loaded onto any robot."""
        return sum(max(0.0, s.extracted_kg - s.loaded_kg)
                   for s in self._sites.values())

    def get_site_available(self, site_id: str) -> float:
        """Kg waiting at a site for pickup (extracted minus loaded)."""
        if site_id not in self._sites:
            raise KeyError(f"Unknown site: {site_id}")
        site = self._sites[site_id]
        return max(0.0, site.extracted_kg - site.loaded_kg)

    def get_unaccounted_kg(self) -> float:
        """Kg haulers reported loading that no excavator reported extracting.

        Zero is the only healthy value.
        """
        return self._unaccounted_kg

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
        """Verify the ledger is self-consistent. Two clauses, one useful.

        Clause 1, the identity::

            extracted == at_site + in_transit + deposited

        BE CLEAR ABOUT WHAT THIS PROVES: almost nothing. It closes
        *structurally*. record_extraction adds to extracted and therefore to
        at_site; record_load moves the same clamped number out of at_site and
        into in_transit; record_unload moves it from in_transit to deposited.
        No path can break it, so it can only ever fail on float drift. It is
        checked because it is cheap and because a future editor who adds a
        fifth stage without a matching term should hear about it.

        The version this class shipped with omitted ``at_site`` and asserted
        ``extracted == in_transit + deposited``. That contradicts
        record_extraction's own docstring -- material sits at the site until
        loaded -- so it was false the moment an excavator ran ahead of a
        hauler, which is the normal state of the pipeline. It only ever passed
        because nothing called the writers and it evaluated 0 == 0 + 0.

        Clause 2, the real one::

            unaccounted_kg <= tolerance

        ``unaccounted_kg`` accumulates every kilogram a hauler's load cell
        claimed to pick up beyond what an excavator's hopper sensor claimed to
        leave at that site. Nothing constrains those two instruments to agree,
        so this clause has information in it: a non-zero value means two
        physical sensors on two different robots disagree about the same
        material, which is what FR-ISRU-2 says cannot happen.

        Returns True when both clauses hold.
        """
        extracted = self.get_total_extracted()
        accounted = (self.get_total_at_site()
                     + self.get_total_in_transit()
                     + self.get_total_deposited())
        identity_ok = abs(extracted - accounted) <= tolerance
        return identity_ok and self._unaccounted_kg <= tolerance

    def get_mission_progress(self) -> dict:
        """Summary dict: extracted, at_site, in_transit, deposited, unaccounted.

        All values in kg. ``extracted`` is the sum of the middle three by
        construction (see check_conservation).
        """
        return {
            "extracted": self.get_total_extracted(),
            "at_site": self.get_total_at_site(),
            "in_transit": self.get_total_in_transit(),
            "deposited": self.get_total_deposited(),
            "unaccounted": self.get_unaccounted_kg(),
        }
