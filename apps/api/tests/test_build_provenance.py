"""An SBOM beside an image answers "what is in some image".

SUP-003. The pipeline produced SBOMs; nothing signed them, nothing bound them to the image
they described, and nothing checked either before a deployment. The deployment question is
not "what is in some image" — it is "what is in this one".

`build_provenance.py` writes a statement shaped like SLSA provenance — subject, builder,
materials, invocation — and signs it. Executed 2026-08-07 against a locally built API
image: verifying it against the image it names passes; against a different image the
digest does not match; a statement with one material digest edited does not verify.

The predicate name says what this is not, in the artefact itself:
`korpus.dev/provenance/v1-local-unattested-builder`. A signature made on the machine that
did the build proves the statement was not altered and proves nothing about whether the
build was honest — a hosted runner and a key in a KMS are what separate those, and neither
exists here. Claiming a SLSA level would be a claim about a build platform that is a
laptop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "scripts/build_provenance.py"


def _run(arguments: list[str], key: Path) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(TOOL), *arguments, "--key-file", str(key)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        timeout=300,
    )
    payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    return completed.returncode, payload


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "provenance.key"
    path.write_text("c" * 64, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def statement(tmp_path: Path) -> Path:
    """A statement built by hand rather than from a live image.

    Docker is not a test dependency: a suite that skips when the daemon is absent has a
    property nobody notices is untested. What is under test here is the signature and the
    comparison, and both work on a document.
    """
    path = tmp_path / "statement.json"
    body = {
        "schema_version": 1,
        "predicate_type": "korpus.dev/provenance/v1-local-unattested-builder",
        "built_at": "2026-08-07T00:00:00+00:00",
        "subject": {"name": "korpus-api:test", "digest": {"sha256": "a" * 64}},
        "builder": {"id": "local-workstation", "attested": False, "meaning": "..."},
        "materials": {"apps/api/Dockerfile": "b" * 64},
        "invocation": {"command": "docker buildx build"},
    }
    import hashlib
    import hmac as hmac_module

    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body["hmac_sha256"] = hmac_module.new(
        ("c" * 64).encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def test_an_intact_statement_verifies(statement: Path, key: Path) -> None:
    code, result = _run(["verify", "--statement", str(statement)], key)

    assert result["signature_intact"] is True, result
    assert code == 0, result


def test_editing_a_material_digest_breaks_the_signature(statement: Path, key: Path) -> None:
    """The material list is the answer to "built from what". An unsigned list is a note."""
    payload = json.loads(statement.read_text(encoding="utf-8"))
    payload["materials"]["apps/api/Dockerfile"] = "0" * 64
    statement.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    code, result = _run(["verify", "--statement", str(statement)], key)

    assert code != 0
    assert result["signature_intact"] is False


def test_another_key_does_not_verify(statement: Path, tmp_path: Path, key: Path) -> None:
    """The control: without it, "the signature holds" could mean "nothing is checked"."""
    other = tmp_path / "other.key"
    other.write_text("d" * 64, encoding="utf-8")

    code, result = _run(["verify", "--statement", str(statement)], other)

    assert code != 0
    assert result["signature_intact"] is False


def test_the_statement_says_the_builder_is_unattested(statement: Path, key: Path) -> None:
    """A green verification must not read as a claim the build was honest."""
    _, result = _run(["verify", "--statement", str(statement)], key)

    assert result["builder_attested"] is False
    assert "unattested" in str(result["predicate_type"])
    assert any("honesty" in item or "honest" in item for item in result["external"]), result
