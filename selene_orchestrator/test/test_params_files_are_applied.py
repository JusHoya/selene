"""A parameter file must reach the node it is written for, and configure it.

WHY THIS EXISTS
---------------
Two defects, both silent, both in the same file, both live for four phases
(``docs/phase5_deviation_register.md`` D-12 and D-13):

* ``selene_orchestrator/config/orchestrator_params.yaml`` was keyed
  ``orchestrator_node:`` while ``orchestrator.launch.py`` started the node as
  ``name='orchestrator'``. ROS 2 matches a parameter file against the node's
  **runtime** name, so under launch the file matched nothing and every value in
  it fell back to its ``declare_parameter`` default. The same file applied
  correctly under ``scripts/start.sh``, which runs ``ros2 run`` with no name
  remap and therefore gets ``orchestrator_node``.
* Three ``bid_weight_*`` keys sat in that same file and are declared by no node
  that loads it — bidding is scored on the agent. ROS 2 drops an undeclared
  override without erroring.

Neither produced a symptom, because every value happened to equal the default
it was being ignored in favour of. That is the worst possible failure mode: the
file reads as configuration, ``ros2 param list`` shows the names, an operator
can edit a number, and nothing anywhere reports that the edit did nothing.

WHY IT HAS TO BE A ROS-FREE TEST
--------------------------------
A running system cannot tell you about either defect. A node whose parameter
file matched nothing looks exactly like a node whose file matched and agreed;
an undeclared override is simply absent from ``ros2 param list``. The evidence
is entirely in the source, so the check belongs in the pure-Python lane where it
runs on every push without a workspace.

``test_no_orphan_parameters.py`` is the mirror of this file and catches neither
case: it checks declared-but-never-read inside one module. This one checks the
two directions that cross a file boundary — written-but-never-matched, and
matched-but-never-declared.

WHAT IT CHECKS
--------------
1. **Discovery.** Every (parameter file, node) pairing in the repository, found
   by parsing ``selene_*/launch/*.launch.py`` with ``ast`` and ``scripts/*.sh``
   with a line-continuation join, never from a hardcoded list. A pairing this
   file cannot resolve is a FAILURE, not a skip — an allow-list that silently
   grows is how D-12 survived a register entry written about it.
2. **The key matches the runtime name.** Top-level keys must be ``/**`` (which
   matches any node) or exactly the name the node will run under. That name is
   the launch action's ``name=`` when it is a constant, and otherwise the name
   the node gives itself in ``super().__init__(...)`` — resolved through the
   package's ``setup.py`` console-script table, so renaming an executable moves
   this check with it.
3. **Every key is declared by that node.** Cross-checked against
   ``declare_parameter`` calls in the module the console script points at.
4. **The known pairings are still there**, so a params file that stops being
   passed to anything fails rather than quietly dropping out of checks 2 and 3.

NOT COVERED, DELIBERATELY. A ``name=`` built from substitutions
(``agent.launch.py``'s ``['agent_', robot_id]``) cannot be resolved statically;
for those, ``/**`` is required and anything else fails. Namespaces are not
modelled: nothing in this repository sets one, and a params file under a
namespace needs the namespace in its key too. If a ``namespace=`` ever appears
on a Node action that also takes a params file, this test fails rather than
guessing (see ``test_no_namespaced_nodes_take_params_files``).
"""

import ast
import collections
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Key that matches every node regardless of its runtime name.
WILDCARD = '/**'

#: Sentinel for "the launch action does not set name=", i.e. the node keeps the
#: name it gives itself.
NODE_DEFAULT_NAME = object()

#: Sentinel for "name= is built from substitutions and is not a constant".
DYNAMIC_NAME = object()

#: The pairings that must exist. Not the source of truth for what is checked —
#: discovery is — but a guard against a params file quietly ceasing to be
#: loaded by anything, which would remove it from every other check here while
#: leaving it on disk looking authoritative.
REQUIRED_PAIRINGS = {
    ('selene_orchestrator/config/orchestrator_params.yaml',
     'selene_orchestrator', 'orchestrator_node'),
}

Binding = collections.namedtuple(
    'Binding', 'params_file package executable declared_name origin')


# ---------------------------------------------------------------------------
# Small AST helpers
# ---------------------------------------------------------------------------

