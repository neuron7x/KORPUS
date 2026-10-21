"""Prepare a bounded Make input-binding repair; never change repository refs."""
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = "c62e300f39659c058f0bf5038fd340a3d4c124cc"
MAIN = "345c0f7daf1da2152d0e554cc8733381ca5a1e9e"
TEST = "apps/api/tests/test_backend_report_staging.py"
DOC = "docs/operations/CANONICAL_CONVERGENCE.md"
PATHS = ["Makefile", TEST, DOC, "SOURCE_MANIFEST.json", "PACKAGE_BUILD.json"]
OUT = Path(os.environ["RUNNER_TEMP"]) / "merge-input-prepared"
OUT.mkdir(exist_ok=False)
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in {"GH_TOKEN", "GITHUB_TOKEN"}}
ENV.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_TERMINAL_PROMPT="0")

ADDITION = '''

@pytest.mark.parametrize("spaced", [False, True])
@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("override", ["environment", "command-line"])
def test_backend_merge_reads_promoted_receipts_not_caller_directory(
    tmp_path: Path, spaced: bool, count: int, populated: bool, override: str
) -> None:
    root = _workspace(tmp_path, spaced)
    relative = "var/caller receipts"
    caller = root / relative
    caller.mkdir(parents=True)
    if populated:
        for index in range(count):
            (caller / f"shard-{index}.json").write_text(
                json.dumps({"index": index, "fresh": True, "origin": "caller"}),
                encoding="utf-8",
            )
    before = {p.name: p.read_bytes() for p in caller.iterdir()}
    arguments = ["backend-report"]
    if override == "command-line":
        arguments.append(f"REGRESSION_SHARD_DIR={relative}")
    result = _make(
        root,
        *arguments,
        count=count,
        shard_dir=relative if override == "environment" else None,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    merged = json.loads((root / "merged-receipts.json").read_text())
    assert sorted(merged) == [
        f"reports/regression/shards/shard-{index}.json" for index in range(count)
    ]
    assert all(
        json.loads((root / path).read_text()) == {"index": index, "fresh": True}
        for index, path in enumerate(sorted(merged))
    )
    assert {p.name: p.read_bytes() for p in caller.iterdir()} == before
    assert (root / "published").read_text() == "yes"
    assert not list((root / "var").glob("regression-shards.*"))
'''
DOC_ADDITION = '''
## Merge input binding after staging

The backend-report merge command explicitly pins REGRESSION_SHARD_DIR to
reports/regression/shards, the directory to which its successful workers promote.
Caller environment/command-line directory overrides cannot redirect that merge to
another receipt set. Direct regression-shard and regression-shard-merge commands
retain their explicit-directory interfaces. This is an input-binding invariant,
not a claim of crash-atomic promotion or concurrent-worktree safety.

Sixteen additional inert Make-recipe cases cover both override channels, empty and
populated caller directories, normal/spaced workspaces, and two/three workers.
They check the exact merge input paths, fresh worker records, unchanged caller
files and temporary cleanup. Existing worker-failure tests remain active.
'''


def git(*args):
    return subprocess.run(["/usr/bin/git", "--no-replace-objects", *args], env=ENV,
                          check=True, capture_output=True, timeout=120).stdout


def run(command, tag, expected=0):
    result = subprocess.run(command, env=ENV, text=True, capture_output=True,
                            check=False, timeout=240)
    (OUT / (tag + ".log")).write_text(result.stdout + result.stderr)
    assert result.returncode == expected, (tag, result.returncode)
    return result


def suite(tag, paths, count, fail=False, select=None):
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--junitxml=" + str(OUT / (tag + ".xml")), *paths]
    if select:
        command += ["-k", select]
    run(command, tag, expected=1 if fail else 0)
    root = ET.parse(OUT / (tag + ".xml")).getroot()
    cases = list(root.iter("testcase"))
    totals = {key: sum(int(s.get(key, "0")) for s in root.iter("testsuite"))
              for key in ("tests", "failures", "errors", "skipped")}
    assert totals["tests"] == len(cases) == count
    assert totals["errors"] == totals["skipped"] == 0
    assert totals["failures"] == (count if fail else 0), totals
    return totals


assert git("rev-parse", "HEAD").decode().strip() == os.environ["GITHUB_SHA"]
assert git("rev-parse", "HEAD^").decode().strip() == "053480be080248eaf150f6c4dc6dcd9637630535"
assert git("rev-parse", "refs/remotes/origin/main").decode().strip() == MAIN
request = os.environ["GITHUB_SHA"]
git("checkout", "--detach", SOURCE)
assert not git("status", "--porcelain").strip()
Path("var").mkdir(exist_ok=True)
original_manifest = json.loads(Path("SOURCE_MANIFEST.json").read_bytes())
assert original_manifest["root_sha256"] == "ccc95bf0c741cba1ced334250678fcbf4808f95a41dbd5ef0dd8cf552d245b17"
for path, sha in {"Makefile": "4001ad3d571a55b79d24b4af43380bc016c27954", TEST: "c4150e6f61eff11d33f56e40c848d15914a7c4c3", DOC: "b2488ce69751f6b59eef3c18b1630099e6b4875c"}.items():
    assert git("hash-object", path).decode().strip() == sha

