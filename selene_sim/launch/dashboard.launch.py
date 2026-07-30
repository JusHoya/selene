"""Dashboard + rosbridge launch.

Launches:
  - rosbridge_websocket on ws://localhost:9090 (always)
  - the React dashboard on http://localhost:3000 (unless headless:=true)

Args:
  headless (default false) — skip the dashboard process entirely
  prebuilt (default false) — serve selene_dashboard/build with a static file
      server instead of running the webpack dev server

Dashboard serving modes
-----------------------
`prebuilt:=false` (default, unchanged behaviour) runs `npm start`, i.e. the
react-scripts dev server. That compiles the bundle at launch time, so port 3000
does not answer for a while on WSL2 (validate_phase5.sh has historically waited
up to ~30s in a retry loop for this).

`prebuilt:=true` serves the already-built static bundle, which answers on port
3000 almost immediately. It requires a build to exist first:

    cd selene_dashboard && npm run build

The static server is `python3 -m http.server ... --directory build`, which is
the same command as the `serve` script in selene_dashboard/package.json. It is
invoked directly here (via sys.executable) so the prebuilt path needs neither
npm nor a shell wrapper process. Plain static serving is sufficient because the
dashboard is a single page with no client-side router — there are no deep links
that would need an SPA fallback rewrite.

NOT YET VALIDATED: neither mode has been executed in this environment (no ROS 2
/ Gazebo available). `npm run build` itself was confirmed to succeed.

Project root resolution
-----------------------
selene_dashboard is COLCON_IGNORE'd, so it is not an installed ament package and
its path must be found on disk. Resolution order:
  1. this file's own location (works from a source checkout, and from an
     install tree built with `colcon build --symlink-install`, where the
     installed launch file is a symlink back into the source tree)
  2. $SELENE_PROJECT_ROOT
  3. ~/selene
The first candidate that actually contains selene_dashboard/package.json wins.
"""

import os
import shutil
import sys

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.launch_description_sources import FrontendLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.substitutions import FindPackageShare


def _project_root_candidates():
    """Ordered, de-duplicated list of plausible project roots."""
    candidates = []

    # 1. Derived from this file: <root>/selene_sim/launch/dashboard.launch.py
    #    realpath() follows the symlink created by --symlink-install.
    here = os.path.dirname(os.path.realpath(__file__))
    candidates.append(os.path.dirname(os.path.dirname(here)))

    # 2. Explicit override.
    env_root = os.environ.get('SELENE_PROJECT_ROOT')
    if env_root:
        candidates.append(os.path.abspath(os.path.expanduser(env_root)))

    # 3. Historical default from the WSL2 sync workflow.
    candidates.append(os.path.expanduser('~/selene'))

    seen = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _resolve_dashboard_path():
    """Return the selene_dashboard directory, or raise with the paths tried."""
    tried = _project_root_candidates()
    for root in tried:
        path = os.path.join(root, 'selene_dashboard')
        if os.path.isfile(os.path.join(path, 'package.json')):
            return path
    raise RuntimeError(
        'Could not locate selene_dashboard/package.json. Tried:\n  '
        + '\n  '.join(os.path.join(t, 'selene_dashboard') for t in tried)
        + '\nSet SELENE_PROJECT_ROOT to the repository root, or launch with '
          'headless:=true to skip the dashboard.'
    )


def _dev_server_process(dashboard_path):
    """react-scripts dev server (compiles at launch; slow first response)."""
    npm = shutil.which('npm')
    if npm is None:
        raise RuntimeError(
            'npm was not found on PATH, so the dashboard dev server cannot '
            'start. Install Node.js 18+ (scripts/setup_wsl2.sh), or launch '
            'with headless:=true.'
        )

    react_scripts = os.path.join(dashboard_path, 'node_modules', '.bin', 'react-scripts')
    if not os.path.exists(react_scripts):
        raise RuntimeError(
            'Dashboard dependencies are not installed: {} is missing.\n'
            'Run:  cd {} && npm install\n'
            '(or use prebuilt:=true / headless:=true).'.format(
                react_scripts, dashboard_path)
        )

    return ExecuteProcess(
        cmd=[npm, 'start'],
        cwd=dashboard_path,
        additional_env={'BROWSER': 'none', 'HOST': '0.0.0.0'},
        output='screen',
    )


def _static_server_process(dashboard_path):
    """Serve the prebuilt bundle; port 3000 answers without a compile step."""
    build_dir = os.path.join(dashboard_path, 'build')
    if not os.path.isfile(os.path.join(build_dir, 'index.html')):
        raise RuntimeError(
            'prebuilt:=true but no production build was found at {}.\n'
            'Run:  cd {} && npm run build\n'
            '(or drop prebuilt:=true to use the dev server).'.format(
                os.path.join(build_dir, 'index.html'), dashboard_path)
        )

    return ExecuteProcess(
        cmd=[sys.executable, '-m', 'http.server', '3000',
             '--bind', '0.0.0.0', '--directory', build_dir],
        cwd=dashboard_path,
        output='screen',
    )


def _launch_setup(context, *args, **kwargs):
    headless = LaunchConfiguration('headless').perform(context).lower() in ('true', '1')
    prebuilt = LaunchConfiguration('prebuilt').perform(context).lower() in ('true', '1')

    rosbridge = IncludeLaunchDescription(
        FrontendLaunchDescriptionSource([
            FindPackageShare('rosbridge_server'),
            '/launch/rosbridge_websocket_launch.xml',
        ]),
    )

    if headless:
        return [rosbridge]

    # Resolve and validate only when the dashboard is actually wanted, so
    # headless launches never fail on a missing dashboard/npm/build.
    #
    # An exception raised inside an OpaqueFunction is fatal to the whole launch
    # service, and unified_sim.launch.py includes this file — so letting a
    # RuntimeError escape here would take down Gazebo, the orchestrator and every
    # agent because npm or node_modules was missing. That is a strictly worse
    # blast radius than the dashboard alone failing, which is what the previous
    # ExecuteProcess-only form did. Degrade instead: keep rosbridge (which CLI
    # tooling and the exit-gate script depend on) and report loudly.
    try:
        dashboard_path = _resolve_dashboard_path()
        dashboard = (_static_server_process(dashboard_path) if prebuilt
                     else _dev_server_process(dashboard_path))
    except RuntimeError as exc:
        return [
            rosbridge,
            LogInfo(msg='=' * 72),
            LogInfo(msg=f'DASHBOARD NOT STARTED: {exc}'),
            LogInfo(msg='Continuing without it. rosbridge is up on ws://localhost:9090, '
                        'so the simulation, orchestrator, agents and CLI tooling are '
                        'unaffected. Fix the above and relaunch, or pass headless:=true '
                        'to skip the dashboard deliberately.'),
            LogInfo(msg='=' * 72),
        ]

    return [rosbridge, dashboard]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('headless', default_value='false'),
        DeclareLaunchArgument(
            'prebuilt', default_value='false',
            description='Serve selene_dashboard/build statically instead of '
                        'running the react-scripts dev server. Requires '
                        '`npm run build` to have been run first.'),
        OpaqueFunction(function=_launch_setup),
    ])
