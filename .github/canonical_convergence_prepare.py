import collections
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PINS = {
    'main': '345c0f7daf1da2152d0e554cc8733381ca5a1e9e',
    'stack': '1d9329d8c08cc96ded90f8580017275267a6225f',
    'kb': '1a79f590579422de28c6e5ff7997a3b1d9beb18e',
}
BRANCHES = {'main': 'main', 'stack': 'security/issue-20-report-evidence-boundary',
            'kb': 'research/kb-reference-metadata-gate-20261021'}
EXPECTED_PARENT = '200b55aca7ba5e37fd3e86b508f16ac2ac5303cf'
ROOT = Path.cwd()
OUT = Path(os.environ['RUNNER_TEMP']) / 'canonical-prepared'
OUT.mkdir()
INVENTORY = Path(os.environ['RUNNER_TEMP']) / 'canonical-inventory'
ENV = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN', 'GIT_EXTERNAL_DIFF')}
ENV.update(GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')
BUDGET = 'config/operations/module-budget.json'
ZIP_SOURCE = 'scripts/zip_safety.py'
TEST = 'apps/api/tests/test_zip_structural_names.py'
DOC = 'docs/operations/CANONICAL_CONVERGENCE.md'
INVENTORY_DOC = 'docs/operations/CANONICAL_BRANCH_INVENTORY.json'
PUBLICATIONS = [BUDGET, ZIP_SOURCE, TEST, DOC, INVENTORY_DOC, 'SOURCE_MANIFEST.json', 'PACKAGE_BUILD.json']

def git(*args, codes=(0,)):
    result = subprocess.run(['git', '--no-replace-objects', *args], env=ENV,
                            capture_output=True, timeout=120, check=False)
    if result.returncode not in codes:
        raise RuntimeError(f'git {args[0]} exited {result.returncode}: {result.stderr[:1000]!r}')
    return result.stdout

def text(*args):
    return git(*args).decode('utf-8').strip()

def load_at(role, path):
    return json.loads(git('show', PINS[role] + ':' + path))

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

assert text('rev-parse', 'HEAD') == os.environ['GITHUB_SHA']
assert text('rev-parse', 'HEAD^') == EXPECTED_PARENT
for role, branch in BRANCHES.items():
    assert text('rev-parse', 'refs/remotes/origin/' + branch) == PINS[role], f'Source drift: {role}'
for filename, digest in json.loads((INVENTORY / 'SHA256.json').read_bytes()).items():
    assert Path(filename).name == filename
    assert hashlib.sha256((INVENTORY / filename).read_bytes()).hexdigest() == digest
inventory = json.loads((INVENTORY / 'inventory.json').read_bytes())
assert inventory['pins'] == PINS and inventory['run_id'] == '39589417052'
assert inventory['counts'] == {'AHEAD': 6, 'AUDIT_ONLY': 1, 'DIVERGED': 7, 'IN_MAIN': 25, 'MAIN': 1}
git('checkout', '--detach', PINS['stack'])
assert not text('status', '--porcelain')
(ROOT / 'var').mkdir(exist_ok=True)

# A genuine three-way source union: refuse all overlapping source edits.
conflicts = {BUDGET, 'SOURCE_MANIFEST.json', 'PACKAGE_BUILD.json'}
def changed(role):
    return {p.decode() for p in git('diff', '--name-only', '-z', PINS['main'], PINS[role]).split(b'\0') if p}
stack_changes, kb_changes = changed('stack'), changed('kb')
assert stack_changes & kb_changes == conflicts
assert len(stack_changes) == 21 and len(kb_changes) == 12
for path in sorted(kb_changes - conflicts):
    mode, kind, blob = git('ls-tree', PINS['kb'], '--', path).split(b'\t', 1)[0].decode().split()
    assert mode == '100644' and kind == 'blob'
    target = ROOT / path
    assert not target.exists(), 'Unexpected overlapping KB path: ' + path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(git('show', PINS['kb'] + ':' + path))

# Preserve every historic entry and every current module ceiling from both lanes.
base, left, right = (load_at(role, BUDGET) for role in ('main', 'stack', 'kb'))
merged = copy.deepcopy(left)
missing = object()
for path in sorted(set(base['modules']) | set(left['modules']) | set(right['modules'])):
    b, l, r = (x['modules'].get(path, missing) for x in (base, left, right))
    value = l if l == r or r == b else r if l == b else missing
    assert value is not missing, 'Conflicting module budget: ' + path
    merged['modules'][path] = value

def key(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True)
for field in ('raised', 'lowered'):
    original = collections.Counter(map(key, base[field]))
    lc, rc = (collections.Counter(map(key, x[field])) for x in (left, right))
    assert not (original - lc) and not (original - rc), 'Deleted historic budget record'
    for lane in (left, right):
        iterator = iter(map(key, lane[field]))
        assert all(any(v == expected for v in iterator) for expected in map(key, base[field]))
    needed = rc - lc
    for record in right[field]:
        token = key(record)
        if needed[token] > 0:
            merged[field].append(record)
            needed[token] -= 1
    assert not +needed
for field in set(base) - {'modules', 'raised', 'lowered'}:
    assert base[field] == left[field] == right[field], 'Unreviewed budget metadata conflict'
assert merged['modules'][ZIP_SOURCE] == base['modules'][ZIP_SOURCE]
assert {p for p in merged['modules'] if merged['modules'][p] != left['modules'].get(p)} == {'scripts/kb_reference_admission.py'}
write_json(ROOT / BUDGET, merged)
merged_budget_bytes = (ROOT / BUDGET).read_bytes()

TEST_SOURCE = '''"""Offline ZIP metadata namespace invariants; never extract archive payloads."""
from __future__ import annotations

import zipfile

import pytest

from scripts.zip_safety import _canonical_name, _record_entry, _structural_collision_failures


def _failures(names: tuple[str, ...]) -> list[str]:
    exact: set[str] = set()
    folded: dict[str, str] = {}
    files: set[str] = set()
    directories: set[str] = set()
    failures: list[str] = []
    for name in names:
        failures.extend(_record_entry(zipfile.ZipInfo(name), exact, folded, files, directories))
    return failures + _structural_collision_failures(files, directories)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("names", [
    ("foo.", "foo/bar.txt"), ("FOO", "foo/bar.txt"),
    ("foo?", "foo_/bar.txt"), ("parent./child", "parent/child/deep.txt"),
    ("reports /leaf", "reports/leaf/deep.txt"),
    ("foo.", "foo/bar/"), ("foo", "foo/bar/"),
    ("foo?", "foo_/bar/"), ("UPPER", "upper/deep/"),
])
def test_normalized_file_prefixes_are_refused(names: tuple[str, ...], reverse: bool) -> None:
    result = _failures(tuple(reversed(names)) if reverse else names)
    assert any("prefix collision" in failure for failure in result)


@pytest.mark.parametrize("names", [("foo.", "foo/"), ("FOO", "foo/"), ("foo?", "foo_/" )])
def test_normalized_file_directory_aliases_are_refused(names: tuple[str, ...]) -> None:
    assert _failures(names)


@pytest.mark.parametrize("component", ["", ".", "..", ". ", " ... ", "   "])
def test_empty_normalized_components_remain_refused(component: str) -> None:
    canonical, failure = _canonical_name("root/" + component + "/leaf")
    assert canonical is None and failure is not None


@pytest.mark.parametrize("names", [
    ("tree/", "tree/a.txt", "tree/b.txt"), ("tree/branch/", "other.txt"),
    ("one.txt", "two.txt"), ("unicode/", "unicode/caf\\u00e9.txt"),
    ("dir with spaces/a.txt", "dir with spaces/b.txt"),
])
def test_distinct_safe_names_remain_admissible(names: tuple[str, ...]) -> None:
    assert _failures(names) == []
'''
assert not (ROOT / TEST).exists()
(ROOT / TEST).write_text(TEST_SOURCE, encoding='utf-8')
subprocess.run([sys.executable, '-m', 'ruff', 'format', TEST], env=ENV, check=True, timeout=60)

def run_tests(paths, label, require_success):
    destination = OUT / (label + '.xml')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', *paths,
                             '-p', 'no:cacheprovider', '--tb=short', '--junitxml=' + str(destination)],
                            env=ENV, capture_output=True, text=True, check=False, timeout=600)
    (OUT / (label + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
    totals = {x: 0 for x in ('tests', 'failures', 'errors', 'skipped')}
    for suite in ET.parse(destination).getroot().iter('testsuite'):
        for field in totals:
            totals[field] += int(suite.get(field, '0'))
    print(label, totals, 'exit', result.returncode, flush=True)
    assert totals['tests'] > 0 and totals['errors'] == totals['skipped'] == 0
    if require_success:
        if result.returncode:
            print(result.stdout[-12000:] + result.stderr[-2000:], flush=True)
        assert result.returncode == 0 and totals['failures'] == 0
    else:
        assert result.returncode == 1 and totals['failures'] > 0
    return totals

baseline = run_tests([TEST], 'baseline-structural', False)
source = ROOT / ZIP_SOURCE
original = source.read_text(encoding='utf-8')
replacements = [
    ('if set(parts) & {"", ".", ".."} or any(not part.rstrip(" .") for part in parts):',
     'if "" in {part.rstrip(" .") for part in parts}:'),
    ('(dir_paths if info.is_dir() else file_paths).add(normalized_path)',
     '(dir_paths if info.is_dir() else file_paths).add(alias_key)'),
    ('for path in sorted(file_paths):', 'for path in sorted(file_paths | dir_paths):'),
]
repaired = original
for old, new in replacements:
    assert repaired.count(old) == 1
    repaired = repaired.replace(old, new)
source.write_text(repaired, encoding='utf-8')
subprocess.run([sys.executable, '-m', 'ruff', 'format', ZIP_SOURCE], env=ENV, check=True, timeout=60)
repaired = source.read_text(encoding='utf-8')
focused = run_tests([TEST], 'repaired-structural', True)

# Named, offline perturbations of the three defensive predicates.
mutations = {
    'raw-structural-namespace': (replacements[1][1], replacements[1][0]),
    'directory-prefixes-omitted': (replacements[2][1], replacements[2][0]),
    'empty-component-trimming-omitted': (replacements[0][1], 'if set(parts) & {"", ".", ".."}:'),
}
controls = {}
try:
    for label, (good, bad) in mutations.items():
        assert repaired.count(good) == 1
        source.write_text(repaired.replace(good, bad), encoding='utf-8')
        controls[label] = run_tests([TEST], label, False)
finally:
    source.write_text(repaired, encoding='utf-8')
assert run_tests([TEST], 'restored-structural', True) == focused

# Traceable inventory is data, not operational/runtime evidence or merge authority.
fields = ('branch', 'sha', 'tree', 'ahead', 'behind', 'classification', 'included_in_main', 'contained_in_heads')
branch_record = {'schema': 'korpus.canonical-branch-inventory.v1',
                 'inventory_run': 39589417052, 'inventory_archive_sha256': '98c2c1e69a696a83d736b1a97a4c2c3d6937e65f5fbb7284f1a4981c7875b3ee',
                 'source_pins': PINS, 'observed_counts': inventory['counts'],
                 'branches': [{f: row[f] for f in fields} for row in inventory['branches']],
                 'deletion_authorized': False, 'merge_authorized': False, 'production_authorized': False}
write_json(ROOT / INVENTORY_DOC, branch_record)
rows = [row for row in inventory['branches'] if row['classification'] == 'DIVERGED']
legacy = '\n'.join(f"| `{r['branch']}` | `{r['sha']}` | {r['ahead']} / {r['behind']} | retain; semantic disposition pending |" for r in rows)
document = '''# Canonical convergence candidate (issue #89)

## Status and boundaries

This is a staged integration candidate, not an admitted main merge or production release.
It combines the pinned package/pilot/distribution stack and metadata-only validator.
No source material is fetched or indexed; no model, runtime, service or deployment is activated.
The existing main admission governance (#72), independent review and exact-head checks remain required.
The older SHA-specific PR #88 automatic merge pin is not changed by this candidate.

## Exact provenance

- Main: `''' + PINS['main'] + '''`.
- Package stack (#82/#84/#85/#86/#87): `''' + PINS['stack'] + '''`.
- Metadata validator (#88): `''' + PINS['kb'] + '''`.
- Branch graph evidence: GitHub run 39589417052, artifact 12341126308.
- Original branches: 39 = main + 25 already in main + 6 ahead + 7 diverged.
- The isolated audit/integration branch adds one observed branch; it is not hidden in the count.

The two source deltas overlap only in module-budget and source/package identity files.
Module budgets use a checked three-way union, preserving all source entries and historical reasons;
conflicting module edits fail rather than selecting a permissive maximum. Generated identities are
rebuilt from the actual combined staged source. Unchanged files retain their exact original Git blobs.
Temporary audit/producer workflows must not appear in the final candidate tree.

## Defensive corrections during integration

The package stack's existing complexity ceiling is restored without raising a budget:
normalized-empty path components use one set-membership predicate. Structural file/directory
sets use the same normalized namespace as alias detection. Prefix checks include explicit
nested directory entries as well as files. New tests operate only on inert ZipInfo metadata;
they never extract archive data or probe a remote target. They preserve ordinary distinct paths.

A passing focused suite is not a substitute for full PostgreSQL/API/web/research/contract CI.
Mutation controls substantiate named finite properties, not universal exploit resistance.
Existing warnings, conditional test skips, release-signing obligations and any uncovered behavior
must remain visible rather than being relabelled as solved.

## Branch disposition

Twenty-five branch tips are already ancestors of main and require no repeated merge.
The package stack ancestry is represented once; do not independently merge its component PRs
and the same aggregate. The standalone audit/pr85-empty-component-fix-20261021 tip is retained
until its auxiliary history is reconciled. The seven divergent tips are not blindly imported:

| Branch | Exact observed head | Ahead / behind main | Disposition |
| --- | --- | --- | --- |
''' + legacy + '''

The complete machine-readable snapshot is CANONICAL_BRANCH_INVENTORY.json beside this document.
Containment and patch identity are not semantic approval, deletion authority or production evidence.
No branch, tag, issue or existing PR is silently deleted/closed by this candidate.

## Operator validation

Use the repository's locked development environment and original CI commands.
From the repository root, `python scripts/kb_reference_admission.py` validates only the
18 reference metadata records. Its indexable/acquired counts remain zero and production
remains unauthorized. Package tooling retains the no-history and evidence-boundary policies;
do not interpret a self-consistent package hash as publisher authenticity or deployment approval.

Before main admission, re-read the candidate HEAD, main base, actual merge-candidate execution
receipts, all required CI jobs, and independent code AND security findings. Require real
server-side main protection and a genuine negative-control refusal record under #72.
No direct main write, force-push, permission bypass or automatic repinning is permitted.
A future rollback is a reviewed tested revert PR, not history rewriting or removal of gates.
'''
(ROOT / DOC).write_text(document, encoding='utf-8')
git('add', '--', *(sorted(kb_changes - conflicts) + PUBLICATIONS[:-2]))
from scripts.generate_manifest import write_manifest
from scripts.verify_source_manifest import verify as verify_manifest
from scripts.verify_package_build_identity import verify as verify_package
manifest = write_manifest(ROOT, ROOT / 'SOURCE_MANIFEST.json', kind='source')
package = load_at('stack', 'PACKAGE_BUILD.json')
package['source_manifest_root_sha256'] = manifest['root_sha256']
write_json(ROOT / 'PACKAGE_BUILD.json', package)
git('add', '--', 'SOURCE_MANIFEST.json', 'PACKAGE_BUILD.json')
assert verify_manifest(ROOT)['valid'] is True and verify_package(ROOT) == []
assert (ROOT / BUDGET).read_bytes() == merged_budget_bytes
assert not any(p.startswith('.github/') for p in text('diff', '--name-only', PINS['stack']).splitlines())

patterns = ['test_kb_reference_*.py', 'test_*budget*.py', 'test_package_*.py',
            'test_snapshot_admission.py', 'test_distribution_runtime_boundary.py',
            'test_manifest_generation.py', 'test_pilot_runtime_units.py', 'test_zip_structural_names.py']
selected = sorted({str(p.relative_to(ROOT)) for pattern in patterns for p in (ROOT / 'apps/api/tests').glob(pattern)})
selected.append('apps/api/tests/test_gate_parity.py::test_every_module_is_in_the_budget')
all_focused = run_tests(selected, 'combined-focused', True)
quality = [
    [sys.executable, '-m', 'ruff', 'check', ZIP_SOURCE, TEST],
    [sys.executable, '-m', 'ruff', 'format', '--check', ZIP_SOURCE, TEST],
    [sys.executable, '-m', 'mypy', ZIP_SOURCE],
    [sys.executable, 'scripts/check_module_budget.py'],
    [sys.executable, 'scripts/check_budget_raises_are_named.py', '--base', PINS['main']],
    [sys.executable, 'scripts/verify_source_manifest.py'],
    [sys.executable, 'scripts/verify_package_build_identity.py'],
    ['git', 'diff', '--check', PINS['stack']],
]
for index, command in enumerate(quality):
    run = subprocess.run(command, env=ENV, capture_output=True, text=True, check=False, timeout=180)
    (OUT / f'quality-{index}.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    print('quality', index, run.returncode, flush=True)
    if run.returncode:
        print(run.stdout[-12000:] + run.stderr[-2000:], flush=True)
    assert run.returncode == 0
assert verify_manifest(ROOT)['valid'] is True and verify_package(ROOT) == []
assert (ROOT / BUDGET).read_bytes() == merged_budget_bytes
changed_paths = text('diff', '--name-only', PINS['stack']).splitlines()
assert set(changed_paths) == (kb_changes - conflicts) | set(PUBLICATIONS)
git('add', '--', *changed_paths)
expected_tree = text('write-tree')
entries = []
for path in changed_paths:
    meta = git('ls-files', '-s', '--', path).split(b'\t', 1)[0].decode().split()
    mode, blob, stage = meta
    data = (ROOT / path).read_bytes()
    # Preserve the sole inherited executable; every other prepared path is regular data.
    assert stage == '0' and mode == ('100755' if path == ZIP_SOURCE else '100644')
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == blob
    entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': blob,
                    'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                    'publication_required': path in PUBLICATIONS})
    if path in PUBLICATIONS:
        target = OUT / 'payload' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
receipt = {'schema': 'korpus.canonical-convergence-preparation.v1', 'status': 'TESTED_NOT_ADMITTED',
           'run_id': os.environ['GITHUB_RUN_ID'], 'request_head': os.environ['GITHUB_SHA'], 'pins': PINS,
           'baseline': baseline, 'repaired_structural': focused, 'regression_controls': controls,
           'combined_focused': all_focused, 'quality_commands': quality,
           'tree_sha': expected_tree, 'entries': entries, 'source_file_count': manifest['file_count'],
           'source_manifest_root_sha256': manifest['root_sha256'],
           'merge_authorized': False, 'production_authorized': False}
write_json(OUT / 'receipt.json', receipt)
print(json.dumps(receipt, ensure_ascii=True, sort_keys=True), flush=True)
