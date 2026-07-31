"""Every declared sensor has a publisher, and every publisher is declared.

WHY THIS EXISTS
``selene_hal/config/hauler.yaml:27`` declared the load cell on
``sensors/load_cell``. ``gazebo_hal.py`` builds a sensor's topic as
``/{robot_id}/{sd.topic}``. ``bin_load_node.py`` published
``/{robot_id}/sensors/bin_load``. So the hauler's HAL subscribed to a topic
nothing in the repository published, ``HaulSkill`` read the ``is_valid=False``
default forever, and every haul reported delivering 0.0 kg -- for two phases,
with no error anywhere and 174 green tests (deviation D-06).

A topic mismatch is invisible in ROS 2 by construction: a subscription to a
topic with no publisher is not an error, it is an ordinary state of the graph
during startup. Nothing can catch it at runtime, so it has to be caught here.

HOW
The RCDL side is read from ``selene_hal/config/*.yaml``. The publisher side is
AST-parsed out of ``selene_sim/selene_sim/*.py`` and the ``ros_gz_bridge``
remappings in ``simulation.launch.py`` -- no imports, so this runs with no ROS
and no rclpy.

Topics are compared as their tail after the last variable segment, because both
sides put the robot id first by construction: the RCDL side is always
``/{robot_id}/<tail>`` (``gazebo_hal.py``) and every sim node builds
``prefix = f'/{self.robot_id}'`` and formats ``f'{prefix}/<tail>'``. That means
this test would NOT catch a node that published the right tail under the wrong
namespace. Stated plainly rather than papered over; the mismatch it is built to
catch is in the tail.

THE ALLOW-LISTS ARE CHECKED FOR ROT. Each entry is asserted to still be
unmatched, so a pre-existing gap that somebody later closes fails this test and
has to be removed from the list, instead of sitting there forever describing a
problem that no longer exists.
"""

import ast
import os

import pytest
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))

SIM_SOURCE_DIR = os.path.join(_REPO, 'selene_sim', 'selene_sim')
LAUNCH_FILE = os.path.join(_REPO, 'selene_sim', 'launch', 'simulation.launch.py')
RCDL_DIR = os.path.join(_REPO, 'selene_hal', 'config')
RCDL_FILES = ('scout.yaml', 'excavator.yaml', 'hauler.yaml')

# Sensor topic tails declared by an RCDL that no simulation node publishes.
# PRE-EXISTING and out of scope for deviation D-06: no simulated camera or IMU
# exists at all, on any robot type. A skill that read either would get the
# is_valid=False default, exactly as the load cell did -- so they are recorded
# here rather than tolerated silently.
DECLARED_WITHOUT_PUBLISHER = {
    'sensors/depth': 'no simulated stereo camera node exists (all three types)',
    'sensors/imu': 'no simulated IMU node exists (all three types)',
}

# Topics a simulation node publishes under the robot namespace that no RCDL
# sensor declares. None of these is a defect; each is here because the forward
# rule alone would not explain it.
PUBLISHED_WITHOUT_DECLARATION = {
    'battery_state': (
        'consumed by GazeboBattery, which builds the topic itself from '
        'robot_id rather than from an RCDL sensor entry -- battery is a '
        'top-level RCDL section, not a sensor'),
    'extraction/rate': (
        'telemetry from extraction_node with no subscriber anywhere; '
        'pre-existing, out of scope for D-06'),
    'extraction/total': (
        'telemetry from extraction_node with no subscriber anywhere; it '
        'duplicates the hopper mass by a second integration and is not what '
        'the material ledger reads; pre-existing, out of scope for D-06'),
    'orchestrator/alerts': (
        'NOT a per-robot topic at all -- world_odometry_node publishes '
        'FleetAlert on the ABSOLUTE /orchestrator/alerts, and the tail-based '
        'parse above strips the leading slash and reads it as if it were '
        'under the robot namespace. The subscriber is the dashboard '
        '(FR-DASH-4) and the orchestrator alert log, not an RCDL sensor. It '
        'is listed here rather than special-cased in the parser because the '
        'parser being dumb is the point: it can only resolve constants and '
        'f-strings, and every exception it cannot see through belongs in one '
        'visible list'),
}

_VARIABLE = '\x00'   # stands in for any f-string {expression}


