"""Execute actual Make recipes with inert producers to verify publication ordering."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

RUNNER = r"""
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("--shard-index", type=int)
parser.add_argument("--shard-count", type=int)
parser.add_argument("--timeout-seconds")
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("receipts", nargs="*")
args = parser.parse_args()
prior = json.loads(Path("expected.json").read_text())
if args.command == "run":
    observed = {str(p): p.read_text() for p in Path("reports/regression/shards").glob("*")}
    if observed != prior:
        raise SystemExit("tracked receipts changed while workers were still running")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"index": args.shard_index, "fresh": True}))
    args.out.with_suffix(".junit.xml").write_text("inert worker receipt")
    if os.getenv("FAIL_SHARD") == str(args.shard_index):
        raise SystemExit(7)
else:
    Path("merged-receipts.json").write_text(json.dumps(args.receipts))
    records = [json.loads(Path(p).read_text()) for p in args.receipts]
    assert sorted(r["index"] for r in records) == list(range(int(os.environ["SHARD_COUNT"])))
    assert all(r["fresh"] for r in records)
    args.out.write_text(json.dumps({"validated": True}))
"""


def _recipe(source: str, name: str) -> str:
    pattern = rf"^{re.escape(name)}:\n(?:\t.*\n|\t.*$)+"
    match = re.search(pattern, source, re.MULTILINE)
    assert match is not None, f"missing recipe: {name}"
    return match.group(0).rstrip() + "\n"


def _workspace(tmp_path: Path, spaced: bool) -> Path:
    root = tmp_path / ("workspace with spaces" if spaced else "workspace")
    root.mkdir()
    source = (ROOT / "Makefile").read_text(encoding="utf-8")
    definitions = "\n".join(
        line for line in source.splitlines() if line.startswith("REGRESSION_") and "?=" in line
    )
    recipes = "\n".join(
        _recipe(source, name)
        for name in ("regression-shard", "regression-shard-merge", "backend-report")
    )
    (root / "Makefile").write_text(definitions + "\n" + recipes, encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "run_regression_shards.py").write_text(RUNNER, encoding="utf-8")
    (scripts / "publish_backend_report.py").write_text(
        'from pathlib import Path\nPath("published").write_text("yes")\n', encoding="utf-8"
    )
    prior = root / "reports/regression/shards"
    prior.mkdir(parents=True)
    for name in ("shard-0.json", "shard-1.json", "obsolete.json"):
        (prior / name).write_text("previous evidence: " + name, encoding="utf-8")
    expected = {str(p.relative_to(root)): p.read_text() for p in prior.iterdir()}
    (root / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
    return root


def _make(
    root: Path,
    *arguments: str,
    count: int,
    fail: int | None = None,
    shard_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("make")
    assert executable is not None, "GNU Make is required for recipe integration tests"
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "FAIL_SHARD", "REGRESSION_SHARD_DIR"}
    }
    env["SHARD_COUNT"] = str(count)
    if shard_dir is not None:
        env["REGRESSION_SHARD_DIR"] = shard_dir
    if fail is not None:
        env["FAIL_SHARD"] = str(fail)
    return subprocess.run(
        [
            executable,
            "--no-print-directory",
            *arguments,
            f"PY={sys.executable}",
            f"REGRESSION_SHARDS={count}",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("spaced", [False, True])
@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("fail", [None, 0, 1])
def test_workers_preserve_prior_receipts_and_publish_only_after_success(
    tmp_path: Path, spaced: bool, count: int, fail: int | None
) -> None:
    root = _workspace(tmp_path, spaced)
    result = _make(root, "backend-report", count=count, fail=fail)
    expected = json.loads((root / "expected.json").read_text())
    if fail is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert (root / "published").read_text() == "yes"
        assert not (root / "reports/regression/shards/obsolete.json").exists()
        assert len(list((root / "reports/regression/shards").glob("*.json"))) == count
    else:
        assert result.returncode != 0
        observed = {
            str(p.relative_to(root)): p.read_text()
            for p in (root / "reports/regression/shards").iterdir()
        }
        assert observed == expected, result.stdout + result.stderr
        assert not (root / "published").exists()
        assert not (root / "reports/regression/FULL_REGRESSION_CURRENT.json").exists()
    assert not list((root / "var").glob("regression-shards.*"))


@pytest.mark.parametrize("spaced", [False, True])
def test_explicit_shard_directory_is_honored(tmp_path: Path, spaced: bool) -> None:
    root = _workspace(tmp_path, spaced)
    result = _make(
        root,
        "regression-shard",
        "SHARD_INDEX=0",
        "REGRESSION_SHARD_DIR=var/custom staging",
        count=2,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "var/custom staging/shard-0.json").is_file()
    expected = json.loads((root / "expected.json").read_text())
    assert all((root / path).read_text() == value for path, value in expected.items())


@pytest.mark.parametrize("count", [0, -1])
def test_invalid_shard_count_preserves_prior_receipts(tmp_path: Path, count: int) -> None:
    root = _workspace(tmp_path, False)
    result = _make(root, "backend-report", count=count)
    assert result.returncode != 0
    expected = json.loads((root / "expected.json").read_text())
    observed = {
        str(p.relative_to(root)): p.read_text()
        for p in (root / "reports/regression/shards").iterdir()
    }
    assert observed == expected
    assert not (root / "published").exists()
    assert not list((root / "var").glob("regression-shards.*"))


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