def _callee(node):
    """Bare name of a call's callee: ``Node(...)`` and ``a.b.Node(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ''


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kwargs(call):
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _assignments(tree):
    """``{name: value_node}`` for every single-target assignment in *tree*.

    Flat rather than scope-aware on purpose: launch files are short, and a
    duplicated local name across two functions is a readability problem this
    test has no business having an opinion about. Later assignments win, which
    matches the order a reader would resolve them in.
    """
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                found[target.id] = node.value
    return found


# ---------------------------------------------------------------------------
# Resolving a parameters= element to a file on disk
# ---------------------------------------------------------------------------

def _path_join_parts(call, assigns):
    """Resolve ``PathJoinSubstitution([...])`` to a path, or None.

    ``FindPackageShare('pkg')`` resolves to ``<repo>/pkg``. That is the install
    layout mapped back onto the source tree: setup.py installs
    ``config/<file>`` to ``share/<pkg>/config/<file>``, so the tail of the path
    is identical and only the root differs.
    """
    if not call.args:
        return None
    items = call.args[0]
    if not isinstance(items, ast.List):
        return None
    parts = []
    for item in items.elts:
        if isinstance(item, ast.Name):
            item = assigns.get(item.id, item)
        if isinstance(item, ast.Call) and _callee(item) == 'FindPackageShare':
            package = _const_str(item.args[0]) if item.args else None
            if package is None:
                return None
            parts.append(REPO / package)
            continue
        text = _const_str(item)
        if text is None:
            return None
        parts.append(text)
    if not parts:
        return None
    resolved = pathlib.Path(parts[0])
    for part in parts[1:]:
        resolved = resolved / part
    return resolved


def _params_file(node, assigns):
    """A ``parameters=`` list element, as a path, or None if it is not a file.

    An inline ``{...}`` dict is not a file and returns None — that is the
    ordinary way to pass per-instance values and needs no key at all.
    """
    if isinstance(node, ast.Name):
        node = assigns.get(node.id, node)
    if isinstance(node, ast.Dict):
        return None
    text = _const_str(node)
    if text is not None:
        return pathlib.Path(text) if text.endswith(('.yaml', '.yml')) else None
    if isinstance(node, ast.Call) and _callee(node) == 'PathJoinSubstitution':
        return _path_join_parts(node, assigns)
    # Anything else is a construct this test does not model. Returning None
    # here would hide it; the caller turns it into a failure instead.
    return False


# ---------------------------------------------------------------------------
# Discovery: launch files
# ---------------------------------------------------------------------------

def _launch_bindings():
    """Every (params file, Node action) pairing across the launch files."""
    bindings = []
    unresolved = []
    namespaced = []
    for launch_file in sorted(REPO.glob('selene_*/launch/*.launch.py')):
        tree = ast.parse(launch_file.read_text(encoding='utf-8'))
        assigns = _assignments(tree)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or _callee(call) != 'Node':
                continue
            kwargs = _kwargs(call)
            if 'parameters' not in kwargs:
                continue
            parameters = kwargs['parameters']
            if isinstance(parameters, ast.Name):
                parameters = assigns.get(parameters.id, parameters)
            if not isinstance(parameters, ast.List):
                unresolved.append('%s:%d parameters= is not a literal list'
                                  % (launch_file.name, call.lineno))
                continue

            if 'name' not in kwargs:
                declared_name = NODE_DEFAULT_NAME
            else:
                literal = _const_str(kwargs['name'])
                declared_name = literal if literal is not None else DYNAMIC_NAME

            for element in parameters.elts:
                resolved = _params_file(element, assigns)
                if resolved is False:
                    unresolved.append(
                        '%s:%d a parameters= element is neither an inline dict '
                        'nor a resolvable file path'
                        % (launch_file.name, element.lineno))
                    continue
                if resolved is None:
                    continue
                if 'namespace' in kwargs:
                    namespaced.append('%s:%d' % (launch_file.name, call.lineno))
                bindings.append(Binding(
                    params_file=resolved,
                    package=_const_str(kwargs.get('package')),
                    executable=_const_str(kwargs.get('executable')),
                    declared_name=declared_name,
                    origin='%s:%d' % (launch_file.name, call.lineno)))
    return bindings, unresolved, namespaced


# ---------------------------------------------------------------------------
# Discovery: shell scripts
# ---------------------------------------------------------------------------

#: scripts/start.sh:21 sets P to the workspace root.
SHELL_ROOT_VARS = ('$P/', '${P}/')

_ROS2_RUN = re.compile(r'\bros2\s+run\s+(\S+)\s+(\S+)')
_PARAMS_FILE = re.compile(r'--params-file[= ]\s*(\S+)')
_NODE_REMAP = re.compile(r'(?:-r|--remap)\s+__node:=(\S+)')


def _shell_bindings():
    """Every ``ros2 run ... --params-file ...`` invocation in scripts/.

    ``scripts/start.sh`` is not a toy: it is the documented way to bring the
    fleet up by hand, and it is the entry point where ``orchestrator_params.yaml``
    was applying correctly the whole time the launch path was ignoring it. A
    check that looked only at launch files would have concluded the file was
    fine.
    """
    bindings = []
    unresolved = []
    for script in sorted((REPO / 'scripts').glob('*.sh')):
        # Join backslash continuations first: a `ros2 run` invocation in this
        # repository is routinely spread over four or five lines, and the
        # --params-file argument is never on the same physical line as the
        # executable name.
        joined = re.sub(r'\\\n\s*', ' ', script.read_text(encoding='utf-8'))
        for line in joined.splitlines():
            if '--params-file' not in line or line.lstrip().startswith('#'):
                continue
            run = _ROS2_RUN.search(line)
            if run is None:
                unresolved.append('%s: --params-file outside a `ros2 run`'
                                  % (script.name,))
                continue
            remap = _NODE_REMAP.search(line)
            for raw in _PARAMS_FILE.findall(line):
                path = None
                for prefix in SHELL_ROOT_VARS:
                    if raw.startswith(prefix):
                        path = REPO / raw[len(prefix):]
                        break
                if path is None:
                    unresolved.append(
                        '%s: --params-file %r is not rooted at $P, so this '
                        'test cannot tell which file it means' % (script.name, raw))
                    continue
                bindings.append(Binding(
                    params_file=path,
                    package=run.group(1),
                    executable=run.group(2),
                    declared_name=(remap.group(1) if remap
                                   else NODE_DEFAULT_NAME),
                    origin=script.name))
    return bindings, unresolved


# ---------------------------------------------------------------------------
# The node behind an executable
# ---------------------------------------------------------------------------

_CONSOLE_SCRIPT = re.compile(r'^\s*([A-Za-z_]\w*)\s*=\s*([\w.]+):\w+\s*$')


def _console_scripts(package):
    """``{executable: module}`` from a package's setup.py entry points.

    Read from setup.py rather than assumed to equal the module name, so that
    renaming an executable moves this check with it instead of silently
    unhooking it.
    """
    setup_py = REPO / package / 'setup.py'
    if not setup_py.is_file():
        return {}
    tree = ast.parse(setup_py.read_text(encoding='utf-8'))
    found = {}
    for node in ast.walk(tree):
        text = _const_str(node) if isinstance(node, ast.Constant) else None
        if text is None:
            continue
        match = _CONSOLE_SCRIPT.match(text)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _module_path(module):
    parts = module.split('.')
    return REPO.joinpath(parts[0], *parts).with_suffix('.py')


def _node_source(binding):
    """The source file of the node an executable starts, or None."""
    if not binding.package or not binding.executable:
        return None
    module = _console_scripts(binding.package).get(binding.executable)
    if module is None:
        return None
    path = _module_path(module)
    return path if path.is_file() else None


def _self_name(source):
    """The name a node gives itself: ``super().__init__('<name>')``."""
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != '__init__':
            continue
        inner = func.value
        if not (isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == 'super'):
            continue
        text = _const_str(node.args[0]) if node.args else None
        if text is not None:
            names.add(text)
    return names


def _declared_parameters(source):
    tree = ast.parse(source.read_text(encoding='utf-8'))
    declared = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != 'declare_parameter':
            continue
        text = _const_str(node.args[0]) if node.args else None
        if text is not None:
            declared.add(text)
    return declared


def _runtime_names(binding, source):
    """Names the node may run under, as a set, or None when unresolvable."""
    if binding.declared_name is DYNAMIC_NAME:
        return set()
    if binding.declared_name is not NODE_DEFAULT_NAME:
        return {binding.declared_name}
    if source is None:
        return None
    return _self_name(source)


def _relative(path):
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:                          # outside the repo
        return str(path)


def _all_bindings():
    launch, launch_unresolved, namespaced = _launch_bindings()
    shell, shell_unresolved = _shell_bindings()
    return (launch + shell, launch_unresolved + shell_unresolved, namespaced)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_every_params_file_binding_is_resolvable():
    """No pairing may be skipped silently.

    If a launch file or script grows a construct this test cannot read, the
    right answer is to teach it the construct — not to let a parameter file
    drop out of every check below while still sitting on disk looking like
    configuration.
    """
    _bindings, unresolved, _namespaced = _all_bindings()
    assert not unresolved, (
        'these parameter-file bindings could not be resolved statically, so '
        'nothing below checked them: ' + '; '.join(sorted(unresolved)))


def test_known_params_files_are_still_loaded():
    bindings, _unresolved, _namespaced = _all_bindings()
    seen = {(_relative(b.params_file), b.package, b.executable)
            for b in bindings}
    missing = REQUIRED_PAIRINGS - seen
    assert not missing, (
        'a parameter file that used to be loaded is not loaded by anything any '
        'more: ' + '; '.join(sorted(map(str, missing)))
        + '. An unloaded params file is checked by nothing here and configures '
          'nothing at runtime, which is deviation D-12 with the file moved '
          'instead of the name.')


def test_no_namespaced_nodes_take_params_files():
    """Namespaces are not modelled, and guessing would be worse than failing.

    A node launched into a namespace needs that namespace in the parameter
    file's key. Nothing in this repository sets one today; the moment something
    does, this fails and the resolver has to learn about it rather than pass a
    check it is no longer entitled to make.
    """
    _bindings, _unresolved, namespaced = _all_bindings()
    assert not namespaced, (
        'Node actions with both namespace= and a parameter file: '
        + ', '.join(sorted(namespaced))
        + '. Teach _runtime_names about namespaces before shipping this.')


def test_params_file_key_matches_the_runtime_node_name():
    """Deviation D-12. The check that would have caught it.

    Fails if a file's top-level key is neither ``/**`` nor the name the node
    actually runs under — which is precisely the state this repository shipped
    in for four phases, silently, on the launch path only.
    """
    bindings, _unresolved, _namespaced = _all_bindings()
    assert bindings, 'no parameter-file bindings found at all — has the layout moved?'

    problems = []
    for binding in bindings:
        relative = _relative(binding.params_file)
        if not binding.params_file.is_file():
            problems.append('%s loads %s, which does not exist'
                            % (binding.origin, relative))
            continue
        source = _node_source(binding)
        names = _runtime_names(binding, source)
        if names is None:
            problems.append(
                '%s: cannot resolve a runtime name for executable %r of '
                'package %r (no console script?)'
                % (binding.origin, binding.executable, binding.package))
            continue
        if len(names) > 1:
            problems.append(
                '%s: %s declares more than one node name %s, so which one this '
                'file matches is ambiguous'
                % (binding.origin, _relative(source), sorted(names)))
            continue

        document = yaml.safe_load(binding.params_file.read_text(encoding='utf-8'))
        assert isinstance(document, dict), (
            '%s is not a mapping at its top level' % (relative,))
        acceptable = {WILDCARD} | names
        for key in document:
            if key in acceptable:
                continue
            if not names:
                problems.append(
                    '%s loads %s, whose top-level key is %r, but its name= is '
                    'built from substitutions and is not knowable statically. '
                    'A params file for such a node must be keyed %r.'
                    % (binding.origin, relative, key, WILDCARD))
            else:
                problems.append(
                    '%s loads %s, whose top-level key is %r, but the node runs '
                    'as %r. ROS 2 matches a parameter file on the RUNTIME name, '
                    'so this file is loaded and then applies nothing: every '
                    'value silently reverts to its declare_parameter default. '
                    'Key it %r or %r.'
                    % (binding.origin, relative, key, sorted(names)[0],
                       sorted(names)[0], WILDCARD))
    assert not problems, '\n'.join(problems)


def test_every_params_file_key_is_declared_by_the_node_that_loads_it():
    """Deviation D-13. The check that would have caught it.

    Three ``bid_weight_*`` keys sat in the orchestrator's file, which only the
    orchestrator loads, and the orchestrator declares none of them. ROS 2 drops
    an undeclared override without a word, so the numbers were decoration.
    """
    bindings, _unresolved, _namespaced = _all_bindings()
    problems = []
    for binding in bindings:
        source = _node_source(binding)
        if source is None or not binding.params_file.is_file():
            continue                    # reported by the test above
        declared = _declared_parameters(source)
        assert declared, ('no declare_parameter calls found in %s — has it moved?'
                          % (_relative(source),))
        document = yaml.safe_load(binding.params_file.read_text(encoding='utf-8'))
        for key, block in (document or {}).items():
            values = (block or {}).get('ros__parameters') or {}
            for name in values:
                # A dotted name addresses a nested parameter; only the head is
                # what declare_parameter names.
                head = name.split('.', 1)[0]
                if head not in declared:
                    problems.append(
                        '%s: %s sets %r under %r, but %s never declares it. '
                        'ROS 2 drops an undeclared override silently, so this '
                        'line configures nothing — the operator gets no '
                        'warning, no error and no log line.'
                        % (binding.origin, _relative(binding.params_file),
                           name, key, _relative(source)))
    assert not problems, '\n'.join(problems)


def test_the_bid_weights_are_not_back_in_the_orchestrator_file():
    """Named separately from the generic check, so the failure says why.

    A count of undeclared keys does not tell the next reader that bidding is
    scored on the agent. This one does.
    """
    document = yaml.safe_load(
        (REPO / 'selene_orchestrator' / 'config' / 'orchestrator_params.yaml')
        .read_text(encoding='utf-8'))
    values = document['orchestrator_node']['ros__parameters']
    strays = sorted(k for k in values if k.startswith('bid_weight_'))
    assert not strays, (
        'bid weight(s) %s are back in orchestrator_params.yaml. Bidding is '
        'scored on the agent (selene_agent/agent_node.py:629-641) from '
        'parameters the agent declares (:114-116); the orchestrator declares '
        'none of them, so a weight set here is dropped as an undeclared '
        'override and changes no bid anywhere. Set them in '
        'selene_agent/launch/agent.launch.py instead.' % (strays,))


def _agent_launch_parameter_dict():
    """``{name: ast node}`` for every key in agent.launch.py's parameter dict."""
    launch_file = REPO / 'selene_agent' / 'launch' / 'agent.launch.py'
    tree = ast.parse(launch_file.read_text(encoding='utf-8'))
    assigns = _assignments(tree)

    passed = {}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _callee(call) != 'Node':
            continue
        parameters = _kwargs(call).get('parameters')
        if isinstance(parameters, ast.Name):
            parameters = assigns.get(parameters.id, parameters)
        if not isinstance(parameters, ast.List):
            continue
        for element in parameters.elts:
            if not isinstance(element, ast.Dict):
                continue
            for key, value in zip(element.keys, element.values):
                name = _const_str(key)
                if name is not None:
                    passed[name] = value
    return passed


