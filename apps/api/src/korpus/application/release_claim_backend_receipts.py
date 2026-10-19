from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from korpus.application.junit_contracts import junit_counts
from korpus.application.release_claim_admission import canonical_paths_admitted
from korpus.application.release_claim_common import (
    EvidenceContext,
    integer,
    load_object,
    sha256,
)

MERGE_PATH = "reports/regression/FULL_REGRESSION_CURRENT.json"
JUNIT_FIELDS = ("tests", "failures", "errors", "skipped")


def _sha_lines(items: list[str]) -> str:
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()


def _bucket(nodeid: str, shards: int) -> int:
    return int.from_bytes(hashlib.sha256(nodeid.encode("utf-8")).digest()[:8], "big") % shards


def _junit(path: Path) -> dict[str, int] | None:
    try:
        return cast(dict[str, int], junit_counts(ET.parse(path).getroot()))
    except (OSError, ET.ParseError, ValueError):
        return None


def _nodeids_from_output(stdout: str) -> tuple[str, ...]:
    marker = "KORPUS_NODEIDS_JSON="
    line = next((row for row in stdout.splitlines() if row.startswith(marker)), "")
    try:
        raw = json.loads(line[len(marker) :]) if line else []
    except json.JSONDecodeError:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return ()
    unique = tuple(sorted(set(raw)))
    return unique if len(unique) == len(raw) else ()


@lru_cache(maxsize=4)
def _live_nodeids(root_text: str, pytest_args: tuple[str, ...]) -> tuple[str, ...]:
    root = Path(root_text)
    marker = "KORPUS_NODEIDS_JSON="
    collector = f"""import json, pytest, sys
class P:
    def pytest_collection_finish(self, session):
        print({marker!r} + json.dumps([item.nodeid for item in session.items], separators=(',', ':')))
sys.exit(pytest.main(['--rootdir', {str(root)!r}, '--collect-only', '-q', *json.loads(sys.argv[1])], plugins=[P()]))
"""
    env = os.environ.copy()
    paths = [str(root / "apps/api/src"), str(root / "scripts"), str(root)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", collector, json.dumps(pytest_args)],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return _nodeids_from_output(completed.stdout) if completed.returncode == 0 else ()


def _receipt_paths(merge: dict[str, Any], shards: int) -> list[str] | None:
    raw = merge.get("receipt_paths")
    expected = {f"reports/regression/shards/shard-{index}.json" for index in range(shards)}
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return None
    return raw if len(raw) == shards and len(set(raw)) == shards and set(raw) == expected else None


def _nodeids_valid(nodeids: list[str], shards: int, index: int) -> bool:
    return len(nodeids) == len(set(nodeids)) and all(
        _bucket(item, shards) == index for item in nodeids
    )


def _receipt_junit(
    root: Path, index: int, receipt: dict[str, Any], selected: int
) -> dict[str, int] | None:
    observed = _junit(root / f"reports/regression/shards/shard-{index}.junit.xml")
    if observed is None or receipt.get("junit") != observed or observed["tests"] != selected:
        return None
    return None if observed["failures"] or observed["errors"] else observed


def _receipt_valid(
    receipt: dict[str, Any], context: EvidenceContext, merge: dict[str, Any], index: int
) -> tuple[list[str], dict[str, int]] | None:
    shards, count = merge["shards"], merge["collection_count"]
    nodeids, pytest_args = receipt.get("selected_nodeids"), receipt.get("pytest_args")
    if not isinstance(nodeids, list) or not all(isinstance(item, str) for item in nodeids):
        return None
    if not isinstance(pytest_args, list) or not all(isinstance(item, str) for item in pytest_args):
        return None
    expected = {
        "schema": "korpus.regression-shard.v1",
        "status": "PASS",
        "release_tag": context.release,
        "source_digest": context.source_digest,
        "collection_digest": merge["collection_digest"],
        "collection_count": count,
        "shard_index": index,
        "shard_count": shards,
        "selected_count": len(nodeids),
        "selected_digest": _sha_lines(nodeids),
        "exit_code": 0,
        "timed_out": False,
    }
    observed = _receipt_junit(context.root, index, receipt, len(nodeids))
    if any(receipt.get(key) != value for key, value in expected.items()):
        return None
    return (nodeids, observed) if _nodeids_valid(nodeids, shards, index) and observed else None


def _receipts_valid(
    context: EvidenceContext, merge: dict[str, Any], shard_count: int
) -> tuple[list[str], dict[str, int], list[str]] | None:
    all_nodeids: list[str] = []
    totals = {field: 0 for field in JUNIT_FIELDS}
    pytest_args: list[list[str]] = []
    for index in range(shard_count):
        receipt = load_object(context.root / f"reports/regression/shards/shard-{index}.json")
        valid = _receipt_valid(receipt, context, merge, index) if receipt is not None else None
        if valid is None:
            return None
        nodeids, counts = valid
        all_nodeids.extend(nodeids)
        pytest_args.append(list(receipt["pytest_args"]))
        totals = {field: totals[field] + counts[field] for field in JUNIT_FIELDS}
    if not pytest_args or any(args != pytest_args[0] for args in pytest_args):
        return None
    return all_nodeids, totals, pytest_args[0]


def backend_artifacts(context: EvidenceContext, shards: int) -> list[str]:
    return [
        context.evidence,
        MERGE_PATH,
        *(f"reports/regression/shards/shard-{index}.json" for index in range(shards)),
        *(f"reports/regression/shards/shard-{index}.junit.xml" for index in range(shards)),
    ]


def merge_valid(merge: dict[str, Any], context: EvidenceContext) -> bool:
    shards, count = merge.get("shards"), merge.get("collection_count")
    if not integer(shards, minimum=1) or not integer(count, minimum=1):
        return False
    shard_count, collection_count = cast(int, shards), cast(int, count)
    identity = (
        merge.get("schema") == "korpus.regression-merge.v1"
        and merge.get("status") == "PASS"
        and merge.get("release_tag") == context.release
        and merge.get("source_digest") == context.source_digest
        and sha256(merge.get("collection_digest"))
        and merge.get("failures") == []
        and _receipt_paths(merge, shard_count) is not None
    )
    receipts = _receipts_valid(context, merge, shard_count) if identity else None
    if receipts is None:
        return False
    all_nodeids, totals, pytest_args = receipts
    inputs = [
        *backend_artifacts(context, shard_count),
        *(nodeid.split("::", 1)[0] for nodeid in all_nodeids),
    ]
    live = _live_nodeids(str(context.root.resolve()), tuple(pytest_args))
    return (
        canonical_paths_admitted(context.root, sorted(set(inputs)))
        and len(all_nodeids) == collection_count
        and len(set(all_nodeids)) == collection_count
        and tuple(sorted(all_nodeids)) == live
        and _sha_lines(sorted(all_nodeids)) == merge["collection_digest"]
        and merge.get("junit") == totals
        and totals["tests"] == collection_count
    )
