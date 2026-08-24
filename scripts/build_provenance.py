#!/usr/bin/env python3
"""Say what an artefact was built from, sign it, and refuse to deploy what does not verify.

SUP-003. The pipeline produces SBOMs; nothing signed them, nothing tied them to the image
they describe, and nothing checked either before a deployment. An SBOM that travels beside
an image without being bound to it answers "what is in some image", and the deployment
question is "what is in *this* one".

The statement follows the shape of SLSA provenance — subject, builder, materials,
invocation — because that vocabulary already means something to whoever reads it, and
because the fields are the right ones: what was produced, by what, from which inputs.
This is not a SLSA attestation and does not claim a level: a level is a claim about the
build *platform*, and this platform is a laptop.

What the signature proves: the statement was not altered by anyone without the key. What
it does not prove: that the build was honest. A key on the same machine as the builder
signs whatever the builder says. Splitting those is what a KMS and a hosted runner are
for, and both are named as external in the report rather than implied by a green check.

    build_provenance.py attest --image korpus-api:local --sbom api-sbom.cdx.json --out ...
    build_provenance.py verify --statement ... --image korpus-api:local
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: The predicate name says what this is and what it is not, in the artefact itself, so a
#: reader who finds it in six months does not have to trust a commit message.
PREDICATE = "korpus.dev/provenance/v1-local-unattested-builder"


def _key(path: Path | None) -> bytes:
    if path is not None:
        return path.read_bytes().strip()
    material = os.environ.get("KORPUS_PROVENANCE_HMAC_KEY", "")
    if not material:
        raise SystemExit(
            "no signing key: pass --key-file or set KORPUS_PROVENANCE_HMAC_KEY. An "
            "unsigned statement is a note, and a note can be replaced by another note."
        )
    return material.encode("utf-8")


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sign(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command, capture_output=True, text=True, check=False, cwd=ROOT, timeout=300
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _image_digest(image: str) -> str:
    """The image's own content id, which is what a deployment actually pulls."""
    digest = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    if not digest:
        raise SystemExit(f"no local image {image}: build it before attesting to it")
    return digest


def _materials() -> dict[str, Any]:
    """What the build consumed, at the granularity a reader can check.

    The lock files by digest rather than by name: "requirements.runtime.lock" identifies
    a file, and the question a reader has is whether it is the same file.
    """
    materials: dict[str, Any] = {}
    for relative in (
        "apps/api/requirements.runtime.lock",
        "apps/api/requirements.dev.lock",
        "apps/api/Dockerfile",
        "apps/web/Dockerfile",
        "docker-compose.yml",
    ):
        path = ROOT / relative
        if path.is_file():
            materials[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    commit = _run(["git", "rev-parse", "HEAD"])
    if commit:
        materials["git.commit"] = commit
        materials["git.dirty"] = bool(_run(["git", "status", "--porcelain"]))
    return materials


def attest(arguments: argparse.Namespace) -> int:
    key = _key(arguments.key_file)
    subject: dict[str, Any] = {
        "name": arguments.image,
        "digest": {"sha256": _image_digest(arguments.image).removeprefix("sha256:")},
    }
    if arguments.sbom:
        sbom = Path(arguments.sbom)
        if not sbom.is_file():
            raise SystemExit(f"no SBOM at {sbom}")
        # Bound to the image by being inside the signed statement. An SBOM travelling
        # beside an image answers "what is in some image".
        subject["sbom"] = {
            "path": sbom.name,
            "sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        }

    statement = {
        "schema_version": 1,
        "predicate_type": PREDICATE,
        "built_at": datetime.now(UTC).isoformat(),
        "subject": subject,
        "builder": {
            "id": "local-workstation",
            "attested": False,
            "meaning": (
                "The build ran on the same machine that holds the signing key, so the "
                "signature proves the statement was not altered and proves nothing about "
                "whether the build was honest. A hosted runner and a KMS are what "
                "separate those, and neither is present."
            ),
        },
        "materials": _materials(),
        "invocation": {"command": arguments.command or "docker buildx build"},
    }
    signed = {**statement, "hmac_sha256": _sign(statement, key)}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(signed, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(signed, ensure_ascii=False, indent=2))
    return 0


def verify(arguments: argparse.Namespace) -> int:
    key = _key(arguments.key_file)
    statement = json.loads(arguments.statement.read_text(encoding="utf-8"))
    recorded = str(statement.pop("hmac_sha256", ""))
    intact = hmac.compare_digest(recorded, _sign(statement, key))

    result: dict[str, Any] = {
        "statement": str(arguments.statement),
        "signature_intact": intact,
        "predicate_type": statement.get("predicate_type"),
        "builder_attested": bool(statement.get("builder", {}).get("attested")),
    }

    if arguments.image:
        # The check that makes this a gate rather than a file: the image about to be
        # deployed must be the image the statement describes.
        actual = _image_digest(arguments.image).removeprefix("sha256:")
        expected = str(statement.get("subject", {}).get("digest", {}).get("sha256", ""))
        result["image"] = arguments.image
        result["image_digest_matches"] = bool(expected) and actual == expected
    if arguments.sbom:
        sbom = Path(arguments.sbom)
        recorded_sbom = statement.get("subject", {}).get("sbom", {})
        result["sbom_matches"] = sbom.is_file() and hashlib.sha256(
            sbom.read_bytes()
        ).hexdigest() == recorded_sbom.get("sha256")

    material_drift = [
        relative
        for relative, digest in (statement.get("materials") or {}).items()
        if relative not in {"git.commit", "git.dirty"}
        and (ROOT / relative).is_file()
        and hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest
    ]
    result["materials_changed_since_build"] = material_drift

    checks = [intact, *(value for key_, value in result.items() if key_.endswith("_matches"))]
    result["status"] = "PASS" if all(checks) else "FAIL"
    result["external"] = [
        "A signature made on the build machine proves integrity, not honesty. A hosted "
        "runner and a key in a KMS are what separate the two.",
        "Nothing here is a SLSA level: a level is a claim about the build platform.",
    ]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    attester = subparsers.add_parser("attest")
    attester.add_argument("--image", required=True)
    attester.add_argument("--sbom")
    attester.add_argument("--command")
    attester.add_argument("--key-file", type=Path)
    attester.add_argument("--out", type=Path, required=True)
    attester.set_defaults(handler=attest)

    verifier = subparsers.add_parser("verify")
    verifier.add_argument("--statement", type=Path, required=True)
    verifier.add_argument("--image")
    verifier.add_argument("--sbom")
    verifier.add_argument("--key-file", type=Path)
    verifier.set_defaults(handler=verify)

    arguments = parser.parse_args()
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    sys.exit(main())
