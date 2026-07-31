"""Tests for ISRU inventory tracking and resource accounting."""

import pytest

from selene_isru.inventory import (
    ExtractionRateModel,
    MaterialInventory,
)


# --- ExtractionRateModel Tests ---


def test_extraction_rate_model():
    """Rate increases with power and concentration."""
    model = ExtractionRateModel(efficiency=0.3, energy_per_kg=20.0)

    rate_low = model.compute_rate(power_fraction=0.5, concentration_wt_pct=2.0)
    rate_high = model.compute_rate(power_fraction=1.0, concentration_wt_pct=5.0)

    assert rate_low > 0.0
    assert rate_high > rate_low


def test_extraction_rate_depth_penalty():
    """Deeper extraction is slower."""
    model = ExtractionRateModel()

    rate_surface = model.compute_rate(
        power_fraction=1.0, concentration_wt_pct=5.0, depth_m=0.0
    )
    rate_deep = model.compute_rate(
        power_fraction=1.0, concentration_wt_pct=5.0, depth_m=2.0
    )

    assert rate_deep < rate_surface
    assert rate_deep > 0.0  # depth penalty floors at 0.1


def test_extraction_rate_very_deep():
    """Depth penalty floors at 0.1 even at extreme depths."""
    model = ExtractionRateModel()

    rate = model.compute_rate(
        power_fraction=1.0, concentration_wt_pct=5.0, depth_m=100.0
    )
    assert rate > 0.0


def test_extraction_rate_zero_power():
    """Zero power yields zero rate."""
    model = ExtractionRateModel()
    rate = model.compute_rate(
        power_fraction=0.0, concentration_wt_pct=5.0
    )
    assert rate == 0.0


# --- MaterialInventory Tests ---


def test_record_extraction():
    """Site extracted_kg increases on record_extraction."""
    inv = MaterialInventory()
    inv.register_site("site_a", (10.0, 20.0), estimated_kg=100.0)
    inv.record_extraction("site_a", "robot_1", 5.0)

    assert inv.get_total_extracted() == 5.0
    assert inv.get_site_remaining("site_a") == 95.0


def test_conservation_invariant():
    """Extract -> load -> unload: extracted == deposited."""
    inv = MaterialInventory()
    inv.register_site("site_a", (10.0, 20.0), estimated_kg=100.0)

    inv.record_extraction("site_a", "robot_1", 10.0)
    inv.record_load("robot_1", "site_a", 10.0)

    # Material in transit, conservation holds
    assert inv.check_conservation()
    assert inv.get_total_in_transit() == 10.0

    inv.record_unload("robot_1", 10.0)

    # Material deposited, conservation still holds
    assert inv.check_conservation()
    assert inv.get_total_deposited() == 10.0
    assert inv.get_total_in_transit() == 0.0


def test_multiple_sites():
    """Independent tracking across multiple sites."""
    inv = MaterialInventory()
    inv.register_site("alpha", (0.0, 0.0), estimated_kg=50.0)
    inv.register_site("beta", (100.0, 0.0), estimated_kg=200.0)

    inv.record_extraction("alpha", "robot_1", 5.0)
    inv.record_extraction("beta", "robot_2", 20.0)

    assert inv.get_site_remaining("alpha") == 45.0
    assert inv.get_site_remaining("beta") == 180.0
    assert inv.get_total_extracted() == 25.0


def test_multiple_robots():
    """Different cargo amounts across robots."""
    inv = MaterialInventory()
    inv.register_site("site_a", (0.0, 0.0), estimated_kg=100.0)

    inv.record_extraction("site_a", "robot_1", 15.0)
    inv.record_load("robot_1", "site_a", 10.0)
    inv.record_load("robot_2", "site_a", 5.0)

    assert inv.get_robot_cargo("robot_1") == 10.0
    assert inv.get_robot_cargo("robot_2") == 5.0
    assert inv.get_total_in_transit() == 15.0


