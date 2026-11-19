"""Neutral, measured native datasets behind a deterministic GitHub HTTP test double."""

from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from coverage_execution_contract import SOURCE_INPUTS, canonical_bytes, snapshot  # noqa: E402
from github_evidence_artifact import digest  # noqa: E402
from github_evidence_run import (  # noqa: E402
    OWNER_ID,
    POSTGRES,
    REPOSITORY_ID,
    SECURITY,
    SQLITE,
    UPLOAD_ACTION,
    WORKFLOW_ID,
    WORKFLOW_PATH,
    Producer,
    Selection,
)
from github_evidence_source import Checkout  # noqa: E402
from github_evidence_transport import GitHubTransport, strict_object  # noqa: E402
from github_source_identity import IDENTITY_PATHS  # noqa: E402

COMMIT, TREE = "a" * 40, "b" * 40
SELECTED = Selection(12345, 2)
RUN_PATH = f"/actions/runs/{SELECTED.run_id}"
HOSTED = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_REPOSITORY": "neuron7x/KORPUS",
    "GITHUB_SHA": COMMIT,
    "GITHUB_RUN_ID": str(SELECTED.run_id),
    "GITHUB_RUN_ATTEMPT": str(SELECTED.attempt),
}


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True).encode()


class ReplayTransport:
    """Only test code can inject this transport; the CLI always constructs HTTPS transport."""

    collection = GitHubTransport.collection

    def __init__(self) -> None:
        self.responses: dict[str, bytes] = {}
        self.downloads: list[str] = []

    def json(self, relative: str) -> dict[str, Any]:
        return strict_object(self.responses[relative], "test GitHub HTTPS response")

    def download(self, relative: str, limit: int) -> bytes:
        self.downloads.append(relative)
        payload = self.responses[relative]
        assert len(payload) <= limit
        return payload


@dataclass
class EvidenceFixture:
    checkout: Checkout
    api: ReplayTransport
    artifacts: dict[str, dict[str, Any]]
    members: dict[str, dict[str, bytes]]
    jobs: dict[str, dict[str, Any]]
    upload_time: datetime

    def clone(self) -> EvidenceFixture:
        return copy.deepcopy(self)

    def replace_json(self, relative: str, mutate) -> None:
        record = self.api.json(relative)
        mutate(record)
        self.api.responses[relative] = encoded(record)

    def repack(self, producer: Producer) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"neutral artifact fixture"
            for name, value in sorted(self.members[producer.job].items()):
                archive.writestr(name, value)
        payload = output.getvalue()
        record = self.artifacts[producer.job]
        record.update(digest="sha256:" + digest(payload), size_in_bytes=len(payload))
        self.api.responses[f"/actions/artifacts/{record['id']}/zip"] = payload
        self.api.responses[RUN_PATH + "/artifacts?per_page=100"] = encoded(
            {"total_count": len(self.artifacts), "artifacts": list(self.artifacts.values())}
        )
        job = self.jobs[producer.job]
        messages = (
            "##[group]Run " + UPLOAD_ACTION,
            "SHA256 digest of uploaded artifact is " + digest(payload),
            f"Artifact {record['name']} successfully finalized. Artifact ID {record['id']}",
        )
        self.api.responses[f"/actions/jobs/{job['id']}/logs"] = "".join(
            f"{(self.upload_time + timedelta(seconds=i)).isoformat().replace('+00:00', 'Z')} {text}\n"
            for i, text in enumerate(messages)
        ).encode()

    def sync_union_receipts(self) -> None:
        report = json.loads(self.members[SQLITE.job]["coverage-union.json"])
        report["dialect_union"]["input_receipt_sha256"] = {
            dialect: digest(self.members[producer.job][f"coverage-{prefix}-receipt.json"])
            for dialect, producer, prefix in (
                ("sqlite", SQLITE, "sqlite"),
                ("postgresql", POSTGRES, "postgres"),
            )
        }
        self.members[SQLITE.job]["coverage-union.json"] = encoded(report)

    def add_artifact(self, producer: Producer, members: dict[str, bytes]) -> None:
        job = copy.deepcopy(self.jobs[SQLITE.job])
        job.update(id=max(item["id"] for item in self.jobs.values()) + 1, name=producer.job)
        job["steps"][0]["name"] = producer.upload_step
        self.jobs[producer.job] = job
        metadata = copy.deepcopy(self.artifacts[SQLITE.job])
        metadata.update(
            id=max(item["id"] for item in self.artifacts.values()) + 1,
            name=f"{producer.artifact_prefix}-{SELECTED.attempt}",
        )
        self.artifacts[producer.job] = metadata
        self.members[producer.job] = dict(members)
        self.repack(producer)
        self.api.responses[RUN_PATH + f"/attempts/{SELECTED.attempt}/jobs?per_page=100"] = encoded(
            {
                "total_count": len(self.jobs),
                "jobs": list(self.jobs.values()),
            }
        )


