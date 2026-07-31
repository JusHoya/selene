"""Deviation D-14: the orchestrator's ROS stubs must not escape their package.

``selene_orchestrator/test/conftest.py`` installs hand-written stand-ins for
``rclpy``, ``selene_msgs``, ``geometry_msgs``, ``std_msgs``,
``builtin_interfaces`` and ``visualization_msgs`` so the orchestrator can be
imported with no ROS 2 present. Those stubs are shaped for exactly one
importer. When they were process-global, a single pytest run naming both
``selene_orchestrator/test`` and ``selene_hal/test`` put a half-``rclpy`` in
``sys.modules`` before ``selene_hal`` was imported, and
``selene_hal/selene_hal/gazebo_hal.py``'s
``from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy``
raised ``ImportError`` — not ``ModuleNotFoundError``, so
``pytest.importorskip`` re-raised it and the whole session aborted at
collection with 0 tests run.

Nothing caught it. No CI job ran a cross-package pytest invocation (the e2e job
runs one file, the gate-coverage job runs one file, and ``colcon test`` gives
each package its own process), and every per-package command in the README kept
passing. It was found by hand, by running the command the README documents.

The two tests here are the machine that would have caught it:

* the first is free and runs in every lane — it asserts that no stub is
  visible in ``sys.modules`` while a ``selene_hal`` test is executing, which
  is the invariant the fix relies on;
* the second is the reproduction itself — a real cross-package pytest process
  in a subprocess. It fails for the original defect and for any future stub
  that leaks past collection, regardless of which lane invoked it.

WHAT THIS DOES NOT PROVE. It says the stubs stay inside
``selene_orchestrator/test``. It says nothing about whether they are faithful
to the real ROS 2 types — that is ``test_conftest_mirrors_msgs.py``'s job for
the message half, and nothing's job for ``rclpy``.
"""

import os
import subprocess
import sys

import pytest

_HAL_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HAL_TEST_DIR, '..', '..'))

#: Parent directory of each pure-Python package, for the subprocess's
#: PYTHONPATH. Mirrors the README's cross-package command.
_PACKAGE_PARENTS = (
    'selene_orchestrator', 'selene_isru', 'selene_hal', 'selene_agent',
)

#: The smallest cross-package invocation that reproduces D-14.
#:
#: * ``test_material_ledger.py`` imports ``selene_orchestrator.orchestrator_node``,
#:   so the stubs are genuinely needed and genuinely installed;
#: * ``test_conftest_mirrors_msgs.py`` reads ``sys.modules['selene_msgs.msg']``
#:   during the *run* phase, so a fix that merely narrowed the stubs to
#:   collection time would turn its 27 assertions into vacuous skips and be
#:   caught here rather than silently accepted;
#: * ``test_gazebo_fill_level.py`` is the victim — the module whose import
#:   aborted the session. It now carries a defensive module-level skip if it
#:   detects a stub, which stops a regression from costing a whole session's
#:   results but would also hide the regression from this test; hence the
#:   assertion below that it did not fire, and hence
#: * the first test in *this* file, re-run inside the subprocess by node id.
#:   That is the check with no defensive layer in front of it: in a genuine
#:   cross-package process it sees the leak directly. (Only that one node, so
#:   the subprocess cannot recurse into this test.)
_PROBE_ARGS = (
    os.path.join('selene_orchestrator', 'test', 'test_material_ledger.py'),
    os.path.join('selene_orchestrator', 'test', 'test_conftest_mirrors_msgs.py'),
    os.path.join('selene_hal', 'test', 'test_gazebo_fill_level.py'),
    os.path.join('selene_hal', 'test', 'test_ros_stub_isolation.py')
    + '::test_no_orchestrator_stub_is_visible_to_selene_hal',
)

#: Substring of the defensive skip in ``test_gazebo_fill_level.py``. Its
#: presence in the subprocess output means a stub was in force there.
_DEFENSIVE_SKIP = 'must not be imported against it (D-14)'


def test_no_orchestrator_stub_is_visible_to_selene_hal():
    """The in-process half: free, and true in every lane.

    In a ``selene_hal``-only run there is no stub to see. In a run that also
    names ``selene_orchestrator/test`` the conftest has already been imported
    by the time this executes, so a stub that outlives its window shows up
    here.
    """
    leaked = sorted(
        name for name, module in list(sys.modules.items())
        if getattr(module, '__selene_test_stub__', False)
    )
    assert not leaked, (
        'selene_orchestrator/test/conftest.py left ROS stubs in sys.modules '
        'where selene_hal can see them: %s. They are incomplete relative to '
        'what selene_hal imports and will abort a cross-package pytest run at '
        'collection. See deviation D-14.' % (leaked,)
    )


def test_the_defensive_skip_message_has_not_drifted():
    """``_DEFENSIVE_SKIP`` is matched against another file's *output*.

    Nothing else ties the two together, so an innocuous reword of that skip
    reason would quietly turn the assertion below into a tautology. Pin it.
    """
    path = os.path.join(_HAL_TEST_DIR, 'test_gazebo_fill_level.py')
    with open(path, encoding='utf-8') as handle:
        source = handle.read()
    assert _DEFENSIVE_SKIP in source, (
        '%r no longer appears in %s, so the assertion that the defensive skip '
        'did not fire can never trip. Update _DEFENSIVE_SKIP.'
        % (_DEFENSIVE_SKIP, path)
    )


def _missing_probe_files():
    return [arg for arg in _PROBE_ARGS
            if not os.path.isfile(
                os.path.join(_REPO_ROOT, arg.split('::', 1)[0]))]


def test_a_cross_package_pytest_process_still_runs():
    """The reproduction: one pytest process spanning both packages.

    Run as a subprocess rather than in-process because the defect is a
    property of pytest's *startup* — it imports the conftest of every initial
    argument's directory before collecting anything — and that cannot be
    reproduced from inside an already-started session.
    """
    missing = _missing_probe_files()
    if missing:
        pytest.skip('not a full checkout; missing %s' % (missing,))

    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(
        [os.path.join(_REPO_ROOT, name) for name in _PACKAGE_PARENTS]
        + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else [])
    )

    result = subprocess.run(
        # -rs so skip *reasons* are printed: a stub leak that the defensive
        # guard absorbs would otherwise be invisible in -q output.
        [sys.executable, '-m', 'pytest', *_PROBE_ARGS,
         '-q', '-rs', '-p', 'no:cacheprovider'],
        cwd=_REPO_ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, (
        'a pytest process naming both selene_orchestrator/test and '
        'selene_hal/test failed (exit %d). This is deviation D-14: the '
        "orchestrator's ROS stubs are visible to selene_hal.\n\n%s"
        % (result.returncode, output)
    )
    assert _DEFENSIVE_SKIP not in output, (
        'the cross-package process survived only because '
        'test_gazebo_fill_level.py detected a ROS stub and skipped itself. '
        'That guard is a seatbelt, not a fix — the stubs are escaping '
        'selene_orchestrator/test again. See deviation D-14.\n\n%s' % (output,)
    )
    # Guard against the other way this could go green: everything skipping.
    assert ' passed' in output and 'no tests ran' not in output, (
        'the cross-package process exited 0 without running anything, which '
        'makes this test vacuous:\n\n%s' % (output,)
    )
