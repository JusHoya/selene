"""Container fill arithmetic for the simulated hopper and transport bin.

PURE PYTHON, NO ROS IMPORTS. stdlib plus PyYAML only.

WHY THIS MODULE EXISTS
The mass arithmetic for both containers used to live inside ``rclpy.Node``
subclasses, which made it unreachable from any test on a machine without ROS --
and it was wrong in a way no reader could see. ``hopper_node`` published
KILOGRAMS on a topic the HAL documents as a 0.0-1.0 fraction
(``selene_hal/selene_hal/data_types.py`` ``FillLevelReading.level``), so an
excavator with a 20 kg hopper crossed ``ExcavateSkill.FILL_THRESHOLD`` (0.95)
at 0.95 kg -- 4.75% full -- and reported that as a finished load. Extracting
the arithmetic is what makes the fraction/kilogram contract verifiable at all;
see ``selene_sim/test/test_fill_model.py``.

WHERE THE NUMBERS COME FROM
Capacities and transfer rates are read out of the RCDL that already declares
them -- ``selene_hal/config/excavator.yaml`` (hopper_fill ``capacity_kg: 20``,
hopper ``transfer_rate: 5``) and ``hauler.yaml`` (load_cell ``capacity_kg: 50``,
transport_bin ``transfer_rate: 10``). That is the same file the agent's HAL
reads, so there is exactly one capacity number per container in the system and
the sim cannot drift from the HAL.

The readers below deliberately use ``yaml.safe_load`` and DO NOT import
``selene_hal`` or pydantic. The shared source of truth is the RCDL *file*, not
the parser: importing the HAL would pull pydantic into the simulation runtime
and make these nodes untestable without a built colcon workspace, for no gain
-- ``simulation.launch.py`` already hands over the exact path.

``parse_transfer_command`` lives here for the same reason: the ``load:<kg>``
payload is what stops a bin loading material nobody extracted, and a parser
reachable only from inside an ``rclpy`` callback is a parser no test on this
machine can reach.
"""

from __future__ import annotations

import math
from typing import NamedTuple, Optional

import yaml

# Concentration, in wt%, at which a container fills at its full nominal rate.
# Moved here verbatim from hopper_node's `rate = BASE_EXTRACTION_RATE *
# (concentration / 10.0)`; it is the simulation's own normalisation constant
# and appears in no RCDL, so this module is its single home. It is unrelated to
# selene_orchestrator's MAX_CONCENTRATION_WT, which is a colour-ramp ceiling.
PEAK_CONCENTRATION_WT = 10.0


class FillModel:
    """Mass held in one container, and the only place a fraction is derived.

    ``mass_kg`` is the state; ``fraction`` is ``mass_kg / capacity_kg`` clamped
    to 0.0-1.0 and is what the node publishes. Nothing outside this class
    multiplies or divides by a capacity.
    """

    def __init__(self, capacity_kg: float, fill_rate_kg_s: float = 0.0,
                 transfer_rate_kg_s: float = 0.0):
        capacity_kg = float(capacity_kg)
        if not math.isfinite(capacity_kg) or capacity_kg <= 0.0:
            raise ValueError(
                f'capacity_kg must be finite and > 0, got {capacity_kg!r}. '
                f'A zero or missing capacity makes every published fraction '
                f'either a division by zero or a constant 0.0, which reads '
                f'downstream as "the container is empty" rather than as a '
                f'configuration error.'
            )
        self._capacity_kg = capacity_kg
        self._fill_rate_kg_s = max(0.0, float(fill_rate_kg_s))
        self._transfer_rate_kg_s = max(0.0, float(transfer_rate_kg_s))
        self._mass_kg = 0.0

    @property
    def capacity_kg(self) -> float:
        return self._capacity_kg

    @property
    def mass_kg(self) -> float:
        return self._mass_kg

    @property
    def fraction(self) -> float:
        """Fill as a dimensionless 0.0-1.0 -- the published quantity."""
        return max(0.0, min(1.0, self._mass_kg / self._capacity_kg))

    @property
    def is_full(self) -> bool:
        return self._mass_kg >= self._capacity_kg

    @property
    def is_empty(self) -> bool:
        return self._mass_kg <= 0.0

    def set_mass(self, kg: float) -> None:
        """Set the held mass directly, clamped to 0..capacity."""
        self._mass_kg = max(0.0, min(self._capacity_kg, float(kg)))

    def fill(self, dt: float, concentration_wt_pct: float) -> float:
        """Extract for ``dt`` seconds at ground of the given concentration.

        Rate is ``fill_rate_kg_s * concentration / PEAK_CONCENTRATION_WT``, so
        barren ground adds nothing and the nominal rate is reached at 10 wt%.
        Returns the kilograms actually added, which is less than the rate
        implies once the container is near full.
        """
        if dt <= 0.0 or self._fill_rate_kg_s <= 0.0:
            return 0.0
        concentration = max(0.0, float(concentration_wt_pct))
        rate = self._fill_rate_kg_s * (concentration / PEAK_CONCENTRATION_WT)
        return self._add(rate * float(dt))

    def load_toward(self, dt: float, target_kg: float) -> float:
        """Transfer material in for ``dt`` seconds, stopping at ``target_kg``.

        ``target_kg`` is ABSOLUTE (fill *to* this mass) and is itself clamped to
        the capacity. This is the authorised-payload path: the orchestrator's
        ledger says how much a site actually holds, so a bin can no longer load
        material no excavator extracted. Returns the kilograms added.
        """
        if dt <= 0.0 or self._transfer_rate_kg_s <= 0.0:
            return 0.0
        target = max(0.0, min(self._capacity_kg, float(target_kg)))
        headroom = target - self._mass_kg
        if headroom <= 0.0:
            return 0.0
        return self._add(min(self._transfer_rate_kg_s * float(dt), headroom))

    def drain(self, dt: float) -> float:
        """Transfer material out for ``dt`` seconds. Returns kilograms removed."""
        if dt <= 0.0 or self._transfer_rate_kg_s <= 0.0:
            return 0.0
        removed = min(self._mass_kg, self._transfer_rate_kg_s * float(dt))
        self._mass_kg -= removed
        return removed

    def _add(self, kg: float) -> float:
        added = min(max(0.0, kg), self._capacity_kg - self._mass_kg)
        self._mass_kg += added
        return added


