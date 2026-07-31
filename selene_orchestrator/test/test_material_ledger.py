"""The orchestrator half of the material chain — D-06 / FR-ISRU-2.

Drives ``material_event_logic`` directly, which is the writer
``MaterialInventory`` never had: before 2026-07-30 ``register_site`` /
``record_extraction`` / ``record_load`` / ``record_unload`` had zero production
callers anywhere in the repository, so every mass in MissionProgress was
structurally 0.0 and ``check_conservation()`` passed trivially as 0 == 0 + 0.

Every branch tested here is a way the ledger could be CORRUPTED, not merely
left empty — a duplicate credited twice, mass banked against a site nobody
declared, a load the site could not cover accepted in silence.
"""

import types

import pytest

from selene_isru.inventory import MaterialInventory
from selene_orchestrator.orchestrator_node import (
    HAUL_BLOCK_NO_MATERIAL,
    HAUL_BLOCK_NO_SITE,
    _MaterialEventContext,
    authorise_task_quantity,
    material_event_logic,
)
from selene_orchestrator.task_queue import TaskQueue


def _event(event_id='e1', robot_id='excavator_01', task_id='t1',
           event_type='extracted', mass_kg=5.0, residual_mass_kg=0.0):
    return types.SimpleNamespace(
        event_id=event_id, robot_id=robot_id, task_id=task_id,
        event_type=event_type, mass_kg=mass_kg,
        residual_mass_kg=residual_mass_kg)


@pytest.fixture
def ledger():
    """(ctx, queue, inventory, alerts) with one site and one sited task."""
    queue = TaskQueue()
    queue.add_task('t1', 'excavate', 0.0, 0.0, site_id='site_A')
    queue.add_task('t_siteless', 'excavate', 0.0, 0.0)
    inventory = MaterialInventory()
    inventory.register_site('site_A', (0.0, 0.0), estimated_kg=100.0)
    alerts = []
    ctx = _MaterialEventContext(
        task_queue=queue,
        inventory=inventory,
        publish_alert=lambda sev, rid, msg: alerts.append((sev, rid, msg)),
        residual_tolerance_kg=0.5,
        # The shipped default from orchestrator_params.yaml. The fixture used
        # to leave it at the dataclass default of 0.0 (the hard-coded 1e-6 the
        # node carried), which is finer than one float32 ulp at 19 kg and made
        # every healthy haul raise an FR-ISRU-2 alert.
        overdraw_tolerance_kg=0.001,
        dedupe_size=4096,
    )
    return ctx, queue, inventory, alerts


def _warnings(alerts):
    return [msg for sev, _rid, msg in alerts if sev == 'WARNING']


class TestHappyPath:

    def test_extraction_credits_the_site(self, ledger):
        ctx, _q, inv, alerts = ledger
        assert material_event_logic(ctx, _event(mass_kg=7.5)) is True
        assert inv.get_total_extracted() == pytest.approx(7.5)
        assert inv.get_total_at_site() == pytest.approx(7.5)
        assert ctx.events_applied == 1
        assert _warnings(alerts) == []

    def test_the_three_stages_move_mass_through_the_pipeline(self, ledger):
        ctx, _q, inv, alerts = ledger
        material_event_logic(ctx, _event('e1', 'excavator_01', 't1',
                                         'extracted', 19.0))
        material_event_logic(ctx, _event('e2', 'hauler_01', 't1',
                                         'loaded', 19.0))
        material_event_logic(ctx, _event('e3', 'hauler_01', 't1',
                                         'unloaded', 19.0))
        assert inv.get_total_extracted() == pytest.approx(19.0)
        assert inv.get_total_at_site() == pytest.approx(0.0)
        assert inv.get_total_in_transit() == pytest.approx(0.0)
        assert inv.get_total_deposited() == pytest.approx(19.0)
        assert inv.check_conservation()
        assert ctx.events_applied == 3
        assert _warnings(alerts) == []