def test_unload_clamps_to_cargo():
    """Cannot unload more than current cargo."""
    inv = MaterialInventory()
    inv.register_site("site_a", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("site_a", "robot_1", 5.0)
    inv.record_load("robot_1", "site_a", 5.0)

    actual = inv.record_unload("robot_1", 999.0)
    assert actual == 5.0
    assert inv.get_robot_cargo("robot_1") == 0.0


def test_unknown_site_raises():
    """Accessing unknown site raises KeyError."""
    inv = MaterialInventory()
    with pytest.raises(KeyError):
        inv.record_extraction("nonexistent", "robot_1", 1.0)
    with pytest.raises(KeyError):
        inv.get_site_remaining("nonexistent")


def test_unknown_robot_returns_zero():
    """Unknown robot has zero cargo."""
    inv = MaterialInventory()
    assert inv.get_robot_cargo("ghost") == 0.0


def test_mission_progress():
    """get_mission_progress returns correct summary dict."""
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "r1", 20.0)
    inv.record_load("r1", "s1", 15.0)
    inv.record_unload("r1", 5.0)

    progress = inv.get_mission_progress()
    assert progress["extracted"] == 20.0
    assert progress["in_transit"] == 10.0
    assert progress["deposited"] == 5.0


# --- D-06: at_site, the overdraw check, and what conservation now means ---


def test_material_sits_at_the_site_until_it_is_loaded():
    """The term the shipped check_conservation() omitted entirely.

    ``record_extraction``'s own docstring says material stays at the site until
    ``record_load``, but the invariant asserted ``extracted == in_transit +
    deposited`` -- false the moment an excavator ran ahead of a hauler, which
    is the normal state of the pipeline.
    """
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 19.0)

    assert inv.get_total_at_site() == 19.0
    assert inv.get_site_available("s1") == 19.0
    assert inv.get_total_in_transit() == 0.0
    assert inv.check_conservation(), inv.get_mission_progress()

    inv.record_load("hauler_01", "s1", 19.0)
    assert inv.get_total_at_site() == 0.0
    assert inv.get_site_available("s1") == 0.0
    assert inv.get_total_in_transit() == 19.0
    assert inv.check_conservation()


def test_record_load_raises_on_an_unknown_site():
    """Matching record_extraction. Crediting a load to a site nobody declared
    opens a bucket the identity knows nothing about, and it then holds
    trivially again -- the precise failure this class shipped with."""
    inv = MaterialInventory()
    with pytest.raises(KeyError):
        inv.record_load("hauler_01", "nonexistent", 5.0)
    with pytest.raises(KeyError):
        inv.get_site_available("nonexistent")


def test_record_load_clamps_to_the_site_balance_and_returns_it():
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)

    accepted = inv.record_load("hauler_01", "s1", 25.0)
    assert accepted == 10.0
    assert inv.get_robot_cargo("hauler_01") == 10.0
    assert inv.get_total_at_site() == 0.0


def test_an_overdraw_is_banked_as_unaccounted_not_created():
    """The real cross-instrument check: the excavator's hopper sensor and the
    hauler's load cell disagree about the same material. FR-ISRU-2's
    acceptance is exactly a statement that this stays zero."""
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)
    inv.record_load("hauler_01", "s1", 25.0)

    assert inv.get_unaccounted_kg() == 15.0
    assert inv.check_conservation() is False
    assert inv.get_mission_progress()["unaccounted"] == 15.0


def test_conservation_identity_still_closes_under_an_overdraw():
    """Only the unaccounted clause fails. The identity closes structurally --
    which is precisely why it is not the interesting half."""
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)
    inv.record_load("hauler_01", "s1", 25.0)

    p = inv.get_mission_progress()
    assert p["extracted"] == pytest.approx(
        p["at_site"] + p["in_transit"] + p["deposited"])


