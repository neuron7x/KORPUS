"""Apply a pinned, transparent revision to the temporary preparation helper."""
import hashlib
import subprocess
from pathlib import Path
import os

source = Path('.github/canonical_residual_prepare.py').read_text()
data = source.encode()
assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == '35081c980356c6d37222040a49e0b58bb9602592'
old_guard = '    assert "rm -rf reports/regression/shards" not in recipe\n    assert "$(MAKE) regression-shard" in recipe\n'
new_guard = '''    workers, separator, promotion = recipe.partition("\\t  done;")
    assert separator, "worker loop must finish before publication"
    assert "rm -rf reports/regression/shards" not in workers
    assert "$(MAKE) regression-shard SHARD_INDEX=" in workers
    assert "@set -eu;" in workers
    assert 'REGRESSION_SHARD_DIR="$$stage"' in workers
    assert (
        promotion.index("rm -rf reports/regression/shards")
        < promotion.index('mv "$$stage"/* reports/regression/shards/')
        < promotion.index("$(MAKE) regression-shard-merge")
    )
'''
insertion = '\ncontract_source = (ROOT / CONTRACT).read_text()\ncontract_old = ' + repr(old_guard) + '\ncontract_new = ' + repr(new_guard) + '\nassert contract_source.count(contract_old) == 1\n(ROOT / CONTRACT).write_text(contract_source.replace(contract_old, contract_new))\nassert run([sys.executable, "-m", "ruff", "format", CONTRACT], "format-contract") == 0\ncontrol_paths = [TEST, CONTRACT + "::test_backend_report_does_not_delete_tracked_receipts_before_self_tests"]\n'
changes = [
    ("PARENT = '4cf7cef2f4f52bbfcd4db565b31f26e86f08e25b'", "PARENT = '2e1ecab745e1c7fd545d725104826757fe0d7aaa'"),
    ("TEST = 'apps/api/tests/test_backend_report_staging.py'", "TEST = 'apps/api/tests/test_backend_report_staging.py'\nCONTRACT = 'apps/api/tests/test_regression_shard_contract.py'"),
    ("PATHS = ['Makefile', TEST, DOC, DISPOSITION,", "PATHS = ['Makefile', TEST, CONTRACT, DOC, DISPOSITION,"),
    ("summary['request_head'] == PARENT", "summary['request_head'] == '4cf7cef2f4f52bbfcd4db565b31f26e86f08e25b'"),
    ("    assert text('rev-parse', 'refs/remotes/origin/' + branch['branch']).decode() if False else text('rev-parse', 'refs/remotes/origin/' + branch['branch']) == branch['head']", "    assert text('rev-parse', 'refs/remotes/origin/' + branch['branch']) == branch['head']"),
    ('controls = {}\n', insertion + '\ncontrols = {}\n'),
    ("    'tracked-destination-restored':", "    'premature-receipt-removal': ('@set -eu;', '@set -eu; rm -rf reports/regression/shards;'),\n    'tracked-destination-restored':"),
    ('controls[label] = suite([TEST], label, False)', 'controls[label] = suite(control_paths, label, False)'),
    ('and omitted cleanup. Tests do not', 'premature deletion, and omitted cleanup. Tests do not'),
    ('This is worker-phase isolation, NOT', 'The existing no-deletion-before-self-tests contract is retained and made order-sensitive: deletion\nis forbidden before/during the worker loop, while verified post-worker promotion remains allowed.\nIts test name and all other shard-contract checks are preserved.\nThis is worker-phase isolation, NOT'),
    ("[sys.executable, '-m', 'ruff', 'check', TEST]", "[sys.executable, '-m', 'ruff', 'check', TEST, CONTRACT]"),
    ("[sys.executable, '-m', 'ruff', 'format', '--check', TEST]", "[sys.executable, '-m', 'ruff', 'format', '--check', TEST, CONTRACT]"),
]
for old, new in changes:
    assert source.count(old) == 1, 'Unexpected helper drift'
    source = source.replace(old, new)
compile(source, 'canonical_residual_prepare.py', 'exec')
destination = Path(os.environ['RUNNER_TEMP']) / 'canonical_residual_prepare.py'
destination.write_text(source)
print('Prepared revision SHA256:', hashlib.sha256(source.encode()).hexdigest(), flush=True)
subprocess.run([os.environ['pythonLocation'] + '/bin/python', str(destination)], check=True)