def test_the_recharge_threshold_is_not_back_in_the_orchestrator():
    """Deviation D-19, and the mirror of the bid-weight check below.

    `recharge_threshold` was declared by the orchestrator and read by nothing,
    while the agent — which is what actually drives to the charging station —
    recharged after every task with no battery test on that path at all. The
    parameter belongs to the node that can act on it.

    Checks BOTH halves, because either alone would let the defect back: the
    orchestrator must not declare it (a declaration is what makes the yaml key
    look supported), and the yaml file must not set it (a key nothing declares
    is dropped silently, which is D-13).
    """
    orchestrator = REPO / 'selene_orchestrator' / 'selene_orchestrator' \
        / 'orchestrator_node.py'
    declared = _declared_parameters(orchestrator)
    assert 'recharge_threshold' not in declared, (
        'orchestrator_node.py declares recharge_threshold again. The '
        'orchestrator cannot act on a battery threshold: the recharge '
        'decision is made on the robot, in '
        'selene_agent/agent_node.py _recharge_reason(). Declaring it here '
        'puts it back on test_no_orphan_parameters.py\'s allow-list, which is '
        'where it sat unread for four phases (D-19).')

    document = yaml.safe_load(
        (REPO / 'selene_orchestrator' / 'config' / 'orchestrator_params.yaml')
        .read_text(encoding='utf-8'))
    values = document['orchestrator_node']['ros__parameters']
    assert 'recharge_threshold' not in values, (
        'recharge_threshold is back in orchestrator_params.yaml. Set it in '
        'selene_agent/launch/agent.launch.py instead — that is the parameter '
        'dict the node that reads it is actually handed.')