p = Path(TEST)
s = p.read_text()
replacements = [
    ('else:\n    records = [json.loads(Path(p).read_text()) for p in args.receipts]',
     'else:\n    Path("merged-receipts.json").write_text(json.dumps(args.receipts))\n    records = [json.loads(Path(p).read_text()) for p in args.receipts]'),
    ('    root: Path, *arguments: str, count: int, fail: int | None = None\n',
     '    root: Path,\n    *arguments: str,\n    count: int,\n    fail: int | None = None,\n    shard_dir: str | None = None,\n'),
    ('if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "FAIL_SHARD"}',
     'if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "FAIL_SHARD", "REGRESSION_SHARD_DIR"}'),
    ('    env["SHARD_COUNT"] = str(count)\n',
     '    env["SHARD_COUNT"] = str(count)\n    if shard_dir is not None:\n        env["REGRESSION_SHARD_DIR"] = shard_dir\n'),
]
for old, new in replacements:
    assert s.count(old) == 1
    s = s.replace(old, new)
p.write_text(s + ADDITION)
run([sys.executable, "-m", "ruff", "format", TEST], "format-test")
selector = "test_backend_merge_reads_promoted_receipts_not_caller_directory"
baseline = suite("baseline", [TEST], 16, fail=True, select=selector)
p = Path("Makefile")
original = p.read_text()
old = "\t$(MAKE) regression-shard-merge PY=$(PY)\n"
new = "\t$(MAKE) regression-shard-merge REGRESSION_SHARD_DIR=reports/regression/shards PY=$(PY)\n"
assert original.count(old) == 1
fixed = original.replace(old, new)
p.write_text(fixed)
repaired = suite("repaired", [TEST], 32)
p.write_text(fixed.replace(new, '\t$(MAKE) regression-shard-merge REGRESSION_SHARD_DIR="$(REGRESSION_SHARD_DIR)" PY=$(PY)\n'))
control = suite("inherited-directory-control", [TEST], 16, fail=True, select=selector)
p.write_text(fixed)
combined = suite("restored-combined", [TEST, "apps/api/tests/test_regression_shard_contract.py", "apps/api/tests/test_release_adaptation_automation_v050.py"], 48)
p = Path(DOC)
p.write_text(p.read_text() + DOC_ADDITION)
git("add", "--", "Makefile", TEST, DOC)
run([sys.executable, "scripts/generate_manifest.py"], "generate-manifest")
manifest = json.loads(Path("SOURCE_MANIFEST.json").read_bytes())
assert manifest["file_count"] == original_manifest["file_count"] == 2141
old_records = {r["path"]: r for r in original_manifest["files"]}
new_records = {r["path"]: r for r in manifest["files"]}
assert old_records.keys() == new_records.keys()
assert {p for p in old_records if old_records[p] != new_records[p]} == {"Makefile", TEST, DOC}
p = Path("PACKAGE_BUILD.json")
package = json.loads(p.read_bytes())
package["source_manifest_root_sha256"] = manifest["root_sha256"]
p.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n")
git("add", "--", *PATHS)
quality = [[sys.executable, "-m", "ruff", "check", TEST],
           [sys.executable, "-m", "ruff", "format", "--check", TEST],
           [sys.executable, "scripts/check_module_budget.py"],
           [sys.executable, "scripts/check_budget_raises_are_named.py", "--base", MAIN],
           [sys.executable, "scripts/verify_source_manifest.py"],
           [sys.executable, "scripts/verify_package_build_identity.py"],
           ["/usr/bin/git", "diff", "--cached", "--check", SOURCE]]
for index, command in enumerate(quality):
    run(command, "quality-" + str(index))
assert set(git("diff", "--cached", "--name-only", SOURCE).decode().splitlines()) == set(PATHS)
entries = []
for path in PATHS:
    mode, sha, stage = git("ls-files", "-s", "--", path).decode().split("\t", 1)[0].split()
    assert mode == "100644" and stage == "0"
    data = Path(path).read_bytes()
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == sha
    target = OUT / "payload" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    entries.append({"path": path, "mode": mode, "type": "blob", "sha": sha,
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
receipt = {"schema": "korpus.merge-input-repair.v1", "status": "TESTED_NOT_ADMITTED",
           "source": SOURCE, "main": MAIN, "request_head": request,
           "run_id": os.environ["GITHUB_RUN_ID"], "baseline": baseline,
           "repaired": repaired, "negative_control": control, "combined": combined,
           "entries": entries, "tree_sha": git("write-tree").decode().strip(),
           "file_count": manifest["file_count"], "root_sha256": manifest["root_sha256"],
           "merge_authorized": False, "production_authorized": False}
(OUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, sort_keys=True))
