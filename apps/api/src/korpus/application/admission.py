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

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from korpus.application.evidence_registry import verify_references

#: Grounds of these classes cannot be cleared from inside the repository.
EXTERNAL_KINDS = frozenset({"external_assessment", "owner_decision", "measurement"})
KNOWN_KINDS = EXTERNAL_KINDS | {"engineering"}
REQUIRED_ATTESTATION_FIELDS = ("document", "sha256", "signed_by", "signed_at")


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


def _attestation_problems(ground: Mapping[str, Any]) -> list[str]:
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
    if not isinstance(digest, str) or len(digest) != 64:
        return [f"{identifier}: attestation sha256 is malformed"]
    return []


def evaluate_admission(root: Path, register: Mapping[str, Any]) -> AdmissionVerdict:
    """Decide from the register, reporting every reason rather than the first."""

    problems: list[str] = []
    open_grounds: list[str] = []
    cleared: list[str] = []
    seen: set[str] = set()

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
            problems.extend(_attestation_problems(ground))
        cleared.append(identifier)

    authorized = not open_grounds and not problems
    return AdmissionVerdict(
        production_authorized=authorized,
        open_grounds=tuple(open_grounds),
        cleared_grounds=tuple(cleared),
        problems=tuple(problems),
    )
