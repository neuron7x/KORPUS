"""Withholding must be a decision with listed grounds, not a constant.

`production_authorized` was the literal `False` in the gate result. The answer was
right, and it was also unfalsifiable: nothing said what would have to be true instead,
nothing checked whether it had become true, and no reader could tell "still withheld"
from "nobody looked". The grounds lived in prose, and a pipeline cannot read prose.

The register states each ground with the class of evidence that clears it and who owns
that evidence, and the verdict is computed from it. Two rules carry the weight:

- an `engineering` ground may be cleared by tests in this tree, and the tests it cites
  must exist;
- an `external_assessment`, `owner_decision` or `measurement` ground may not — clearing
  one needs an attestation (document, digest, signatory, date), because the whole point
  of those grounds is that no amount of code written here settles them.

The last test is the one that keeps this honest in the other direction: a verdict that
can only ever be false is as useless as one that is always true.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from korpus.application.admission import evaluate_admission, load_register

from apps.api.tests.test_admission_cannot_be_self_granted import (
    _enrolled_all_roles,
    _enrolled_assessor,
    _sign,
)

REGISTER = Path("config/operations/admission-grounds.json")
ROOT = Path(".")


def _register(**overrides: Any) -> dict[str, Any]:
    value = json.loads(REGISTER.read_text(encoding="utf-8"))
    value.update(overrides)
    return value


def test_the_shipped_register_withholds_and_says_why() -> None:
    verdict = evaluate_admission(ROOT, load_register(REGISTER))

    assert verdict.production_authorized is False
    # 2.9 joined on 2026-08-05: the recovery drill is now measured, and the absence of
    # a declared RTO/RPO became a named ground with an owner instead of a sentence in
    # a runbook that nothing read.
    assert set(verdict.open_grounds) == {
        "2.5",
        "2.6",
        "2.7",
        "2.9",
        "superseded-never-current",
    }
    assert verdict.problems == (), verdict.problems


def test_every_ground_the_register_clears_cites_evidence_that_exists() -> None:
    """§2.8 is cleared by tests; the tests it names have to be real (ADR-0008)."""
    verdict = evaluate_admission(ROOT, load_register(REGISTER))

    assert "2.8" in verdict.cleared_grounds
    assert verdict.problems == ()


def test_an_external_ground_cannot_be_cleared_by_editing_the_register() -> None:
    """The failure mode the register exists to prevent."""
    register = _register()
    for ground in register["grounds"]:
        if ground["id"] == "2.5":
            ground["status"] = "cleared"
            ground["evidence"] = ["apps/api/tests/test_admission_register.py"]

    verdict = evaluate_admission(ROOT, register)

    assert verdict.production_authorized is False
    assert any("attestation" in problem for problem in verdict.problems), verdict.problems


def test_an_external_ground_with_a_complete_attestation_is_accepted(tmp_path) -> None:
    """The mechanism has to be able to accept one, or it is theatre.

    The attested document is written here rather than named: since 2026-08-05 the
    attestation must refer to a file that exists and whose digest matches, so a test
    that names a path nobody wrote would be asserting the old, forgeable contract.
    """
    registry, private = _enrolled_assessor()
    document = tmp_path / "external-assessment-2026-09.pdf"
    document.write_bytes(b"independent assessment report")
    register = _register()
    for ground in register["grounds"]:
        if ground["id"] == "2.5":
            ground["status"] = "cleared"
            ground["evidence"] = ["docs/operations/ADMISSION_BOUNDARY_2026-08-03.md"]
            attestation = {
                "document": str(document),
                "sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
                "signed_by": "Assessment Organisation",
                "signed_at": "2026-08-01",
                "key_id": "assessor-key",
            }
            attestation["signature_b64"] = _sign(private, "2.5", attestation)
            ground["attestation"] = attestation

    verdict = evaluate_admission(ROOT, register, registry)

    assert "2.5" not in verdict.open_grounds
    assert not any("2.5" in problem for problem in verdict.problems), verdict.problems


@pytest.mark.parametrize("field", ["document", "sha256", "signed_by", "signed_at"])
def test_an_incomplete_attestation_is_refused(field: str) -> None:
    register = _register()
    attestation = {
        "document": "external-assessment-2026-09.pdf",
        "sha256": "a" * 64,
        "signed_by": "Assessment Organisation",
        "signed_at": "2026-09-01",
    }
    attestation.pop(field)
    for ground in register["grounds"]:
        if ground["id"] == "2.7":
            ground["status"] = "cleared"
            ground["evidence"] = ["docs/operations/ADMISSION_BOUNDARY_2026-08-03.md"]
            ground["attestation"] = attestation

    verdict = evaluate_admission(ROOT, register)

    assert verdict.production_authorized is False
    assert any(field in problem or "attestation" in problem for problem in verdict.problems)


def test_a_ground_cleared_with_a_test_that_does_not_exist_is_refused() -> None:
    register = _register()
    for ground in register["grounds"]:
        if ground["id"] == "2.8":
            ground["evidence"] = ["apps/api/tests/test_gone.py::test_removed"]

    verdict = evaluate_admission(ROOT, register)

    assert verdict.production_authorized is False
    assert any("does not exist" in problem for problem in verdict.problems), verdict.problems


def test_a_ground_cleared_with_no_evidence_at_all_is_refused() -> None:
    register = _register()
    for ground in register["grounds"]:
        if ground["id"] == "2.8":
            ground["evidence"] = []

    verdict = evaluate_admission(ROOT, register)

    assert verdict.production_authorized is False
    assert any("no evidence" in problem for problem in verdict.problems), verdict.problems


def test_the_verdict_can_be_true_when_every_ground_is_properly_cleared(tmp_path) -> None:
    """The dual control: a verdict that can only be false decides nothing.

    This is the shape a real authorization would have — every ground cleared, external
    ones by attestation, engineering ones by tests that exist. It is constructed here,
    not asserted about the shipped register, which withholds.
    """
    registry, privates = _enrolled_all_roles()
    role_for_kind = {
        "external_assessment": "external_assessor",
        "owner_decision": "process_owner",
        "measurement": "corpus_owner",
    }
    register = _register()
    for ground in register["grounds"]:
        ground["status"] = "cleared"
        ground["evidence"] = ["docs/operations/ADMISSION_BOUNDARY_2026-08-03.md"]
        if ground["kind"] != "engineering":
            document = tmp_path / f"attestation-{ground['id']}.pdf"
            document.write_bytes(f"attestation for {ground['id']}".encode())
            role = role_for_kind[ground["kind"]]
            attestation = {
                "document": str(document),
                "sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
                "signed_by": "Owner",
                "signed_at": "2026-08-01",
                "key_id": f"{role}-key",
            }
            attestation["signature_b64"] = _sign(privates[role], ground["id"], attestation)
            ground["attestation"] = attestation

    verdict = evaluate_admission(ROOT, register, registry)

    assert verdict.problems == (), verdict.problems
    assert verdict.open_grounds == ()
    assert verdict.production_authorized is True
