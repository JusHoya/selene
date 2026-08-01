"""Every key in nav_params.yaml must have a reader, or a written reason.

WHY THE EXISTING GUARD CANNOT DO THIS
-------------------------------------
``selene_orchestrator/test/test_no_orphan_parameters.py`` AST-walks the
ORCHESTRATOR's ``declare_parameter`` calls and fails on any that nothing reads.
It is a good guard and it is blind to the shape that cost this project a
mission. Its own docstring, written on 2026-07-31, put it exactly right about
the OTHER case and the register said so about this one:

    a limit that lives in a YAML file no node declares at all is invisible to
    it -- the parameter is not orphaned, it is absent.

``navigation.max_traversable_slope_deg`` was never a ROS parameter. It lived in
``selene_agent/config/nav_params.yaml``, was loaded with ``yaml.safe_load`` and
handed to ``OccupancyGrid.from_config``, and nothing ever looked at it. Four
phases, five instances of the pattern, and a hauler pinned on a 34 degree wall
reporting success. This file is the guard for THAT shape: it starts from the
config FILE and asks who reads each key, rather than starting from the code and
asking which declarations are unused.

WHAT WAS COUNTED, AND BY WHOM
-----------------------------
An earlier analysis put the number of zero-reader leaf keys at 14 and an
adversarial reviewer re-derived it as 17. Recomputed here from scratch on
2026-08-01 against ``HEAD`` (commit 7727ba8): **26 leaf keys, 17 with no
reader** -- the reviewer's figure, and the same three groups they named (the
whole ``path_follower:`` block, the whole ``obstacle_avoidance:`` block, three
``mission.`` keys) plus ``max_traversable_slope_deg``,
``slope_penalty_weight`` and ``hazard_penalty_weight``. The 14 is the 17 minus
those three ``navigation.`` keys.

After this change: **22 leaf keys, 5 with no reader**, all of them the
``obstacle_avoidance:`` block, all five allow-listed with the same reason.

    read      max_traversable_slope_deg, slope_penalty_weight (D-28)
    read      all six path_follower keys
    deleted   hazard_penalty_weight (no hazard layer exists to weight)
    deleted   mission.recharge_position (D-32; three coordinates disagreed)
    deleted   mission.low_battery_threshold, mission.recharge_target
              (silent duplicates of ROS parameters that already existed)

WHAT "READ" MEANS HERE, PRECISELY
---------------------------------
A string literal in a genuine config-read POSITION -- a subscript
(``cfg['grid_width']``), the first argument of a ``.get(...)``, or a key or
value of a dict literal (which is how ``PATH_FOLLOWER_KEYS`` translates
``stall_timeout_s`` into ``stall_timeout``). Deliberately NOT "the name appears
anywhere in the source": a key named in a log message, a docstring or a comment
about how sad it is that nothing reads the key would otherwise count as a
reader, which is the failure mode of every grep-based version of this check.
``test_the_reader_detector_can_tell_the_two_apart`` exercises each accepted
position and each rejected one, so the detector is not itself taken on trust.

MUTATIONS RUN AGAINST THIS FILE (house rule 2), each applied then reverted on
2026-08-01. Counts are MEASURED; the baseline is 8 passed.

* ``OccupancyGrid.from_config``'s ``nav.get("max_traversable_slope_deg")``
  -> ``None`` -> 3 failed, 5 passed: the allow-list check, the count, and
  ``test_the_slope_limit_and_its_weight_are_read``, which is the one that names
  the deviation.
* build ``PATH_FOLLOWER_KEYS`` without string literals -> 3 failed, 5 passed.
  It takes SIX keys with it in one edit, which is why the count is pinned as
  well as the set.
* add ``navigation.bogus_knob: 1.0`` to nav_params.yaml -> 2 failed, 6 passed,
  naming the key.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
NAV_PARAMS = REPO / 'selene_agent' / 'config' / 'nav_params.yaml'

#: Where a reader may live. ``selene_agent``'s production modules are the only
#: things that load this file today (``agent_node`` reads it and hands it to
#: ``OccupancyGrid.from_config`` and ``Navigator``); ``scripts/`` is included so
#: that a tool reading a key counts as a reader rather than being missed.
#: Test directories are excluded on purpose -- ``AdaptiveSurveyPlanner`` shipped
#: with green unit tests and zero call sites, so a test is not a reader.
READER_ROOTS = ('selene_agent/selene_agent', 'scripts')

#: Leaf keys with NO reader, each with the reason it is tolerated. Removing a
#: name from this dict is a fix. Adding one needs a reason in writing, here.
#:
#: All five are arguments of ``selene_agent/selene_agent/obstacle_avoidance.py``'s
#: ``ObstacleAvoidance``, and its constructor defaults are exactly these values.
#: They are not wired because THAT CLASS HAS NO PRODUCTION CALLER EITHER -- only
#: ``selene_agent/test/test_navigator.py`` constructs it -- so reading the config
#: would move the dead end one level up and no further. Making them live means
#: calling the class from the driving loop, which is a behaviour change to how
#: every robot moves and not a config fix.
#:
#: (``depth_image_bins`` does not even name the argument: the constructor calls
#: it ``num_bins``. Nothing has ever noticed, because nothing has ever read it.)
KNOWN_UNREAD = {
    'obstacle_avoidance.detection_range':
        'ObstacleAvoidance has no production caller; wiring the config would '
        'not make it run',
    'obstacle_avoidance.critical_range':
        'as detection_range',
    'obstacle_avoidance.avoidance_gain':
        'as detection_range',
    'obstacle_avoidance.slow_factor':
        'as detection_range',
    'obstacle_avoidance.depth_image_bins':
        'as detection_range, and it does not match the constructor argument '
        'name (num_bins) either',
}

#: Pinned so the number is assertable and not only the set. The set equality
#: below is the stronger check; this exists so that a change to the ALLOW-LIST
#: itself -- the one edit set equality cannot object to -- still has to be
#: deliberate. It was 17 at commit 7727ba8.
ZERO_READER_KEY_COUNT = 5

#: Deleted on 2026-08-01. Asserted absent rather than merely unread, because
#: each was a second silent statement of a number that lives somewhere else and
#: restoring one restores the defect.
DELETED_KEYS = {
    'navigation.hazard_penalty_weight',
    'mission.recharge_position',
    'mission.low_battery_threshold',
    'mission.recharge_target',
}


# ---------------------------------------------------------------------------
# The two halves of the check
# ---------------------------------------------------------------------------

def _leaf_keys(node, prefix=''):
    """Dotted paths to every leaf of a parsed YAML mapping.

    A LIST IS A LEAF, not a container to recurse into. ``static_obstacles.rocks``
    is one knob whose value happens to be 26 dicts; treating each rock's ``x``
    as a separate config key would drown the real signal in 78 names.
    """
    if isinstance(node, dict):
        out = []
        for key, value in node.items():
            out.extend(_leaf_keys(value, f'{prefix}{key}.'))
        return out
    return [prefix[:-1]]


def _read_names(source: str) -> set:
    """String literals in a genuine config-read position. See the docstring."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            names.add(node.slice.value)
        elif (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get'
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            names.add(node.args[0].value)
        elif isinstance(node, ast.Dict):
            for item in list(node.keys) + list(node.values):
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    names.add(item.value)
    return names


@pytest.fixture(scope='module')
def readers() -> set:
    names = set()
    for root in READER_ROOTS:
        for path in sorted((REPO / root).rglob('*.py')):
            if '__pycache__' in path.parts or 'test' in path.parts:
                continue
            try:
                names |= _read_names(path.read_text(encoding='utf-8'))
            except SyntaxError as error:            # pragma: no cover
                raise AssertionError(
                    f'{path} does not parse, so this guard cannot see whether '
                    f'it reads anything: {error}') from error
    return names


@pytest.fixture(scope='module')
def leaf_keys() -> list:
    return _leaf_keys(yaml.safe_load(NAV_PARAMS.read_text(encoding='utf-8')))


@pytest.fixture(scope='module')
def unread(leaf_keys, readers) -> set:
    return {key for key in leaf_keys
            if key.rsplit('.', 1)[-1] not in readers}


# ---------------------------------------------------------------------------
# The detector, tested before it is trusted
# ---------------------------------------------------------------------------

def test_the_reader_detector_can_tell_the_two_apart():
    """Each accepted position, and each rejected one, on a source it owns.

    Without this the whole file is one heuristic asserting things about another
    heuristic. The rejected cases matter most: this repository's config comments
    are long and name their own keys constantly, and a detector that counted a
    docstring would report every key as read and pass forever.
    """
    accepted = _read_names(
        "cfg['subscripted']\n"
        "nav.get('dot_get', 1.0)\n"
        "MAPPING = {'dict_key': 'dict_value'}\n"
    )
    assert accepted == {'subscripted', 'dot_get', 'dict_key', 'dict_value'}

    rejected = _read_names(
        '"""A docstring naming in_a_docstring, sadly unread."""\n'
        "log('in_a_log_message is not a read')\n"
        "# in_a_comment\n"
        "def f(in_a_signature=1.0):\n"
        "    return in_a_signature\n"
        "obj.in_an_attribute\n"
    )
    assert rejected == set(), f'these should not count as reads: {rejected}'


def test_a_key_no_node_declares_is_visible_here(readers):
    """D-28'S EXACT SHAPE, asserted as detectable.

    ``max_traversable_slope_deg`` is not a ROS parameter and never was, so
    ``test_no_orphan_parameters.py`` could not see it: "the parameter is not
    orphaned, it is absent". This check starts from the FILE, so a key that no
    node declares is not merely visible -- it is the only kind of key there is.
    """
    invented = _leaf_keys({'navigation': {'a_knob_nothing_declares': 1.0}})
    assert invented == ['navigation.a_knob_nothing_declares']
    assert invented[0].rsplit('.', 1)[-1] not in readers


# ---------------------------------------------------------------------------
# The state of the shipped file
# ---------------------------------------------------------------------------

def test_no_new_unread_keys(unread):
    """The guard proper: exact set equality against the written allow-list.

    Equality rather than containment, in both directions. A NEW unread key is
    the defect this exists for; an allow-listed key that has since acquired a
    reader is an allow-list rotting into a permanent excuse, which is the
    lesson ``test_no_orphan_parameters.py`` was written for arriving from the
    other side.
    """
    new = unread - set(KNOWN_UNREAD)
    assert not new, (
        'nav_params.yaml key(s) that nothing reads: ' + ', '.join(sorted(new))
        + '. A config key with no reader is a knob an operator can set that '
          'does nothing -- see this file\'s docstring for the four phases and '
          'one pinned hauler that cost. Read it, delete it, or add it to '
          'KNOWN_UNREAD with a reason.')


def test_the_allow_list_is_still_honest(unread):
    """Every allow-listed key is still unread, and every one has a reason."""
    fixed = set(KNOWN_UNREAD) - unread
    assert not fixed, (
        'these now have readers and should be deleted from KNOWN_UNREAD: '
        + ', '.join(sorted(fixed)))
    for key, reason in KNOWN_UNREAD.items():
        assert reason and len(reason) > 10, (
            f'{key} is allow-listed without a usable reason')


def test_the_zero_reader_count_only_goes_down(unread, leaf_keys):
    """17 at commit 7727ba8, 5 now. Pinned so the allow-list cannot grow quietly.

    Set equality above already refuses a new unread key. This refuses the edit
    set equality cannot object to: adding a name to KNOWN_UNREAD and to the
    config in the same change. Raising this number needs a deliberate edit here
    and a reason in the commit.
    """
    assert len(unread) == ZERO_READER_KEY_COUNT, (
        f'{len(unread)} nav_params.yaml keys have no reader, pinned at '
        f'{ZERO_READER_KEY_COUNT}: {sorted(unread)}')
    assert len(leaf_keys) == 22, (
        f'nav_params.yaml has {len(leaf_keys)} leaf keys, pinned at 22. If '
        f'that is a deliberate addition, say so here and check the new key has '
        f'a reader.')
    assert len(unread) < len(leaf_keys) / 2, (
        'more than half of this config file is inert')


def test_the_slope_limit_and_its_weight_are_read(readers):
    """THE SPECIFIC REGRESSION, named separately from the count.

    Named on its own so that if someone deletes the read, the failure says
    which deviation reopened rather than reporting an arithmetic difference.
    D-28 is the fifth instance of "wired but never called" in this repository
    and the only one that made a physical mission impossible.

    Note what the absence of ``max_traversable_slope_deg`` would actually mean:
    ``OccupancyGrid.from_config`` loads the terrain ONLY when the key is
    present, so deleting it from the config does not relax the limit, it
    removes slope enforcement entirely and silently.
    """
    for key in ('max_traversable_slope_deg', 'slope_penalty_weight'):
        assert key in readers, (
            f'navigation.{key} is declared in nav_params.yaml and read by '
            f'nothing again. That is deviation D-28.')


def test_the_whole_path_follower_block_is_read(readers, leaf_keys):
    """Six keys at once, and the one that needs translating.

    ``Navigator`` built its ``PathFollower`` with the constructor's own defaults,
    so the entire block was settable and inert. ``stall_timeout_s`` is checked
    by name because it is the one that does not survive a mechanical splat --
    the constructor calls it ``stall_timeout``.
    """
    block = [key for key in leaf_keys if key.startswith('path_follower.')]
    assert len(block) == 6
    for key in block:
        assert key.rsplit('.', 1)[-1] in readers, f'{key} is unread again'
    assert 'stall_timeout_s' in readers and 'stall_timeout' in readers


def test_the_deleted_keys_stay_deleted(leaf_keys):
    """Each was a second, silent statement of a number that lives elsewhere.

    ``mission.recharge_position`` is D-32's third coordinate, at (-75, -100), on
    33.91 degree ground, read by nothing. ``mission.low_battery_threshold`` and
    ``mission.recharge_target`` duplicated the ``energy_critical_threshold`` and
    ``energy_recharge_target`` ROS parameters -- identically, which is why
    nobody noticed; a copy that had drifted would have been invisible.
    ``navigation.hazard_penalty_weight`` weighted a hazard layer that does not
    exist.
    """
    present = DELETED_KEYS & set(leaf_keys)
    assert not present, (
        'deleted nav_params.yaml key(s) are back: ' + ', '.join(sorted(present))
        + '. Each was a duplicate or a knob with no mechanism behind it; if one '
          'is genuinely needed, it needs a reader and a single source of truth.')