def test_conservation_tolerates_a_sub_tolerance_overdraw():
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)
    inv.record_load("hauler_01", "s1", 10.005)
    assert inv.get_unaccounted_kg() == pytest.approx(0.005)
    assert inv.check_conservation() is True


def test_at_site_totals_across_several_sites():
    inv = MaterialInventory()
    inv.register_site("alpha", (0.0, 0.0), estimated_kg=50.0)
    inv.register_site("beta", (100.0, 0.0), estimated_kg=200.0)
    inv.record_extraction("alpha", "excavator_01", 12.0)
    inv.record_extraction("beta", "excavator_02", 8.0)
    inv.record_load("hauler_01", "alpha", 5.0)

    assert inv.get_site_available("alpha") == 7.0
    assert inv.get_site_available("beta") == 8.0
    assert inv.get_total_at_site() == 15.0
    assert inv.check_conservation()


def test_a_negative_load_is_ignored_rather_than_crediting_backwards():
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)
    assert inv.record_load("hauler_01", "s1", -5.0) == 0.0
    assert inv.get_robot_cargo("hauler_01") == 0.0
    assert inv.get_unaccounted_kg() == 0.0


# ------------------------------------------------------- the overdraw tolerance

def test_a_float32_sized_overdraw_is_credited_not_banked():
    """THE 2026-07-31 NUMBER, reproduced.

    That run's hauler reported loading 1.0109e-4 kg more than the excavator
    said it had extracted -- 53 float32 ulps at 19 kg, which is what two
    instruments agreeing perfectly look like after both readings have crossed
    the wire as float32 and been multiplied by a capacity. With no tolerance the
    ledger banked all of it, so ``unaccounted_kg`` was non-zero on a haul in
    which nothing went wrong, and the WARNING it raised printed
    "0.00 kg is unaccounted" -- an alert firing below its own precision.
    """
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 19.01289939880371)

    accepted = inv.record_load("hauler_01", "s1", 19.01300048828125,
                               tolerance_kg=0.001)

    assert accepted == pytest.approx(19.01300048828125, abs=1e-12)
    assert inv.get_unaccounted_kg() == 0.0
    assert inv.check_conservation()


def test_the_identity_still_closes_when_an_overdraw_is_credited():
    """Crediting the robot without crediting the site would break the identity.

    ``extracted == at_site + in_transit + deposited`` is the one thing
    MaterialInventory must never break, so the tolerated excess is added to the
    site's extracted total as well as to the robot's cargo.
    """
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)
    inv.record_load("hauler_01", "s1", 10.0005, tolerance_kg=0.001)

    progress = inv.get_mission_progress()
    assert progress["extracted"] == pytest.approx(10.0005, abs=1e-12)
    assert progress["at_site"] == pytest.approx(0.0, abs=1e-12)
    assert progress["in_transit"] == pytest.approx(10.0005, abs=1e-12)
    assert progress["unaccounted"] == 0.0
    assert inv.check_conservation()


def test_an_overdraw_above_the_tolerance_is_still_banked_in_full():
    """The tolerance forgives instrument noise, not material.

    Only the part above the tolerance used to be a candidate for forgiveness;
    it is not forgiven at all. A 15 kg overdraw is banked whole -- not
    15 kg minus a gram -- because the discrepancy IS 15 kg.
    """
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)

    accepted = inv.record_load("hauler_01", "s1", 25.0, tolerance_kg=0.001)

    assert accepted == 10.0
    assert inv.get_unaccounted_kg() == 15.0
    assert not inv.check_conservation()


def test_the_default_tolerance_is_the_strict_old_behaviour():
    """A caller who has not thought about resolution gets the strict version."""
    inv = MaterialInventory()
    inv.register_site("s1", (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction("s1", "excavator_01", 10.0)
    assert inv.record_load("hauler_01", "s1", 10.0005) == 10.0
    assert inv.get_unaccounted_kg() == pytest.approx(0.0005)
