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