class TestIdempotence:

    def test_a_duplicate_event_id_is_ignored_with_no_side_effect(self, ledger):
        """TRANSIENT_LOCAL replays each agent's history to a restarting
        orchestrator; without this, replay would DOUBLE the mission's mass."""
        ctx, _q, inv, alerts = ledger
        assert material_event_logic(ctx, _event('dup', mass_kg=10.0)) is True
        assert material_event_logic(ctx, _event('dup', mass_kg=10.0)) is False
        assert inv.get_total_extracted() == pytest.approx(10.0)
        assert ctx.events_applied == 1
        # Silently, too: a replay is expected, not an anomaly.
        assert alerts == []

    def test_the_dedupe_window_is_bounded(self, ledger):
        """5000 events against a 4096 window: memory stays bounded and the
        oldest ids are evicted rather than retained forever."""
        ctx, _q, _inv, _alerts = ledger
        for i in range(5000):
            material_event_logic(
                ctx, _event(f'evt_{i:05d}', mass_kg=0.001))
        assert ctx.events_applied == 5000
        assert len(ctx.seen_ids) <= 4096
        assert len(ctx.seen_order) <= 4096
        # The bookkeeping cannot drift apart.
        assert len(ctx.seen_ids) == len(ctx.seen_order)
        # An evicted id is accepted again -- LOST HISTORY, never double mass,
        # which is the direction this degrades in by design.
        assert 'evt_00000' not in ctx.seen_ids


class TestDrops:

    def test_event_for_an_unknown_task_is_dropped_with_a_warning(self, ledger):
        ctx, _q, inv, alerts = ledger
        assert material_event_logic(ctx, _event(task_id='nope')) is False
        assert inv.get_total_extracted() == 0.0
        assert ctx.events_applied == 0
        assert any('unknown to the queue' in m for m in _warnings(alerts))

    def test_event_whose_task_has_no_site_is_dropped_with_a_warning(self, ledger):
        """NEVER register a site on the fly: an invented site accepts mass into
        a bucket nothing else knows about and conservation holds trivially
        again -- the exact failure this whole change removes."""
        ctx, _q, inv, alerts = ledger
        assert material_event_logic(
            ctx, _event(task_id='t_siteless')) is False
        assert inv.get_total_extracted() == 0.0
        assert any('extraction site' in m for m in _warnings(alerts))

    def test_unknown_event_type_is_dropped(self, ledger):
        ctx, _q, inv, alerts = ledger
        assert material_event_logic(ctx, _event(event_type='teleported')) is False
        assert inv.get_total_extracted() == 0.0
        assert any('event_type' in m for m in _warnings(alerts))

    def test_a_mass_that_is_not_a_mass_is_dropped_not_clamped(self, ledger):
        """Clamping would turn a broken sensor into a plausible number."""
        ctx, _q, inv, alerts = ledger
        for bad in (-1.0, float('nan'), float('inf')):
            assert material_event_logic(
                ctx, _event(event_id=f'bad{bad}', mass_kg=bad)) is False
        assert inv.get_total_extracted() == 0.0
        assert len(_warnings(alerts)) == 3

    def test_a_site_missing_from_the_ledger_is_reported_not_created(self, ledger):
        ctx, queue, inv, alerts = ledger
        queue.add_task('t_ghost', 'excavate', 0.0, 0.0, site_id='site_ghost')
        assert material_event_logic(ctx, _event(task_id='t_ghost')) is False
        assert inv.get_total_extracted() == 0.0
        assert any('not registered' in m for m in _warnings(alerts))


