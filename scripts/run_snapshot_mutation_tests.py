#!/usr/bin/env python3
"""First-order mutation gate for the temporal corpus snapshot invariant.

The legacy catalogue is intentionally large and sharded. Issue #23 adds a compact,
separately reviewable destruction set around the new cross-layer invariant so a missing
pre/post read barrier, epoch binding, epoch source, or full release digest cannot hide
inside aggregate coverage. A mutant is counted as killed only when its exact control
passes on the unmodified tree and fails after one surgical source mutation.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "var/snapshot-mutation-report.json"


@dataclass(frozen=True)
class Mutant:
    id: str
    path: str
    old: str
    new: str
    control: str
    claim: str


MUTANTS = (
    Mutant(
        "TS01",
        "apps/api/src/korpus/application/snapshot_retrieval.py",
        "        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)\n"
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n",
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_approval_between_token_validation_and_retrieval_fails_closed",
        "pre-read token validation is mandatory",
    ),
    Mutant(
        "TS02",
        "apps/api/src/korpus/application/snapshot_retrieval.py",
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n"
        "        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)\n"
        "        return result\n",
        "        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)\n"
        "        return result\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_rescission_after_retrieval_before_revalidation_fails_closed",
        "post-read token validation is mandatory",
    ),
    Mutant(
        "TS03",
        "apps/api/src/korpus/application/cache.py",
        "                str(token.state_epoch),\n",
        "                \"epoch-omitted\",\n",
        "apps/api/tests/test_query_cache.py::"
        "test_cache_is_bound_to_identity_release_epoch_and_configuration",
        "cache identity includes the monotonic epoch",
    ),
    Mutant(
        "TS04",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "        if current != token.state_epoch:\n"
        "            raise CorpusConsistencyError(\"corpus state changed after read token capture\")\n",
        "        if False:\n"
        "            raise CorpusConsistencyError(\"corpus state changed after read token capture\")\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_semantic_backfill_invalidates_an_inflight_snapshot_token",
        "validation rejects stale monotonic epochs",
    ),
    Mutant(
        "TS05",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "            release_id=digest.hexdigest(),\n",
        "            release_id=digest.hexdigest()[:16],\n",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_approval_seals_the_exact_persisted_evidence_set",
        "temporal release identity keeps the full SHA-256 digest",
    ),
    Mutant(
        "TS06",
        "apps/api/src/korpus/infrastructure/corpus_snapshot.py",
        "    \"span_embeddings\",\n",
        "",
        "apps/api/tests/test_temporal_corpus_snapshot.py::"
        "test_semantic_backfill_invalidates_an_inflight_snapshot_token",
        "semantic-index mutations advance corpus state epoch",
    ),
)


def _python() -> str:
    requested = os.getenv("PYTHON", "")
    if requested:
        found = shutil.which(requested)
        if found:
            return found
        candidate = (ROOT / requested).resolve()
        if candidate.is_file():
            return str(candidate)
        raise RuntimeError(f"PYTHON executable not found: {requested}")
    return sys.executable


def _environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "apps/api/src")))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_control(root: Path, selector: str, python: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python, "-m", "pytest", selector, "-q"],
        cwd=root,
        env=_environment(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _mutate(work: Path, mutant: Mutant) -> None:
    path = work / mutant.path
    source = path.read_text(encoding="utf-8")
    count = source.count(mutant.old)
    if count != 1:
        raise RuntimeError(
            f"{mutant.id}: expected one mutation site in {mutant.path}, found {count}"
        )
    path.write_text(source.replace(mutant.old, mutant.new, 1), encoding="utf-8")


def _copy_tree(target: Path) -> None:
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            "var",
            ".venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ),
    )


def main() -> int:
    python = _python()
    selectors = sorted({mutant.control for mutant in MUTANTS})
    controls: dict[str, dict[str, object]] = {}
    invalid: list[str] = []

    for selector in selectors:
        result = _run_control(ROOT, selector, python)
        controls[selector] = {
            "returncode": result.returncode,
            "output_tail": result.stdout[-2000:],
        }
        if result.returncode != 0:
            invalid.append(f"control failed: {selector}")

    outcomes: list[dict[str, object]] = []
    if not invalid:
        for mutant in MUTANTS:
            with tempfile.TemporaryDirectory(prefix=f"korpus-{mutant.id.lower()}-") as tmp:
                work = Path(tmp) / "repo"
                _copy_tree(work)
                try:
                    _mutate(work, mutant)
                except RuntimeError as exc:
                    invalid.append(str(exc))
                    outcomes.append({**asdict(mutant), "status": "INVALID", "returncode": None})
                    continue
                result = _run_control(work, mutant.control, python)
                outcomes.append(
                    {
                        **asdict(mutant),
                        "status": "KILLED" if result.returncode != 0 else "SURVIVED",
                        "returncode": result.returncode,
                        "output_tail": result.stdout[-2000:],
                    }
                )

    killed = sum(item.get("status") == "KILLED" for item in outcomes)
    survived = [str(item["id"]) for item in outcomes if item.get("status") == "SURVIVED"]
    report = {
        "schema": "korpus.snapshot-mutation.v1",
        "mutants": len(MUTANTS),
        "executed_mutants": len(outcomes),
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "controls": controls,
        "outcomes": outcomes,
        "status": "PASS"
        if not invalid and not survived and killed == len(MUTANTS)
        else "FAIL",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
