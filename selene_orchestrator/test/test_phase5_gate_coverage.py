"""The Phase 5 exit gate must not claim more coverage than it has — D-10.

WHY THIS TEST EXISTS
--------------------
Deviation D-10 (``docs/phase5_deviation_register.md``) is not "a check was
wrong". It is that ``scripts/validate_phase5.sh`` ran eight checks, passed 8/8,
and printed a report implying the Phase 5 exit gate had been met — while three of
the PRD's seven exit-gate rows had no check at all, three had liveness proxies
that the failure they described would also satisfy, and the footer asserting all
this was a hand-written paragraph that had already gone factually false about
FR-MAP-4.

Nothing connected the report to the checks. That is the defect this file closes,
and it is the same shape as D-09's: a declared thing with nothing behind it, and
no machine ever comparing the two. ``test_no_orphan_parameters.py`` is that test
for parameters; this is it for exit-gate coverage.

WHAT IS ASSERTED
----------------
1. The seven exit-gate rows in ``scripts/validate_phase5.sh``'s ``PRD_ROWS`` are
   byte-identical to the table in ``docs/PRD.md``, in the same order. Paraphrase
   the PRD in the script and this fails.
2. ``ROW_CHECKS``, ``NOT_COVERED_REASONS`` and ``ROW_COVERAGE_KIND`` are
   index-aligned with ``PRD_ROWS`` — every row has an explicit answer, a row
   answered ``none`` must carry a written reason, and every row must state what
   KIND of evidence its checks produce. That last one is the column the register
   table had and the first generated table dropped: a verdict of PASS with no
   qualifier beside a row whose PRD method was never performed is D-10 again at
   reduced amplitude.
3. Every check number the mapping names exists in ``CHECK_CATALOG``.
4. Every catalogued check is genuinely emitted — by a literal ``record_check
   <n>`` in the shell, or as a key of ``CHECK_TITLES`` in
   ``scripts/phase5_probe.py`` — and the catalogue's ``owner`` column says which.
5. No catalogued check is unmapped: it covers a PRD row, or it appears in
   ``EXTRA_CHECKS`` with a reason for being kept anyway.
6. The probe's own titles and the script's catalogue agree, so the report row and
   the code that produced it cannot describe different things.

DELIBERATE NON-ASSERTIONS. This test says nothing about whether a check is
*good*, and it cannot judge whether a row's ``ROW_COVERAGE_KIND`` sentence is
honest — only that one exists, that it commits to ``end-to-end``, ``proxy:`` or
``not covered``, and that it will not break the table it is printed into. A check
can be catalogued, mapped, correctly titled, labelled and still be a weak proxy —
which is exactly what the pre-D-10 gate was, and why the script's generated
footer also states in prose what a green run does and does not mean.

ROS-FREE BY CONSTRUCTION: this file imports nothing from ``selene_orchestrator``
and nothing from ROS. It lives under ``selene_orchestrator/test/`` only because
that is the directory the ROS-free gate lane collects.
"""

import ast
import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

GATE_SCRIPT = os.path.join(_REPO_ROOT, 'scripts', 'validate_phase5.sh')
PROBE_SCRIPT = os.path.join(_REPO_ROOT, 'scripts', 'phase5_probe.py')
PRD = os.path.join(_REPO_ROOT, 'docs', 'PRD.md')

#: Heading that opens the exit-gate table, and the line that closes the section.
PRD_SECTION_HEADING = '#### Phase 5 Exit Gate'
PRD_SECTION_END = '**Demo checkpoint:**'


def _read(path):
    if not os.path.isfile(path):
        pytest.skip('%s is not present in this checkout' % (path,))
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


def _bash_string_array(source, name):
    """Return the quoted elements of a multi-line bash array literal.

    Deliberately narrow: it only understands the exact shape the gate script
    uses (``NAME=(`` / one ``"..."`` per line / ``)``). A looser parser would
    quietly accept a mangled table, and a table nobody can trust is what this
    test exists to prevent.
    """
    match = re.search(r'^%s=\(\s*\n(.*?)^\)\s*$' % (re.escape(name),),
                      source, re.MULTILINE | re.DOTALL)
    assert match, ('%s is not defined as a multi-line array in %s'
                   % (name, os.path.basename(GATE_SCRIPT)))
    body = match.group(1)
    elements = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        quoted = re.fullmatch(r'"([^"]*)"', stripped)
        assert quoted, ('%s contains a line this test cannot parse: %r'
                        % (name, stripped))
        elements.append(quoted.group(1))
    return elements


def _prd_rows():
    """The exit-gate table's first column, verbatim, in document order."""
    text = _read(PRD)
    start = text.find(PRD_SECTION_HEADING)
    assert start >= 0, ('%r not found in docs/PRD.md; the gate script cites '
                        'that section by name' % (PRD_SECTION_HEADING,))
    end = text.find(PRD_SECTION_END, start)
    assert end > start, ('%r not found after the exit-gate heading, so the '
                         'section has no end to parse to' % (PRD_SECTION_END,))

    rows = []
    for line in text[start:end].splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if not cells or not cells[0]:
            continue
        if cells[0] == 'Check' or set(cells[0]) <= set('-: '):
            continue                      # header row and separator row
        rows.append(cells[0])
    return rows


