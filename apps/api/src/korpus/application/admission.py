"""Whether the system is authorized for production, computed from stated grounds.

`production_authorized` was the literal `False` in the gate result. That is the correct
answer, and it was also unfalsifiable: nothing said what would have to be true instead,
nothing checked whether it had become true, and nobody could tell "still withheld" from
"nobody looked". The admission boundary listed the grounds in prose, and prose is not
something a pipeline can read.

The register (`config/operations/admission-grounds.json`) states each ground with the
class of evidence that clears it and who owns that evidence. This module computes the
verdict from the register, under two rules:

- A ground of class `engineering` may be cleared by tests inside this tree, and the
  tests it cites must exist.
- A ground of class `external_assessment`, `owner_decision` or `measurement` may not.
  Clearing one requires an attestation — a document, its digest, and who signed it —
  because the whole point of those grounds is that the tree cannot settle them by
  writing more code in it. A register entry that claims otherwise is itself a failure,
  not a clearance.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from korpus.application.evidence_registry import verify_references
from korpus.security.attestors import AttestorRegistry

#: Grounds of these classes cannot be cleared from inside the repository.
EXTERNAL_KINDS = frozenset({"external_assessment", "owner_decision", "measurement"})
KNOWN_KINDS = EXTERNAL_KINDS | {"engineering"}
REQUIRED_ATTESTATION_FIELDS = ("document", "sha256", "signed_by", "signed_at")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
ATTESTOR_REGISTRY = Path("config/operations/attestor-keys.json")
#: Signers who cannot make an assessment independent, because they are the assessed.
#: Matched as substrings and case-folded: the register is written in Ukrainian and the
#: point is to refuse the obvious self-signature, not to enumerate every phrasing.
NON_INDEPENDENT_SIGNERS = (
    "інженері",
    "engineering",
    "себе",
    "self",
    "korpus",
    "корпус",
    "neuron7x",
)


@dataclass(frozen=True)
class AdmissionVerdict:
    production_authorized: bool
    open_grounds: tuple[str, ...]
    cleared_grounds: tuple[str, ...]
    problems: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "production_authorized": self.production_authorized,
            "open_grounds": list(self.open_grounds),
            "cleared_grounds": list(self.cleared_grounds),
            "problems": list(self.problems),
        }


def load_register(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
        raise ValueError("unsupported admission register schema")
    if not isinstance(value.get("grounds"), list) or not value["grounds"]:
        raise ValueError("admission register lists no grounds")
    return value


def _attestation_problems(
    root: Path, ground: Mapping[str, Any], registry: AttestorRegistry | None
) -> list[str]:
    """Whether the attestation refers to anything, or is four filled-in fields.

    Until 2026-08-05 this asked only whether the fields were *present*. Setting every
    open ground to `cleared`, citing any existing test, and attaching a document that
    does not exist, a sha256 of sixty-four `f`s and a date in 2030 produced
    `production_authorized = True` with no problems reported — the one verdict in this
    repository that decides whether the system may be used at all, flipped by editing
    one JSON file in the same commit as the code it authorises.

    Four things are checked now, and each corresponds to a way the register could
    otherwise authorise itself.
    """
    identifier = ground.get("id")
    attestation = ground.get("attestation")
    if not isinstance(attestation, Mapping):
        return [
            f"{identifier}: a {ground.get('kind')} ground cannot be cleared from inside "
            "the repository; it needs an attestation naming the document and who signed it"
        ]
    missing = [field for field in REQUIRED_ATTESTATION_FIELDS if not attestation.get(field)]
    if missing:
        return [f"{identifier}: attestation is missing {', '.join(sorted(missing))}"]

    digest = attestation.get("sha256")
    if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        return [f"{identifier}: attestation sha256 is malformed"]

    problems: list[str] = []

    # (1) The document exists. A path nobody can open is a citation of nothing.
    document = Path(str(attestation["document"]))
    resolved = document if document.is_absolute() else root / document
    if not resolved.is_file():
        problems.append(
            f"{identifier}: the attested document does not exist: {attestation['document']}"
        )
    # (2) The digest is of that document. Otherwise the field is decoration and any
    #     document clears any ground.
    elif hashlib.sha256(resolved.read_bytes()).hexdigest() != digest:
        problems.append(
            f"{identifier}: the attestation digest does not match the document it names"
        )

    # (3) The signature date is a real past date. A date nobody has reached is not a
    #     date somebody signed on.
    signed_at = str(attestation["signed_at"])
    try:
        signed = date.fromisoformat(signed_at)
    except ValueError:
        problems.append(f"{identifier}: signed_at is not an ISO date: {signed_at!r}")
    else:
        if signed > date.today():
            problems.append(f"{identifier}: signed_at is in the future: {signed_at}")

    # (4) The signature. Everything above is satisfied by anyone with write access to
    #     this repository: write a PDF, compute its sha256, type an organisation's name
    #     into signed_by. An Ed25519 signature over the attestation's own content is
    #     what the named party has to have produced, and the private key is not here.
    #     The registry is optional at load time so a tree without one still reports the
    #     other four problems rather than crashing; a missing registry cannot clear a
    #     ground, because an unsigned attestation is refused.
    if registry is not None:
        problems.extend(
            registry.verify(
                ground_id=str(identifier),
                ground_kind=str(ground.get("kind")),
                attestation=dict(attestation),
                document_sha256=digest,
            )
        )
    else:
        problems.append(
            f"{identifier}: no attestor registry is configured, so no signature on this "
            "attestation can be verified"
        )

    # (5) An independent assessment is not independent when the engineering that built
    #     the system signs it. §2.5 exists precisely because the internal tests were
    #     written by the process that wrote the code; a self-signed report restates the
    #     position the ground was raised against. Owner decisions are exempt — there the
    #     owner IS the correct signatory, which is the whole difference between the two
    #     classes.
    if ground.get("kind") == "external_assessment":
        signer = str(attestation["signed_by"]).strip().casefold()
        if any(marker in signer for marker in NON_INDEPENDENT_SIGNERS):
            problems.append(
                f"{identifier}: an independent assessment cannot be signed by "
                f"{attestation['signed_by']!r} — that is the party whose work is assessed"
            )
    return problems


def _load_registry(root: Path) -> AttestorRegistry | None:
    path = root / ATTESTOR_REGISTRY
    if not path.is_file():
        return None
    try:
        return AttestorRegistry.load(path)
    except ValueError:
        return None


def evaluate_admission(
    root: Path,
    register: Mapping[str, Any],
    registry: AttestorRegistry | None = None,
) -> AdmissionVerdict:
    """Decide from the register, reporting every reason rather than the first.

    `registry` is read from the tree when not supplied. It is a parameter so a test can
    state what a correctly enrolled attestor would produce without enrolling one here —
    enrolling a key is an act of whoever accepts the system, not an edit a developer
    makes to make a test pass.
    """

    problems: list[str] = []
    open_grounds: list[str] = []
    cleared: list[str] = []
    seen: set[str] = set()
    registry = registry if registry is not None else _load_registry(root)

    for ground in register["grounds"]:
        identifier = str(ground.get("id", "")).strip()
        if not identifier:
            problems.append("a ground has no id")
            continue
        if identifier in seen:
            problems.append(f"{identifier}: listed twice")
        seen.add(identifier)
        kind = ground.get("kind")
        if kind not in KNOWN_KINDS:
            problems.append(f"{identifier}: unknown ground class {kind!r}")
        status = ground.get("status")
        if status not in {"open", "cleared"}:
            problems.append(f"{identifier}: unknown status {status!r}")
            continue
        if status == "open":
            open_grounds.append(identifier)
            continue

        evidence: Iterable[str] = ground.get("evidence") or ()
        if not isinstance(evidence, list) or not evidence:
            problems.append(f"{identifier}: cleared with no evidence cited")
        else:
            problems.extend(
                f"{identifier}: {message}" for message in verify_references(root, evidence)
            )
        if kind in EXTERNAL_KINDS:
            problems.extend(_attestation_problems(root, ground, registry))
        cleared.append(identifier)

    authorized = not open_grounds and not problems
    return AdmissionVerdict(
        production_authorized=authorized,
        open_grounds=tuple(open_grounds),
        cleared_grounds=tuple(cleared),
        problems=tuple(problems),
    )