class TestCrossInstrumentChecks:

    def test_a_load_beyond_the_site_balance_is_clamped_alerted_and_banked(
            self, ledger):
        """The real FR-ISRU-2 check: the excavator's hopper sensor and the
        hauler's load cell disagree about the same material."""
        ctx, _q, inv, alerts = ledger
        material_event_logic(ctx, _event('e1', 'excavator_01', 't1',
                                         'extracted', 10.0))
        material_event_logic(ctx, _event('e2', 'hauler_01', 't1',
                                         'loaded', 25.0))

        assert inv.get_total_in_transit() == pytest.approx(10.0)
        assert inv.get_unaccounted_kg() == pytest.approx(15.0)
        assert any('overdraw' in m and '25.00' in m and '10.00' in m
                   for m in _warnings(alerts)), alerts

    def test_a_float32_sized_overdraw_raises_nothing(self, ledger):
        """The alert that used to fire on every successful haul.

        On 2026-07-31 a hauler reported 1.0109e-4 kg more than the excavator
        had left at the site -- 53 float32 ulps at 19 kg, i.e. two instruments
        agreeing as closely as the wire format allows. The check compared
        against a hard-coded 1e-6 kg, which is below one ulp of the quantity it
        was comparing, so it raised a WARNING whose own text read "reported
        19.01 kg but only 19.01 kg had been extracted there; 0.00 kg is
        unaccounted".
        """
        ctx, _q, inv, alerts = ledger
        material_event_logic(ctx, _event('e1', 'excavator_01', 't1',
                                         'extracted', 19.01289939880371))
        material_event_logic(ctx, _event('e2', 'hauler_01', 't1',
                                         'loaded', 19.01300048828125))

        assert not [m for m in _warnings(alerts) if 'overdraw' in m], alerts
        assert inv.get_unaccounted_kg() == 0.0
        assert inv.check_conservation()
        assert inv.get_total_in_transit() == pytest.approx(
            19.01300048828125, abs=1e-12)

    def test_a_residual_beyond_tolerance_raises_a_warning(self, ledger):
        """A hauler reporting 19 kg delivered while its load cell still reads
        7 kg is a fault only residual_mass_kg can show."""
        ctx, _q, _inv, alerts = ledger
        material_event_logic(ctx, _event('e1', 'excavator_01', 't1',
                                         'extracted', 19.0))
        material_event_logic(ctx, _event('e2', 'hauler_01', 't1',
                                         'loaded', 19.0))
        material_event_logic(ctx, _event('e3', 'hauler_01', 't1', 'unloaded',
                                         19.0, residual_mass_kg=7.0))
        assert any('still reads 7.00 kg' in m for m in _warnings(alerts)), alerts

    def test_a_residual_inside_tolerance_is_silent(self, ledger):
        ctx, _q, _inv, alerts = ledger
        material_event_logic(ctx, _event('e1', 'excavator_01', 't1',
                                         'extracted', 19.0,
                                         residual_mass_kg=0.2))
        assert _warnings(alerts) == []


class TestConservationLatch:

    def test_exactly_one_alert_per_breach(self, ledger):
        """A persistent discrepancy must not flood AlertLog.jsx."""
        ctx, _q, inv, alerts = ledger
        material_event_logic(ctx, _event('e1', 'excavator_01', 't1',
                                         'extracted', 5.0))
        # Overdraw -> unaccounted 10 kg -> conservation false from here on.
        material_event_logic(ctx, _event('e2', 'hauler_01', 't1',
                                         'loaded', 15.0))
        assert inv.check_conservation() is False
        breaches = [m for m in _warnings(alerts) if 'conservation breach' in m]
        assert len(breaches) == 1

        # Five more healthy events; the breach persists but is not re-alerted.
        for i in range(5):
            material_event_logic(ctx, _event(f'x{i}', 'excavator_01', 't1',
                                             'extracted', 1.0))
        breaches = [m for m in _warnings(alerts) if 'conservation breach' in m]
        assert len(breaches) == 1

    def test_the_latch_rearms_once_conservation_is_restored(self, ledger):
        ctx, _q, inv, _alerts = ledger
        material_event_logic(ctx, _event('e1', 'excavator_01', 't1',
                                         'extracted', 5.0))
        material_event_logic(ctx, _event('e2', 'hauler_01', 't1',
                                         'loaded', 15.0))
        assert ctx.conservation_ok is False
        # There is no un-accounting operation, so restore it directly: the
        # point under test is the latch, not the arithmetic.
        inv._unaccounted_kg = 0.0
        material_event_logic(ctx, _event('e3', 'excavator_01', 't1',
                                         'extracted', 1.0))
        assert ctx.conservation_ok is True