def _collect(root: Path, dialect: str, choice: str) -> None:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GITHUB_", "CI_", "COVERAGE_")) and name != "GITLAB_CI"
    }
    environment.update(HOSTED)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/collect_dialect_coverage.py"),
            "--root",
            str(root),
            "--dialect",
            dialect,
            "--",
            sys.executable,
            "-m",
            "coverage",
            "run",
            "apps/api/tests/measure_toy.py",
            choice,
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _source(root: Path) -> None:
    for relative in SOURCE_INPUTS:
        path = root / relative
        if Path(relative).suffix or relative == "Makefile":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# neutral fixture\n")
        else:
            path.mkdir(parents=True, exist_ok=True)
            (path / "fixture.txt").write_text("neutral source input\n")
    source = root / "apps/api/src/korpus"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "toy.py").write_text(
        'def choose(flag):\n    if flag:\n        return "left"\n    return "right"\n'
    )
    tests = root / "apps/api/tests"
    tests.mkdir()
    (tests / "measure_toy.py").write_text(
        "import runpy, sys\n"
        'module = runpy.run_path("apps/api/src/korpus/toy.py")\n'
        'assert module["choose"](sys.argv[1] == "left") in {"left", "right"}\n'
    )
    for kind in ("runtime", "dev", "scanners"):
        (root / f"apps/api/requirements.{kind}.lock").write_bytes(
            (ROOT / f"apps/api/requirements.{kind}.lock").read_bytes()
        )
    (source / "release.json").write_bytes(
        encoded(
            {
                "schema": "korpus.release-identity.v1",
                "product": "KORPUS",
                "tag": "v0.9.7",
                "version": "0.9.7",
                "artifact_stem": "KORPUS_v0.9.7_NEUTRAL_FIXTURE",
                "distribution_artifact": "KORPUS_v0.9.7_NEUTRAL_FIXTURE.zip",
            }
        )
    )


