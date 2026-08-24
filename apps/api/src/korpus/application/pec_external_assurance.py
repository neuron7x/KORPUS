from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalAssuranceVerdict:
    admissible: bool
    failures: tuple[str, ...]


def validate_external_assurance(receipt: Mapping[str, object], *, release: str, source_digest: str, trusted_signers: Iterable[str]) -> ExternalAssuranceVerdict:
    trusted = set(trusted_signers)
    checks = {
        "independent": receipt.get("independent") is True,
        "release": str(receipt.get("release", "")) == release,
        "source_digest": str(receipt.get("source_digest", "")) == source_digest,
        "trusted_signer": str(receipt.get("signer_fingerprint", "")) in trusted,
        "blocking_findings_closed": receipt.get("blocking_findings_closed") is True,
    }
    failures = tuple(name for name, ok in checks.items() if not ok)
    return ExternalAssuranceVerdict(not failures, failures)
