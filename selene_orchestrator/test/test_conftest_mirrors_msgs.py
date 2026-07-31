"""Every selene_msgs field must exist on the ROS-free stub — CLAUDE.md's rule.

CLAUDE.md says, in prose: "Any new or changed .msg MUST be mirrored in
selene_orchestrator/test/conftest.py or the CI e2e lane breaks at import."
This is that rule made executable.

It is a real gap, not a hypothetical one. Before 2026-07-30 the ``RobotState``
stub was missing ``task_progress``, ``velocity`` and ``stamp``, and
``ResourceMapUpdate`` was missing ``scout_id`` and ``stamp`` — so the first
time the orchestrator read ``msg.task_progress`` in a subscriber callback under
test, it would have raised AttributeError from deep inside the callback rather
than at import, where it is obvious.

WHAT THIS DOES NOT PROVE. The stubs are hand-written Python; ``colcon`` and
``rosidl`` never run on this box. A field-name typo shared by BOTH the .msg and
the stub passes here and fails at the first colcon build. A green run of this
test says the two agree, not that either is right.

Skipped entirely when the real generated ``selene_msgs`` is importable, because
then the stub is not in force and there is nothing to compare.
"""

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MSG_DIR = _REPO_ROOT / 'selene_msgs' / 'msg'

#: Message types the orchestrator's ROS-free lane has no reason to stub. Each
#: needs a reason in writing; an empty set is the healthy state.
NOT_STUBBED: dict[str, str] = {}


def _msg_fields(path: pathlib.Path) -> list[str]:
    """Field names in a .msg, ignoring comments, blanks and constants.

    A constant is ``TYPE NAME=VALUE`` and becomes a CLASS attribute on the
    generated type, not an instance field, so it is not something the stub's
    per-instance ``__init__`` would set.
    """
    fields = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        if '=' in line.split(None, 1)[1]:
            continue                      # constant, not an instance field
        fields.append(name)
    return fields


def _stub_module():
    module = sys.modules.get('selene_msgs.msg')
    if module is None:
        pytest.skip('selene_msgs.msg not in sys.modules')
    if not getattr(module, '__selene_test_stub__', False):
        pytest.skip('real generated selene_msgs is in force; nothing to mirror')
    return module


def _msg_files():
    return sorted(_MSG_DIR.glob('*.msg'))


def test_the_message_directory_is_where_this_test_thinks_it_is():
    assert _MSG_DIR.is_dir(), _MSG_DIR
    assert _msg_files(), f'no .msg files under {_MSG_DIR}'


@pytest.mark.parametrize('msg_path', _msg_files(), ids=lambda p: p.stem)
def test_stub_mirrors_every_field(msg_path):
    module = _stub_module()
    name = msg_path.stem
    if name in NOT_STUBBED:
        pytest.skip(f'{name} deliberately not stubbed: {NOT_STUBBED[name]}')

    stub_cls = getattr(module, name, None)
    assert stub_cls is not None, (
        f'{name}.msg exists but conftest._stub_selene_msgs has no stub for it. '
        f'Add one, or add it to NOT_STUBBED with a reason.')

    instance = stub_cls()
    missing = [f for f in _msg_fields(msg_path) if not hasattr(instance, f)]
    assert not missing, (
        f'{name} stub is missing field(s) {missing}. The orchestrator will '
        f'AttributeError inside a subscriber callback under test rather than '
        f'at import. Mirror them in conftest._stub_selene_msgs.')


@pytest.mark.parametrize('msg_path', _msg_files(), ids=lambda p: p.stem)
def test_stub_has_no_field_the_msg_does_not(msg_path):
    """The other direction, which is how a stub rots.

    A stub field with no .msg behind it lets a test assert on something that
    will not exist on the wire — exactly as misleading as a missing one, and
    harder to notice because everything passes.
    """
    module = _stub_module()
    name = msg_path.stem
    if name in NOT_STUBBED:
        pytest.skip(f'{name} deliberately not stubbed: {NOT_STUBBED[name]}')
    stub_cls = getattr(module, name, None)
    if stub_cls is None:
        pytest.skip('covered by test_stub_mirrors_every_field')

    declared = set(_msg_fields(msg_path))
    extra = sorted(
        attr for attr in vars(stub_cls()) if attr not in declared
    )
    assert not extra, (
        f'{name} stub declares field(s) {extra} that {msg_path.name} does not. '
        f'Either the .msg lost them or the stub invented them.')