def _topic_pattern(node):
    """Render a topic argument as text with {expressions} replaced by a marker.

    Returns None for anything not statically resolvable (a bare name, a call),
    which is then ignored rather than guessed at.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append(_VARIABLE)
            else:                                   # pragma: no cover
                return None
        return ''.join(parts)
    return None


def _tail(pattern):
    """The portion after the last variable segment, without a leading slash."""
    if pattern is None:
        return None
    return pattern.rsplit(_VARIABLE, 1)[-1].lstrip('/')


def _iter_calls(path):
    with open(path, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def published_topics():
    """{tail: source file} for every create_publisher in the sim nodes."""
    found = {}
    for filename in sorted(os.listdir(SIM_SOURCE_DIR)):
        if not filename.endswith('.py'):
            continue
        path = os.path.join(SIM_SOURCE_DIR, filename)
        for call in _iter_calls(path):
            if _call_name(call) != 'create_publisher' or len(call.args) < 2:
                continue
            tail = _tail(_topic_pattern(call.args[1]))
            if tail:
                found[tail] = filename
    return found


def bridged_topics():
    """{tail: 'simulation.launch.py'} for every ros_gz_bridge remapping target.

    The odometry every RCDL declares is not published by a selene_sim node at
    all -- it comes out of Gazebo through parameter_bridge and is remapped onto
    ``/{robot_id}/odom``. Without reading the remappings this test would report
    a false mismatch on every robot type.
    """
    found = {}
    for call in _iter_calls(LAUNCH_FILE):
        for keyword in call.keywords:
            if keyword.arg != 'remappings':
                continue
            if not isinstance(keyword.value, ast.List):
                continue
            for element in keyword.value.elts:
                if not isinstance(element, ast.Tuple) or len(element.elts) != 2:
                    continue
                tail = _tail(_topic_pattern(element.elts[1]))
                if tail:
                    found[tail] = os.path.basename(LAUNCH_FILE)
    return found


def declared_sensors():
    """[(robot_type, sensor_name, topic_tail)] across every shipped RCDL."""
    declared = []
    for filename in RCDL_FILES:
        with open(os.path.join(RCDL_DIR, filename), 'r') as f:
            rcdl = yaml.safe_load(f)
        for sensor in rcdl.get('sensors', []):
            declared.append((
                rcdl['robot_type'], sensor['name'],
                # gazebo_hal builds /{robot_id}/{sd.topic}; the tail is sd.topic
                # with any stray leading slash removed.
                sensor['topic'].lstrip('/'),
            ))
    return declared


# ---------------------------------------------------------------------------
# Sanity: the parsers found something. A silent zero here would make every
# assertion below pass vacuously, which is the failure mode this whole file is
# about.
# ---------------------------------------------------------------------------

def test_parsers_are_not_returning_nothing():
    assert len(published_topics()) >= 4, published_topics()
    assert len(bridged_topics()) >= 2, bridged_topics()
    assert len(declared_sensors()) >= 12, declared_sensors()


def test_the_world_pose_topic_is_published_and_declared():
    """The frame fix's topic, pinned in both directions and against its constant.

    ``world_odometry_node`` is the one place a dead-reckoned pose becomes a
    world pose, and everything else in SELENE reads its output. Three things can
    silently disconnect that: the node publishing a different tail from the one
    the RCDLs declare (the D-06 load-cell defect, exactly), an RCDL reverting to
    the raw ``odom`` (which would restore the frame defect with no error
    anywhere), and the topic literal in the node drifting from
    ``world_frame.WORLD_ODOM_TOPIC``, which the rest of the package imports.
    """
    import sys
    sys.path.insert(0, os.path.dirname(SIM_SOURCE_DIR))
    from selene_sim.world_frame import RAW_ODOM_TOPIC, WORLD_ODOM_TOPIC

    published = published_topics()
    assert published.get(WORLD_ODOM_TOPIC) == 'world_odometry_node.py', (
        f'{WORLD_ODOM_TOPIC!r} must be published by world_odometry_node.py; '
        f'found {published.get(WORLD_ODOM_TOPIC)!r}. The publish call has to '
        f'use an f-string literal, not a variable, or this parser cannot see '
        f'it at all.')

    odometry_topics = {
        (robot_type, tail)
        for robot_type, name, tail in declared_sensors() if name == 'odometry'
    }
    assert odometry_topics == {
        ('scout', WORLD_ODOM_TOPIC),
        ('excavator', WORLD_ODOM_TOPIC),
        ('hauler', WORLD_ODOM_TOPIC),
    }, (
        f'every RCDL must point its odometry sensor at {WORLD_ODOM_TOPIC!r}. '
        f'{RAW_ODOM_TOPIC!r} is Gazebo\'s raw dead-reckoned pose, whose origin '
        f'is the robot\'s spawn — reading it as world coordinates is the defect '
        f'world_odometry_node exists to remove. Found: {sorted(odometry_topics)}')


def test_only_the_frame_node_subscribes_to_the_raw_odometry():
    """Raw ``/{rid}/odom`` has exactly one consumer, and that is the design.

    "One conversion point" is a claim about the code, so it is checked as one.
    Any other selene_sim node subscribing to the raw topic would be applying the
    spawn transform itself, or worse, not applying it.
    """
    import sys
    sys.path.insert(0, os.path.dirname(SIM_SOURCE_DIR))
    from selene_sim.world_frame import RAW_ODOM_TOPIC

    def _subscribed_tails(filename):
        path = os.path.join(SIM_SOURCE_DIR, filename)
        return {
            _tail(_topic_pattern(call.args[1]))
            for call in _iter_calls(path)
            if _call_name(call) == 'create_subscription' and len(call.args) >= 2
        }

    offenders = sorted(
        filename for filename in os.listdir(SIM_SOURCE_DIR)
        if filename.endswith('.py') and filename != 'world_odometry_node.py'
        and RAW_ODOM_TOPIC in _subscribed_tails(filename)
    )
    assert not offenders, (
        f'these nodes subscribe to the raw dead-reckoned /{{rid}}/'
        f'{RAW_ODOM_TOPIC} instead of the world-referenced topic: {offenders}')

    # And the converter really does read the raw one. Without this the test
    # above passes trivially on a system where NOTHING reads /odom, which is a
    # fleet whose every consumer is stuck on its is_valid=False default.
    assert RAW_ODOM_TOPIC in _subscribed_tails('world_odometry_node.py'), (
        f'world_odometry_node must subscribe to /{{rid}}/{RAW_ODOM_TOPIC}; its '
        f'subscriptions are '
        f'{sorted(_subscribed_tails("world_odometry_node.py"))}')


def test_the_two_fixed_topics_are_where_the_rcdls_say():
    """The specific mismatch this test was written for, named explicitly."""
    published = published_topics()

    assert 'sensors/load_cell' in published, (
        'the hauler load cell must be published on sensors/load_cell '
        '(hauler.yaml:27); found: ' + repr(sorted(published)))
    assert 'sensors/bin_load' not in published, (
        'sensors/bin_load is the old topic no RCDL declares and nothing '
        'subscribes to -- publishing it again re-opens D-06')
    assert 'sensors/hopper_fill' in published


# ---------------------------------------------------------------------------
# Forward: declared -> published
# ---------------------------------------------------------------------------

def test_every_declared_sensor_has_a_publisher():
    available = set(published_topics()) | set(bridged_topics())

    missing = [
        (robot_type, name, tail)
        for robot_type, name, tail in declared_sensors()
        if tail not in available and tail not in DECLARED_WITHOUT_PUBLISHER
    ]

    assert not missing, (
        'RCDL sensors whose topic nothing publishes -- the HAL will subscribe '
        'and read the is_valid=False default forever:\n'
        + '\n'.join(f'  {rt} {name} -> /<robot_id>/{tail}  NO PUBLISHER'
                    for rt, name, tail in missing)
        + '\n(published by sim nodes: ' + repr(sorted(published_topics()))
        + '; bridged: ' + repr(sorted(bridged_topics())) + ')')


@pytest.mark.parametrize('tail', sorted(DECLARED_WITHOUT_PUBLISHER))
def test_declared_without_publisher_allowlist_has_not_rotted(tail):
    available = set(published_topics()) | set(bridged_topics())

    assert tail not in available, (
        f'{tail!r} is now published, so it must be removed from '
        f'DECLARED_WITHOUT_PUBLISHER. Reason it was listed: '
        f'{DECLARED_WITHOUT_PUBLISHER[tail]}')


@pytest.mark.parametrize('tail', sorted(DECLARED_WITHOUT_PUBLISHER))
def test_declared_without_publisher_allowlist_is_still_declared(tail):
    declared = {t for _rt, _name, t in declared_sensors()}

    assert tail in declared, (
        f'{tail!r} is no longer declared by any RCDL, so the entry in '
        f'DECLARED_WITHOUT_PUBLISHER describes nothing and must be removed.')


# ---------------------------------------------------------------------------
# Reverse: published -> declared
# ---------------------------------------------------------------------------

def test_every_published_topic_is_declared_or_explained():
    declared = {tail for _rt, _name, tail in declared_sensors()}

    orphans = [
        (tail, source)
        for tail, source in sorted(published_topics().items())
        if tail not in declared and tail not in PUBLISHED_WITHOUT_DECLARATION
    ]

    assert not orphans, (
        'simulation topics no RCDL declares -- nothing in the HAL will ever '
        'subscribe to these:\n'
        + '\n'.join(f'  {source}: /<robot_id>/{tail}  PUBLISHED TO NOBODY'
                    for tail, source in orphans))


@pytest.mark.parametrize('tail', sorted(PUBLISHED_WITHOUT_DECLARATION))
def test_published_without_declaration_allowlist_has_not_rotted(tail):
    declared = {t for _rt, _name, t in declared_sensors()}
    published = published_topics()

    assert tail in published, (
        f'{tail!r} is no longer published by any sim node, so the entry in '
        f'PUBLISHED_WITHOUT_DECLARATION must be removed.')
    assert tail not in declared, (
        f'{tail!r} is now declared by an RCDL, so it must be removed from '
        f'PUBLISHED_WITHOUT_DECLARATION. Reason it was listed: '
        f'{PUBLISHED_WITHOUT_DECLARATION[tail]}')