class TransferCommand(NamedTuple):
    """Parsed ``std_msgs/String`` payload from a transfer actuator topic.

    ``mode``       ``'loading'`` | ``'unloading'`` | ``'idle'`` | ``None``.
                   ``'idle'`` means STOP -- clear the current transfer.
                   ``None`` means the payload was rejected, and a node must
                   leave whatever it was doing ALONE rather than stopping it.
    ``target_kg``  absolute mass to fill to; only meaningful for ``'loading'``.
    ``error``      human-readable reason, set exactly when ``mode`` is None.
    """
    mode: Optional[str]
    target_kg: float
    error: Optional[str]


def parse_transfer_command(payload: str, capacity_kg: float) -> TransferCommand:
    """Parse ``load`` | ``load:<kg>`` | ``unload`` | ``stop``.

    ``<kg>`` is ABSOLUTE -- fill *to* that mass, not by it -- and is capped at
    ``capacity_kg``. The bare ``load`` spelling is preserved so an unpatched
    publisher still works, and means "fill to capacity", which is what it has
    always meant.

    A MALFORMED NUMBER IS REJECTED RATHER THAN TREATED AS A BARE LOAD. That is
    the whole point of the bound: falling back to capacity on a bad payload
    would re-create the fabricated 50 kg this design removes, and a fabricated
    payload is invisible -- it looks exactly like a successful haul. A
    rejection instead surfaces as a warning and a haul that fails at its load
    timeout.

    This lives here, rather than inside the node callback that uses it, so it
    can be tested without rclpy. It is the mechanism the material ledger's
    conservation identity rests on; a parser reachable only from a running
    Gazebo is a parser nobody checks.
    """
    command = (payload or '').lower().strip()

    if command == 'load':
        return TransferCommand('loading', max(0.0, float(capacity_kg)), None)

    if command.startswith('load:'):
        raw = command.split(':', 1)[1]
        try:
            requested = float(raw)
        except ValueError:
            return TransferCommand(
                None, 0.0,
                f'the value after ":" ({raw!r}) is not a number. Not falling '
                f'back to a full container: that would move material no '
                f'excavator extracted.')
        if not (requested >= 0.0):       # the negated form also rejects NaN
            return TransferCommand(
                None, 0.0,
                f'the authorised mass ({requested!r}) must be >= 0.')
        return TransferCommand(
            'loading', min(max(0.0, float(capacity_kg)), requested), None)

    if command == 'unload':
        return TransferCommand('unloading', 0.0, None)

    if command == 'stop':
        return TransferCommand('idle', 0.0, None)

    return TransferCommand(None, 0.0, 'unknown command')


def _load_rcdl(rcdl_path: str) -> dict:
    if not rcdl_path:
        raise ValueError(
            'rcdl_path is empty. This node needs the RCDL that declares its '
            'container capacity and transfer rate; simulation.launch.py passes '
            'it as selene_hal/config/<robot_type>.yaml. There is deliberately '
            'no default: a guessed capacity would publish a plausible wrong '
            'fraction rather than failing.'
        )
    with open(rcdl_path, 'r') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f'{rcdl_path}: not a YAML mapping')
    return data


def _lookup(entries, name: str, kind: str, rcdl_path: str) -> dict:
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get('name') == name:
            return entry
    available = [e.get('name') for e in (entries or []) if isinstance(e, dict)]
    raise ValueError(
        f'{rcdl_path}: no {kind} named {name!r}. Declared {kind}s: {available}'
    )


def _positive(entry: dict, key: str, name: str, kind: str,
              rcdl_path: str) -> float:
    raw = entry.get(key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f'{rcdl_path}: {kind} {name!r} declares {key}={raw!r}, which is '
            f'not a number.'
        )
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(
            f'{rcdl_path}: {kind} {name!r} declares {key}={raw!r}; it must be '
            f'finite and > 0.'
        )
    return value


def read_fill_capacity_kg(rcdl_path: str, sensor_name: str) -> float:
    """Return ``sensors[name].capacity_kg`` from an RCDL, in kilograms.

    Raises ``ValueError`` naming the file, the entry and the key when the
    sensor is absent or its capacity is missing or non-positive. Raising rather
    than defaulting is the point: this is the same number
    ``SensorConfig.extra['capacity_kg']`` carries into the HAL, and a sim that
    silently used a different one would publish a fraction the HAL converts
    back to the wrong mass, with nothing anywhere reporting a disagreement.
    """
    data = _load_rcdl(rcdl_path)
    entry = _lookup(data.get('sensors'), sensor_name, 'sensor', rcdl_path)
    return _positive(entry, 'capacity_kg', sensor_name, 'sensor', rcdl_path)


def read_transfer_rate(rcdl_path: str, actuator_name: str) -> float:
    """Return ``actuators[name].transfer_rate`` from an RCDL, in kg/s."""
    data = _load_rcdl(rcdl_path)
    entry = _lookup(data.get('actuators'), actuator_name, 'actuator', rcdl_path)
    return _positive(entry, 'transfer_rate', actuator_name, 'actuator',
                     rcdl_path)