def _catalog(source):
    """{number: (owner, title)} from CHECK_CATALOG."""
    catalog = {}
    for entry in _bash_string_array(source, 'CHECK_CATALOG'):
        parts = entry.split('|')
        assert len(parts) == 3, ('CHECK_CATALOG entries are number|owner|title; '
                                 'got %r' % (entry,))
        number, owner, title = parts
        assert number.isdigit(), 'CHECK_CATALOG number %r is not a number' % (
            number,)
        assert number not in catalog, 'check %s is catalogued twice' % (number,)
        catalog[number] = (owner, title)
    return catalog


def _probe_check_titles():
    """CHECK_TITLES out of scripts/phase5_probe.py, without importing it.

    ``ast`` rather than a regex, and evaluation rather than execution: the probe
    imports rclpy at call time and must never be imported by a test in the
    ROS-free lane.
    """
    tree = ast.parse(_read(PROBE_SCRIPT))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'CHECK_TITLES':
                return {str(k): v
                        for k, v in ast.literal_eval(node.value).items()}
    pytest.fail('CHECK_TITLES is not a module-level assignment in '
                'scripts/phase5_probe.py')


def _shell_emitted_checks(source):
    """Check numbers emitted by a literal ``record_check <n>`` in the script."""
    return set(re.findall(r'^\s*record_check\s+(\d+)\s', source, re.MULTILINE))


# --------------------------------------------------------------------------
# 1. The script quotes the PRD, it does not paraphrase it.
# --------------------------------------------------------------------------

def test_prd_rows_are_verbatim_and_in_order():
    script_rows = _bash_string_array(_read(GATE_SCRIPT), 'PRD_ROWS')
    prd_rows = _prd_rows()
    assert prd_rows, 'no exit-gate rows parsed out of docs/PRD.md'
    assert script_rows == prd_rows, (
        'validate_phase5.sh PRD_ROWS has drifted from the exit-gate table in '
        'docs/PRD.md.\n  script: %r\n  PRD:    %r' % (script_rows, prd_rows))


# --------------------------------------------------------------------------
# 2. Every row has an explicit answer, and "none" has to be justified.
# --------------------------------------------------------------------------

def test_every_prd_row_is_mapped():
    source = _read(GATE_SCRIPT)
    rows = _bash_string_array(source, 'PRD_ROWS')
    row_checks = _bash_string_array(source, 'ROW_CHECKS')
    reasons = _bash_string_array(source, 'NOT_COVERED_REASONS')

    assert len(row_checks) == len(rows), (
        'ROW_CHECKS has %d entries for %d PRD rows; they are index-aligned'
        % (len(row_checks), len(rows)))
    assert len(reasons) == len(rows), (
        'NOT_COVERED_REASONS has %d entries for %d PRD rows; they are '
        'index-aligned' % (len(reasons), len(rows)))

    for row, checks, reason in zip(rows, row_checks, reasons):
        assert checks.strip(), 'row %r has an empty ROW_CHECKS entry' % (row,)
        if checks.strip() == 'none':
            assert reason.strip(), (
                'row %r is mapped to "none" with no NOT_COVERED_REASONS entry. '
                'An unexplained gap in the gate is how D-10 happened.' % (row,))
        else:
            for number in checks.split():
                assert number.isdigit(), (
                    'row %r maps to %r, which is neither "none" nor a list of '
                    'check numbers' % (row, checks))


def test_every_prd_row_states_its_coverage_kind():
    """A verdict with no coverage qualifier is what this column exists to stop.

    The generated table prints Coverage beside Verdict. Rows 1, 2 and 5 are
    proxies — no browser runs, RViz2 is never launched, and check 10 recomputes
    the overlay with the same module the publisher used — and a bare PASS beside
    them reads as though the PRD's method had been performed. So every row must
    commit to one of two shapes, and "proxy:" must be followed by something.
    """
    source = _read(GATE_SCRIPT)
    rows = _bash_string_array(source, 'PRD_ROWS')
    row_checks = _bash_string_array(source, 'ROW_CHECKS')
    kinds = _bash_string_array(source, 'ROW_COVERAGE_KIND')

    assert len(kinds) == len(rows), (
        'ROW_COVERAGE_KIND has %d entries for %d PRD rows; they are '
        'index-aligned' % (len(kinds), len(rows)))

    for row, checks, kind in zip(rows, row_checks, kinds):
        assert kind.strip(), (
            'row %r has no ROW_COVERAGE_KIND entry, so the generated table '
            'would print a bare verdict for it. Say what the checks reach.'
            % (row,))
        assert '|' not in kind, (
            'ROW_COVERAGE_KIND for row %r contains a "|", which would split '
            'the markdown table cell it is printed into' % (row,))
        if checks.strip() == 'none':
            assert kind.strip().lower().startswith('not covered'), (
                'row %r is mapped to no checks, so its coverage kind must say '
                '"not covered"; got %r' % (row, kind))
            continue
        head = kind.split(':', 1)[0].strip().lower()
        assert head in ('end-to-end', 'proxy'), (
            'row %r must declare its coverage as "end-to-end" or "proxy: <what '
            'is and is not measured>"; got %r. There is deliberately no third, '
            'comfortable value.' % (row, kind))
        if head == 'proxy':
            assert kind.split(':', 1)[1].strip(), (
                'row %r is declared a proxy with nothing after the colon. Name '
                'the half that is not measured.' % (row,))