def test_the_agent_receives_the_recharge_threshold_it_charges_by():
    """The other half of D-19: the floor must reach the node that reads it.

    Deleting it from the orchestrator would close the orphan and leave the
    fleet with an unconfigurable recharge policy — correct, and useless to an
    operator. This asserts it is in the dict every agent is handed, that the
    agent declares it, and that it is a float (agent_node.py declares it as a
    double; an int override raises ParameterTypeException at node start).

    The VALUE is asserted too, unlike the bid weights: 0.30 is the number
    orchestrator_params.yaml carried, and D-19's claim is that the move
    changed which node reads the parameter and nothing else.
    """
    passed = _agent_launch_parameter_dict()
    declared = _declared_parameters(
        REPO / 'selene_agent' / 'selene_agent' / 'agent_node.py')

    assert 'recharge_threshold' in declared, (
        'agent_node.py no longer declares recharge_threshold, so the recharge '
        'floor is a hardcoded constant again.')
    assert 'recharge_threshold' in passed, (
        'agent.launch.py does not pass recharge_threshold. The agent declares '
        'it, so it silently falls back to the node default and the operator '
        'has no way to change it — which is exactly how D-13 hid for four '
        'phases.')
    value = passed['recharge_threshold']
    assert isinstance(value, ast.Constant) and isinstance(value.value, float), (
        'recharge_threshold is passed as %s, not a float literal. '
        'agent_node.py declares it as a double; an int or a string override '
        'raises ParameterTypeException at node start.' % (ast.dump(value),))
    assert value.value == 0.30, (
        'recharge_threshold is %r; it was 0.30 in orchestrator_params.yaml '
        'before D-19 moved it, and the move was meant to be '
        'value-preserving. Changing it is fine — update this assertion and '
        'say so in the register.' % (value.value,))
    """The other half of D-13: the weights must reach the node that reads them.

    Deleting them from the orchestrator's file would close the defect and leave
    the fleet with no configured weights at all — correct, and useless to an
    operator. This asserts they are in the parameter dict every agent is handed,
    that all three are there, and that they are floats: agent_node.py declares
    them as doubles, and an int or a string override raises
    ParameterTypeException at node start rather than being coerced.
    """
    launch_file = REPO / 'selene_agent' / 'launch' / 'agent.launch.py'
    tree = ast.parse(launch_file.read_text(encoding='utf-8'))
    assigns = _assignments(tree)

    passed = {}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _callee(call) != 'Node':
            continue
        parameters = _kwargs(call).get('parameters')
        if isinstance(parameters, ast.Name):
            parameters = assigns.get(parameters.id, parameters)
        if not isinstance(parameters, ast.List):
            continue
        for element in parameters.elts:
            if not isinstance(element, ast.Dict):
                continue
            for key, value in zip(element.keys, element.values):
                name = _const_str(key)
                if name is not None and name.startswith('bid_weight_'):
                    passed[name] = value

    declared = _declared_parameters(
        REPO / 'selene_agent' / 'selene_agent' / 'agent_node.py')
    expected = {n for n in declared if n.startswith('bid_weight_')}
    assert expected, 'agent_node.py declares no bid_weight_* parameters at all'
    assert set(passed) == expected, (
        'agent.launch.py passes %s but the agent scores bids with %s. A weight '
        'the agent declares and the launch does not pass falls back to the '
        'hardcoded default, which is how D-13 hid for four phases.'
        % (sorted(passed), sorted(expected)))
    for name, value in sorted(passed.items()):
        assert isinstance(value, ast.Constant) and isinstance(value.value, float), (
            '%s is passed as %s, not a float literal. agent_node.py declares it '
            'as a double; an int or a string override raises '
            'ParameterTypeException at node start.'
            % (name, ast.dump(value)))