def _task(task_type='haul', site_id='site_A', quantity_kg=0.0,
          task_id='h1'):
    return types.SimpleNamespace(task_id=task_id, task_type=task_type,
                                 site_id=site_id, quantity_kg=quantity_kg)


class TestHaulAuthorisation:
    """``authorise_task_quantity``: zero is not "authorise nothing" — D-06.

    ``TaskAssignment.quantity_kg`` 0.0 is documented as *unconstrained -- fill
    to the robot's own RCDL capacity*, and the agent implements exactly that:
    ``HaulSkill._clamp_quantity`` maps any non-positive request to 0.0, and
    ``_update_loading`` then calls ``trigger_load(max_kg=-1.0)``, which reaches
    the sim as a bare "load" and fills the bin to ``capacity_kg`` (50 kg,
    ``selene_hal/config/hauler.yaml:29``). So returning 0.0 to mean "nothing is
    authorised" -- which this did -- authorised 50 kg of material no excavator
    ever extracted, and the ledger then raised a conservation breach blaming
    the instruments for the orchestrator's own fabrication.
    """

    def test_a_haul_at_a_stocked_site_is_authorised_for_what_is_there(self):
        inv = MaterialInventory()
        inv.register_site('site_A', (0.0, 0.0), estimated_kg=100.0)
        inv.record_extraction('site_A', 'excavator_01', 18.0)

        assert authorise_task_quantity(
            _task(), inv.get_site_available) == (18.0, '')

    def test_a_haul_at_an_empty_site_is_blocked_not_zeroed(self):
        inv = MaterialInventory()
        inv.register_site('site_A', (0.0, 0.0), estimated_kg=100.0)

        quantity, blocked = authorise_task_quantity(
            _task(), inv.get_site_available)
        assert blocked == HAUL_BLOCK_NO_MATERIAL
        assert quantity == 0.0

    def test_a_haul_at_a_drained_site_is_blocked(self):
        """Everything extracted has already been loaded onto some hauler."""
        inv = MaterialInventory()
        inv.register_site('site_A', (0.0, 0.0), estimated_kg=100.0)
        inv.record_extraction('site_A', 'excavator_01', 10.0)
        inv.record_load('hauler_02', 'site_A', 10.0)

        assert authorise_task_quantity(_task(), inv.get_site_available)[1] == \
            HAUL_BLOCK_NO_MATERIAL

    def test_a_haul_with_no_site_is_blocked(self):
        inv = MaterialInventory()
        assert authorise_task_quantity(
            _task(site_id=''), inv.get_site_available)[1] == HAUL_BLOCK_NO_SITE

    def test_a_haul_naming_an_unregistered_site_is_blocked(self):
        """A KeyError from the ledger is a block, never an unconstrained fill."""
        inv = MaterialInventory()
        assert authorise_task_quantity(
            _task(site_id='site_ghost'),
            inv.get_site_available)[1] == HAUL_BLOCK_NO_SITE

    def test_an_operator_named_mass_is_honoured_and_never_blocks(self):
        """FR-DASH-5: the operator asked for that number.

        Not a fabrication by the orchestrator, and not silent either --
        ``record_load`` clamps the accepted mass to what the site holds and
        banks the difference as unaccounted kg with a named WARNING.
        """
        inv = MaterialInventory()
        inv.register_site('site_A', (0.0, 0.0), estimated_kg=100.0)

        assert authorise_task_quantity(
            _task(quantity_kg=7.5), inv.get_site_available) == (7.5, '')

    def test_an_excavate_at_zero_stays_unconstrained(self):
        """Only a haul is gated: 0.0 on an excavate means "fill the hopper"."""
        inv = MaterialInventory()
        assert authorise_task_quantity(
            _task(task_type='excavate', site_id=''),
            inv.get_site_available) == (0.0, '')

    def test_a_prospect_and_a_missing_task_are_unconstrained(self):
        inv = MaterialInventory()
        assert authorise_task_quantity(
            _task(task_type='prospect'), inv.get_site_available) == (0.0, '')
        assert authorise_task_quantity(None, inv.get_site_available) == (0.0, '')