# --------------------------------------------------------------------------
# 3 and 4. The mapping names real checks, and every catalogued check is emitted.
# --------------------------------------------------------------------------

def test_mapped_checks_exist_in_the_catalog():
    source = _read(GATE_SCRIPT)
    catalog = _catalog(source)
    for checks in _bash_string_array(source, 'ROW_CHECKS'):
        if checks.strip() == 'none':
            continue
        for number in checks.split():
            assert number in catalog, (
                'ROW_CHECKS names check %s, which is not in CHECK_CATALOG. The '
                'footer would print a coverage claim for a check that does not '
                'exist.' % (number,))
    for entry in _bash_string_array(source, 'EXTRA_CHECKS'):
        number = entry.split('|', 1)[0]
        assert number in catalog, (
            'EXTRA_CHECKS names check %s, which is not in CHECK_CATALOG'
            % (number,))


def test_every_catalogued_check_is_actually_emitted():
    source = _read(GATE_SCRIPT)
    catalog = _catalog(source)
    shell_checks = _shell_emitted_checks(source)
    probe_titles = _probe_check_titles()

    emitted = shell_checks | set(probe_titles)
    assert set(catalog) == emitted, (
        'CHECK_CATALOG and the checks actually emitted disagree.\n'
        '  catalogued but never emitted: %s\n'
        '  emitted but not catalogued:   %s'
        % (sorted(set(catalog) - emitted, key=int),
           sorted(emitted - set(catalog), key=int)))

    for number, (owner, _title) in sorted(catalog.items(), key=lambda kv: int(kv[0])):
        if owner == 'shell':
            assert number in shell_checks, (
                'check %s is catalogued as shell-owned but no literal '
                '"record_check %s" appears in validate_phase5.sh'
                % (number, number))
            assert number not in probe_titles, (
                'check %s is catalogued as shell-owned but the probe also '
                'declares it' % (number,))
        elif owner == 'probe':
            assert number in probe_titles, (
                'check %s is catalogued as probe-owned but is not a key of '
                'CHECK_TITLES in scripts/phase5_probe.py' % (number,))
        else:
            pytest.fail('check %s has unknown owner %r; expected shell or '
                        'probe' % (number, owner))


def test_no_check_is_unmapped():
    source = _read(GATE_SCRIPT)
    catalog = _catalog(source)

    mapped = set()
    for checks in _bash_string_array(source, 'ROW_CHECKS'):
        if checks.strip() == 'none':
            continue
        mapped.update(checks.split())
    extras = {}
    for entry in _bash_string_array(source, 'EXTRA_CHECKS'):
        number, _sep, reason = entry.partition('|')
        assert reason.strip(), (
            'EXTRA_CHECKS entry for check %s has no reason. A check that covers '
            'no PRD row and explains nothing is exactly the padding a green '
            '8/8 was made of.' % (number,))
        extras[number] = reason

    unmapped = sorted(set(catalog) - mapped - set(extras), key=int)
    assert not unmapped, (
        'checks %s cover no PRD row and are not listed in EXTRA_CHECKS with a '
        'reason. Add them to a row or justify them; do not leave the report '
        'counting checks nobody can trace to a requirement.' % (unmapped,))

    overlap = sorted(mapped & set(extras), key=int)
    assert not overlap, (
        'checks %s are both mapped to a PRD row and listed as covering none'
        % (overlap,))


# --------------------------------------------------------------------------
# 6. The report row and the code that produced it describe the same thing.
# --------------------------------------------------------------------------

def test_probe_titles_match_the_catalog():
    catalog = _catalog(_read(GATE_SCRIPT))
    probe_titles = _probe_check_titles()
    mismatched = []
    for number, title in sorted(probe_titles.items(), key=lambda kv: int(kv[0])):
        catalogued = catalog.get(number)
        if catalogued is None:
            continue                      # covered by the emission test above
        if catalogued[1] != title:
            mismatched.append((number, catalogued[1], title))
    assert not mismatched, (
        'CHECK_CATALOG and the probe disagree about what a check is called, so '
        'the generated footer and the emitted row would name different things: '
        '%r' % (mismatched,))