def measured_fixture(root: Path) -> EvidenceFixture:
    _source(root)
    for name in ("SOURCE_MANIFEST.json", "PACKAGE_BUILD.json"):
        (root / name).write_bytes(encoded({"neutral_identity": name}))
    started = datetime.now(UTC) - timedelta(seconds=5)
    _collect(root, "sqlite", "left")
    _collect(root, "postgresql", "right")
    environment = {**os.environ, **HOSTED}
    environment.pop("GITLAB_CI", None)
    merged = subprocess.run(
        [sys.executable, str(ROOT / "scripts/merge_dialect_coverage.py"), "--root", str(root)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert merged.returncode == 0, merged.stdout + merged.stderr
    uploaded = datetime.now(UTC) + timedelta(seconds=1)
    completed = uploaded + timedelta(seconds=5)
    repository = {
        "id": REPOSITORY_ID,
        "full_name": "neuron7x/KORPUS",
        "owner": {"id": OWNER_ID, "login": "neuron7x"},
    }
    run = {
        "id": SELECTED.run_id,
        "run_attempt": SELECTED.attempt,
        "workflow_id": WORKFLOW_ID,
        "path": WORKFLOW_PATH,
        "event": "push",
        "head_branch": "main",
        "head_sha": COMMIT,
        "repository": repository,
        "head_repository": repository,
        "status": "completed",
        "conclusion": "success",
        "run_started_at": started.isoformat(),
    }
    api = ReplayTransport()
    api.responses[RUN_PATH] = encoded(run)
    api.responses[RUN_PATH + f"/attempts/{SELECTED.attempt}"] = encoded(run)
    api.responses[f"/git/commits/{COMMIT}"] = encoded({"sha": COMMIT, "tree": {"sha": TREE}})
    source = snapshot(root, SOURCE_INPUTS)
    files = tuple(
        (Path(name), "0644", (root / name).read_bytes()) for name in sorted(source["files"])
    )
    identity_files = tuple(
        (Path(name), "0644", (root / name).read_bytes()) for name in IDENTITY_PATHS
    )
    fixture = EvidenceFixture(
        Checkout(
            root,
            COMMIT,
            TREE,
            "c" * 64,
            canonical_bytes(source),
            "d" * 64,
            "e" * 64,
            files,
            identity_files,
        ),
        api,
        {},
        {},
        {},
        uploaded,
    )
    for index, producer in enumerate((SQLITE, POSTGRES), 1):
        fixture.jobs[producer.job] = {
            "id": 100 + index,
            "run_id": SELECTED.run_id,
            "run_attempt": SELECTED.attempt,
            "name": producer.job,
            "head_sha": COMMIT,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "runner_group_name": "GitHub Actions",
            "labels": ["ubuntu-24.04"],
            "started_at": started.isoformat(),
            "completed_at": (completed + timedelta(seconds=1)).isoformat(),
            "steps": [
                {
                    "name": producer.upload_step,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": uploaded.isoformat(),
                    "completed_at": completed.isoformat(),
                }
            ],
        }
        fixture.artifacts[producer.job] = {
            "id": 200 + index,
            "name": f"{producer.artifact_prefix}-{SELECTED.attempt}",
            "expired": False,
            "created_at": (uploaded + timedelta(seconds=2)).isoformat(),
            "workflow_run": {
                "id": SELECTED.run_id,
                "repository_id": REPOSITORY_ID,
                "head_repository_id": REPOSITORY_ID,
                "head_sha": COMMIT,
                "head_branch": "main",
            },
        }
        names = producer.required_members
        if producer == SQLITE:
            names += POSTGRES.required_members
        fixture.members[producer.job] = {name: (root / "var" / name).read_bytes() for name in names}
        fixture.repack(producer)
    api.responses[RUN_PATH + f"/attempts/{SELECTED.attempt}/jobs?per_page=100"] = encoded(
        {"total_count": len(fixture.jobs), "jobs": list(fixture.jobs.values())}
    )
    return fixture


def pull_request_fixture(measured: EvidenceFixture) -> EvidenceFixture:
    fixture = measured.clone()
    repository = fixture.api.json(RUN_PATH)["repository"]
    for endpoint in (RUN_PATH, RUN_PATH + f"/attempts/{SELECTED.attempt}"):
        record = fixture.api.json(endpoint)
        record.update(event="pull_request", head_sha="c" * 40, head_branch="candidate")
        record["referenced_workflows"] = [
            {
                "path": f"neuron7x/KORPUS/.github/workflows/assurance.yml@{COMMIT}",
                "sha": COMMIT,
                "ref": "refs/pull/113/merge",
            }
        ]
        fixture.api.responses[endpoint] = encoded(record)
    fixture.api.responses["/pulls/113"] = encoded(
        {
            "number": 113,
            "merge_commit_sha": COMMIT,
            "head": {"sha": "c" * 40, "ref": "candidate", "repo": repository},
            "base": {"sha": "d" * 40, "ref": "main", "repo": repository},
        }
    )
    fixture.api.responses[f"/git/commits/{COMMIT}"] = encoded(
        {
            "sha": COMMIT,
            "tree": {"sha": TREE},
            "parents": [{"sha": "d" * 40}, {"sha": "c" * 40}],
        }
    )
    for job in fixture.jobs.values():
        job.update(head_sha="c" * 40, head_branch="candidate")
    fixture.api.responses[RUN_PATH + f"/attempts/{SELECTED.attempt}/jobs?per_page=100"] = encoded(
        {
            "total_count": len(fixture.jobs),
            "jobs": list(fixture.jobs.values()),
        }
    )
    for producer in (SQLITE, POSTGRES):
        fixture.artifacts[producer.job]["workflow_run"].update(
            head_sha="c" * 40, head_branch="candidate"
        )
        fixture.repack(producer)
    return fixture


def with_security(measured: EvidenceFixture) -> EvidenceFixture:
    from scripts.source_security_contract import EXECUTION_NAMES, expected_tools
    from scripts.source_security_lock import build_lock_sbom, locked_packages

    from .source_security_fixtures import execution_record, output_values

    fixture = measured.clone()
    values = output_values()
    for kind in ("runtime", "dev"):
        values[f"pip-audit-{kind}.json"]["dependencies"] = [
            {"name": name, "version": version, "vulns": []}
            for name, version in sorted(locked_packages(fixture.checkout.root, kind).items())
        ]
    values["lock-sbom.cdx.json"] = build_lock_sbom(fixture.checkout.root)
    started = fixture.jobs[SQLITE.job]["started_at"]
    completed = (fixture.upload_time - timedelta(seconds=1)).isoformat()
    values["tree-sbom.cdx.json"]["metadata"]["timestamp"] = completed
    values["trivy.json"]["CreatedAt"] = completed
    members = {name: encoded(value) for name, value in values.items()}
    receipt = {
        "schema": "korpus.source-security-execution.v1",
        "status": "PASS",
        "production_authorized": False,
        "run": {
            name: HOSTED[name]
            for name in ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
        },
        "source_commit_sha": fixture.checkout.commit,
        "source_tree_oid": fixture.checkout.tree,
        "source_before": fixture.checkout.source,
        "source_after_sha256": fixture.checkout.source["sha256"],
        "tools": expected_tools(fixture.checkout.root),
        "executions": [
            execution_record(tool, ["neutral-fixture", tool], started, completed)
            for tool in EXECUTION_NAMES
        ],
        "artifacts": {
            name: {"path": "var/source-security/" + name, "sha256": digest(payload)}
            for name, payload in members.items()
        },
    }
    receipt["run"]["kind"] = "github-actions"
    members["source-security-receipt.json"] = encoded(receipt)
    fixture.add_artifact(SECURITY, members)
    return fixture
