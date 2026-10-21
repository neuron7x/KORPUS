"""Prepare a bounded receipt-staging correction and residual disposition."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = 'c2abdb69edd273c53e3a7bb2344f1ffb3be2a158'
MAIN = '345c0f7daf1da2152d0e554cc8733381ca5a1e9e'
PARENT = '4cf7cef2f4f52bbfcd4db565b31f26e86f08e25b'
TEST_BLOB = 'fb70c3f6c7c75ef1a1e7c99793b6557de340d799'
ROOT = Path.cwd()
TEMP = Path(os.environ['RUNNER_TEMP'])
OUT = TEMP / 'residual-prepared'
OUT.mkdir()
ENV = {k: v for k, v in os.environ.items() if not k.startswith('GIT_') and k not in {'GH_TOKEN', 'GITHUB_TOKEN'}}
ENV.update(GIT_NO_REPLACE_OBJECTS='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0')
TEST = 'apps/api/tests/test_backend_report_staging.py'
DOC = 'docs/operations/CANONICAL_CONVERGENCE.md'
DISPOSITION = 'docs/operations/CANONICAL_BRANCH_DISPOSITION.json'
PATHS = ['Makefile', TEST, DOC, DISPOSITION, 'SOURCE_MANIFEST.json', 'PACKAGE_BUILD.json']

def git(*args):
    return subprocess.run(['/usr/bin/git', '--no-replace-objects', *args], env=ENV, capture_output=True, check=True, timeout=90).stdout

def text(*args):
    return git(*args).decode().strip()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def run(command, label):
    p = subprocess.run(command, env=ENV, capture_output=True, text=True, check=False, timeout=600)
    (OUT / (label + '.log')).write_text(p.stdout + p.stderr, encoding='utf-8')
    print(label, 'exit', p.returncode, flush=True)
    if p.returncode:
        print(p.stdout[-12000:] + p.stderr[-2000:], flush=True)
    return p.returncode

def suite(paths, label, good):
    destination = OUT / (label + '.xml')
    code = run([sys.executable, '-m', 'pytest', '-q', *paths, '-p', 'no:cacheprovider', '--tb=short', '--junitxml=' + str(destination)], label)
    xml = ET.parse(destination).getroot()
    counts = {k: sum(int(s.get(k, '0')) for s in xml.iter('testsuite')) for k in ('tests', 'failures', 'errors', 'skipped')}
    assert counts['tests'] == len(list(xml.iter('testcase'))) > 0
    assert counts['errors'] == counts['skipped'] == 0
    assert (code == 0 and counts['failures'] == 0) if good else (code == 1 and counts['failures'] > 0)
    print(label, counts, flush=True)
    return counts

assert text('rev-parse', 'HEAD') == os.environ['GITHUB_SHA']
assert text('rev-parse', 'HEAD^') == PARENT
assert text('rev-parse', 'refs/remotes/origin/main') == MAIN
assert text('hash-object', '.github/canonical_staging_cases.py') == TEST_BLOB
new_tests = (ROOT / '.github/canonical_staging_cases.py').read_bytes()
audit_root = TEMP / 'residual-audit'
for name, digest in json.loads((audit_root / 'SHA256.json').read_bytes()).items():
    path = Path(name)
    assert not path.is_absolute() and '..' not in path.parts
    assert hashlib.sha256((audit_root / path).read_bytes()).hexdigest() == digest
summary = json.loads((audit_root / 'summary.json').read_bytes())
assert summary['candidate'] == SOURCE and summary['main'] == MAIN
assert summary['run_id'] == '39629417088' and summary['request_head'] == PARENT
for branch in summary['branches']:
    assert text('rev-parse', 'refs/remotes/origin/' + branch['branch']).decode() if False else text('rev-parse', 'refs/remotes/origin/' + branch['branch']) == branch['head']
api_xml = ET.parse(TEMP / 'residual-api' / 'pytest.xml').getroot()
cases = list(api_xml.iter('testcase'))
assert len(cases) == 5652 and not any(c.find('failure') is not None or c.find('error') is not None for c in cases)
git('checkout', '--detach', SOURCE)
assert not text('status', '--porcelain')
(ROOT / 'var').mkdir(exist_ok=True)
assert not (ROOT / TEST).exists() and not (ROOT / DISPOSITION).exists()
(ROOT / TEST).write_bytes(new_tests)
assert run([sys.executable, '-m', 'ruff', 'format', TEST], 'format-test') == 0
baseline = suite([TEST], 'baseline-staging', False)
assert baseline == {'tests': 16, 'failures': 14, 'errors': 0, 'skipped': 0}
original = (ROOT / 'Makefile').read_text()
repaired = original
replacements = [
    ('REGRESSION_TIMEOUT ?= 240\n', 'REGRESSION_TIMEOUT ?= 240\nREGRESSION_SHARD_DIR ?= reports/regression/shards\n'),
    ('\tmkdir -p reports/regression/shards\n\tPYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_regression_shards.py run', '\tmkdir -p "$(REGRESSION_SHARD_DIR)"\n\tPYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_regression_shards.py run'),
    ('--out "reports/regression/shards/shard-$(SHARD_INDEX).json"', '--out "$(REGRESSION_SHARD_DIR)/shard-$(SHARD_INDEX).json"'),
    ('reports/regression/FULL_REGRESSION_CURRENT.json reports/regression/shards/shard-*.json', 'reports/regression/FULL_REGRESSION_CURRENT.json "$(REGRESSION_SHARD_DIR)"/shard-*.json'),
]
for old, new in replacements:
    assert repaired.count(old) == 1
    repaired = repaired.replace(old, new)
old_recipe = '''backend-report:
\t# Receipts are tracked evidence and therefore part of repository self-inspection.
\t# Overwrite them in place: deleting the directory before pytest makes the
\t# repository-completeness requirement fail inside every shard.
\tmkdir -p reports/regression/shards
\tfor index in $$(seq 0 $$(( $(REGRESSION_SHARDS) - 1 ))); do \\
\t  $(MAKE) regression-shard SHARD_INDEX=$$index PY=$(PY) || exit 1; \\
\tdone
\t$(MAKE) regression-shard-merge PY=$(PY)
\tPYTHONPATH=apps/api/src:scripts $(PY) scripts/publish_backend_report.py'''
new_recipe = '''backend-report:
\t# Keep tracked receipts unchanged while shards inspect the source checkout.
\t# A failed worker leaves prior evidence intact; each invocation owns its staging directory.
\tmkdir -p var
\t@set -eu; \\
\t  test "$(REGRESSION_SHARDS)" -ge 1; \\
\t  stage=$$(mktemp -d var/regression-shards.XXXXXX); \\
\t  trap 'rm -rf "$$stage"' EXIT; \\
\t  trap 'exit 1' HUP INT TERM; \\
\t  for index in $$(seq 0 $$(( $(REGRESSION_SHARDS) - 1 ))); do \\
\t    $(MAKE) regression-shard SHARD_INDEX=$$index REGRESSION_SHARD_DIR="$$stage" PY=$(PY); \\
\t  done; \\
\t  rm -rf reports/regression/shards; \\
\t  mkdir -p reports/regression/shards; \\
\t  mv "$$stage"/* reports/regression/shards/
\t$(MAKE) regression-shard-merge PY=$(PY)
\tPYTHONPATH=apps/api/src:scripts $(PY) scripts/publish_backend_report.py'''
assert repaired.count(old_recipe) == 1
repaired = repaired.replace(old_recipe, new_recipe)
(ROOT / 'Makefile').write_text(repaired)
repaired_counts = suite([TEST], 'repaired-staging', True)
assert repaired_counts['tests'] == 16
controls = {}
mutations = {
    'tracked-destination-restored': ('REGRESSION_SHARD_DIR="$$stage"', 'REGRESSION_SHARD_DIR="reports/regression/shards"'),
    'worker-failure-ignored': ('@set -eu;', '@set -u;'),
    'staging-cleanup-omitted': ("trap 'rm -rf \"$$stage\"' EXIT;", "trap ':' EXIT;"),
}
try:
    for label, (old, new) in mutations.items():
        assert repaired.count(old) == 1
        (ROOT / 'Makefile').write_text(repaired.replace(old, new))
        controls[label] = suite([TEST], label, False)
finally:
    (ROOT / 'Makefile').write_text(repaired)
assert suite([TEST], 'restored-staging', True) == repaired_counts

statuses = ['SUPERSEDED', 'SUPERSEDED', 'ADAPTED_PENDING_FULL_CI', 'SUPERSEDED', 'RETAIN_EXCLUDED_PENDING_SCOPED_ADAPTATION']
reasons = [
    'All four changed Python definitions are retained with identical AST; the three named regressions pass in original candidate CI. Formatting and obsolete generated identity are not imported.',
    'Architecture separation, return-decision attestation and HTTP deadline admission are represented by current source and tests. The old ISSUE_46_BOUNDARY_FIXES local checkpoint is historical, not current admission evidence.',
    'Restore isolated staging for backend-report with 16 new real-Make/inert-producer cases. Retain current dependency graph, PostgreSQL-before-union order and audit-reader regression. Do not import 86 historic generated paths.',
    'Gateway implementation and all 247 changed named tests are represented by the hardened candidate. Later source changes retain stricter boundary normalization, decision attestation and deadlines. The unused historical registry.versions convenience accessor is not reintroduced as a supported API; its source remains in the legacy ref.',
    '33 absent source paths include a distinct, unadmitted hosted-release/attestation pipeline. Issues #66 and #67 require scoped adaptation to the current artifact DAG and explicitly reject wholesale restoration of this legacy workflow. Retain this ref; do not assert its remaining implementation or production obligations are complete.',
]
records = []
for index, branch in enumerate(summary['branches']):
    source_rows = [r for r in branch['changes'] if not r['generated']]
    names = {(r['path'][len('apps/api/'):].removesuffix('.py').replace('/', '.'), name.split('.')[-1])
             for r in source_rows if r['path'].startswith('apps/api/tests/')
             for name in r['legacy_changed_definitions'] if name.split('.')[-1].startswith('test_')}
    matched = [c for c in cases if (c.get('classname'), c.get('name', '').split('[')[0]) in names]
    records.append({
        'branch': branch['branch'], 'head': branch['head'], 'merge_base': branch['merge_base'],
        'status': statuses[index], 'reason': reasons[index],
        'net_delta_paths': len(branch['changes']), 'non_generated_paths': len(source_rows),
        'exact_current_blob_and_mode': sum(r['same_blob_and_mode'] for r in source_rows),
        'absent_current_paths': [r['path'] for r in source_rows if r['candidate'] is None],
        'original_candidate_test_match': {'scope': SOURCE, 'run_id': 39610691741,
          'introduced_test_functions': len(names), 'matched_cases': len(matched),
          'passed': sum(not any(c.find(t) is not None for t in ('failure','error','skipped')) for c in matched),
          'skipped': sum(c.find('skipped') is not None for c in matched)},
        'history_retained': True, 'original_commits_claimed_merged': False,
    })
record = {
    'schema': 'korpus.canonical-branch-disposition.v1', 'observed_date': '2026-10-21',
    'compared_source': SOURCE, 'main_baseline': MAIN,
    'static_audit': {'run_id': 39629417088, 'artifact_id': 12357074758,
      'archive_sha256': '363e3d95c1ad36dfa8020655acfef0e7f463cb8d62b01df8a14a0e5d8c57b305',
      'method': 'Pinned common-ancestor deltas, Git blob/mode equality, parsed AST and manual source review; no legacy code execution.'},
    'classification_complete': True, 'all_source_integrated': False,
    'records': records,
    'previous_dispositions': [
       {'branch': 'governance/issue-54-forge-contract', 'head': '398c3ac524e20d9d986cfb7df4c07cd54f1073be', 'status': 'NO_NET_SOURCE_IMPORT', 'review_id': 5601034069},
       {'branch': 'audit/pr85-empty-component-fix-20261021', 'head': '974dfc77b30e0dfc4beb703e6e29d269132c28ae', 'status': 'NO_NET_SOURCE_IMPORT', 'review_id': 5601034069},
       {'branch': 'codex/finalize-canonical-20261018', 'head': '54db6bdbf2091a3bf7a66cf1124aa0c1a364931e', 'status': 'SUPERSEDED', 'review_id': 5602153926},
    ],
    'retained_dependencies': [66, 67, 72],
    'limits': ['AST equality and passing finite tests are not universal semantic/security proof.',
               'Original-candidate test matches do not replace fresh final-head CI or independent review.',
               'Classification is not branch deletion, source-integration completion or merge authorization.'],
    'merge_authorized': False, 'production_authorized': False,
}
write_json(ROOT / DISPOSITION, record)
old_document = (ROOT / DOC).read_text()
start, finish = old_document.index('## Branch disposition'), old_document.index('## Operator validation')
section = '''## Branch disposition (2026-10-21 continuation)

The original CANONICAL_BRANCH_INVENTORY.json remains an immutable dated observation.
The companion CANONICAL_BRANCH_DISPOSITION.json records subsequent source-level decisions,
exact legacy pins, current-test matches and retained implementation dependencies.
Twenty-five tips were already ancestors of the main baseline. The package stack is represented
once; do not merge both its component PRs and the aggregate as independent source imports.

Read-only static audit run 39629417088 examined all five residual tips against source
c2abdb69edd273c53e3a7bb2344f1ffb3be2a158. Artifact 12357074758 was independently hash-checked:
363e3d95c1ad36dfa8020655acfef0e7f463cb8d62b01df8a14a0e5d8c57b305.
All 730 internal evidence-file hashes were verified. No legacy code was executed.

| Legacy tip | Disposition | Rationale |
| --- | --- | --- |
| agent/ci-local-ref-isolation-20261018 | SUPERSEDED | Four changed definitions retained; three named tests pass in original candidate CI. |
| codex/issue-46-architecture | SUPERSEDED | Current composition, gateway and deadline implementation covers the changes; 50 matched cases pass. The old local verification log remains historical. |
| codex/issue-6-release-evidence | ADAPTED_PENDING_FULL_CI | Restore isolated receipt staging only; preserve newer dependencies and controls; never promote its 86 generated paths as fresh evidence. |
| proposal/korpus-capability-gateway-v1-20260904 | SUPERSEDED | Current hardened implementation retains all 247 named test functions (277 matched cases pass). Do not reintroduce the unused registry.versions helper as a public API. |
| work/issue-54-hosted-bootstrap | RETAIN_EXCLUDED_PENDING_SCOPED_ADAPTATION | 33 absent paths belong in a scoped current-architecture assessment under #66/#67, not a blind workflow rollback. Those obligations remain OPEN. |

The auxiliary governance/issue-54-forge-contract and audit/pr85-empty-component-fix-20261021
tips have no additional net source import (review 5601034069). codex/finalize-canonical-20261018
is semantically superseded by current all-parent traversal and its killed M727 control
(review 5602153926). Source disposition is not ancestry equivalence: all refs and original
commits remain intact; no branch, tag, issue or component PR is deleted or silently closed.
Five of five residual tips are classified; not all historic implementation debt is closed.

## Regression-receipt staging correction

The previous backend-report target overwrote tracked shard receipts while later workers still
inspected the checkout. A failed worker could leave a mixture of old and new evidence.
Each invocation now creates a unique staging directory under var, directs every worker there,
preserves prior tracked receipts during worker execution, and stops before promotion if a worker
fails. Positive shard count is required. Normal exit and handled signals clean the temporary path.
Only a fully successful worker loop replaces the canonical shard directory; the original exact
shard-merge verifier and backend publisher then run unchanged. Direct regression-shard commands
retain their original output default and may explicitly set REGRESSION_SHARD_DIR.

Sixteen isolated tests execute the actual Make recipes with inert Python producers: normal and
space-containing workspaces, two/three workers, failure of first/later workers, explicit staging
paths, and invalid counts. Named guard regressions test early live writes, ignored worker failures
and omitted cleanup. Tests do not activate services, acquire content or invoke production tools.
This is worker-phase isolation, NOT crash-atomic directory promotion or concurrent-worktree support.
A promotion/merge/publisher failure still blocks completion; the one-worktree-per-agent contract applies.

The complete generated source identity is rebound after this change. Full hosted CI and independent
CODE/SECURITY assessment must cover the final commit; earlier c2abdb69 results are historical.

'''
(ROOT / DOC).write_text(old_document[:start] + section + old_document[finish:])
git('add', '--', *PATHS[:-2])
from scripts.generate_manifest import write_manifest
from scripts.verify_source_manifest import verify as verify_manifest
from scripts.verify_package_build_identity import verify as verify_package
manifest = write_manifest(ROOT, ROOT / 'SOURCE_MANIFEST.json', kind='source')
package = json.loads((ROOT / 'PACKAGE_BUILD.json').read_bytes())
package['source_manifest_root_sha256'] = manifest['root_sha256']
write_json(ROOT / 'PACKAGE_BUILD.json', package)
git('add', '--', 'SOURCE_MANIFEST.json', 'PACKAGE_BUILD.json')
assert verify_manifest(ROOT)['valid'] is True and verify_package(ROOT) == []
combined = suite([TEST, 'apps/api/tests/test_release_adaptation_automation_v050.py', 'apps/api/tests/test_regression_shard_contract.py'], 'combined-focused', True)
quality = [
    [sys.executable, '-m', 'ruff', 'check', TEST],
    [sys.executable, '-m', 'ruff', 'format', '--check', TEST],
    [sys.executable, 'scripts/check_module_budget.py'],
    [sys.executable, 'scripts/check_budget_raises_are_named.py', '--base', MAIN],
    [sys.executable, 'scripts/verify_source_manifest.py'],
    [sys.executable, 'scripts/verify_package_build_identity.py'],
    ['/usr/bin/git', 'diff', '--check', SOURCE],
]
for i, command in enumerate(quality):
    assert run(command, 'quality-' + str(i)) == 0
assert (ROOT / 'Makefile').read_text() == repaired
assert verify_manifest(ROOT)['valid'] is True and verify_package(ROOT) == []
assert text('diff', '--name-only', SOURCE).splitlines() == sorted(PATHS)
assert not text('diff', SOURCE, '--', '.github', 'config/operations/module-budget.json', 'apps/api/requirements.dev.lock', 'apps/api/requirements.runtime.lock')
git('add', '--', *PATHS)
entries = []
for name in PATHS:
    metadata = git('ls-files', '-s', '--', name).split(b'\t', 1)[0].decode().split()
    mode, blob, stage = metadata
    assert stage == '0' and mode == '100644'
    data = (ROOT / name).read_bytes()
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == blob
    target = OUT / 'payload' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    entries.append({'path': name, 'mode': mode, 'type': 'blob', 'sha': blob, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
receipt = {'schema': 'korpus.residual-preparation.v1', 'status': 'TESTED_NOT_ADMITTED',
    'source': SOURCE, 'main': MAIN, 'request_head': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
    'baseline': baseline, 'repaired': repaired_counts, 'controls': controls, 'combined_focused': combined,
    'quality_commands': quality, 'entries': entries, 'tree_sha': text('write-tree'),
    'source_manifest_root_sha256': manifest['root_sha256'], 'source_file_count': manifest['file_count'],
    'merge_authorized': False, 'production_authorized': False}
write_json(OUT / 'receipt.json', receipt)
print(json.dumps(receipt, sort_keys=True), flush=True)
