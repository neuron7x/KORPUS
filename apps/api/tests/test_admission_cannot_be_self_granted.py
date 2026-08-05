"""The admission register must not be able to authorise the system that ships it.

`admission.py` states the rule in its own docstring: a ground of class
`external_assessment`, `owner_decision` or `measurement` "may not" be cleared from
inside the repository, "because the whole point of those grounds is that the tree
cannot settle them by writing more code in it".

It did not enforce it. Probed 2026-08-05: setting every open ground to `cleared`, citing
any existing test as evidence, and attaching an attestation that names a document which
does not exist, a sha256 of sixty-four `f`s, a signer called anything at all and a date
in 2030 produced `production_authorized = True` with zero problems reported. Four fields
were required to be *present*; nothing asked whether any of them referred to anything.

That is the highest-consequence defect this repository can have. Every other gate here
reports a property of the software; this one reports whether the software may be used
to answer a soldier's question, and it could be flipped by editing one JSON file in the
same commit as the code it authorises.

These tests state what an attestation has to survive. They are deliberately adversarial
rather than illustrative: each one is a way somebody in a hurry, or somebody under
pressure to ship, would clear a ground they had not actually cleared.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from korpus.application.admission import evaluate_admission, load_register

ROOT = Path(__file__).resolve().parents[3]
REGISTER = ROOT / "config/operations/admission-grounds.json"
REAL_EVIDENCE = "apps/api/tests/test_admission_register.py"


def _register() -> dict[str, Any]:
    return json.loads(REGISTER.read_text(encoding="utf-8"))


def _attested(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    document = tmp_path / "assessment.pdf"
    document.write_bytes(b"independent assessment report, signed")
    attestation: dict[str, Any] = {
        "document": str(document),
        "sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
        "signed_by": "Незалежна організація з безпекової оцінки",
        "signed_at": "2026-08-01",
    }
    attestation.update(overrides)
    return attestation


def _cleared(register: dict[str, Any], ground_id: str, attestation: Any) -> dict[str, Any]:
    forged = copy.deepcopy(register)
    for ground in forged["grounds"]:
        if ground["id"] == ground_id:
            ground["status"] = "cleared"
            ground["evidence"] = [REAL_EVIDENCE]
            ground["attestation"] = attestation
    return forged


def test_the_shipped_register_still_withholds() -> None:
    """The dual. If the register were already authorised, none of this would mean much."""
    verdict = evaluate_admission(ROOT, load_register(REGISTER))

    assert verdict.production_authorized is False
    assert set(verdict.open_grounds) >= {"2.5", "2.6", "2.7", "2.9"}


def test_an_attestation_naming_a_document_that_does_not_exist_is_refused() -> None:
    """The original hole: four fields had to be present, none had to refer to anything."""
    forged = _cleared(
        _register(),
        "2.5",
        {
            "document": "docs/operations/NO_SUCH_ASSESSMENT.pdf",
            "sha256": "f" * 64,
            "signed_by": "anybody",
            "signed_at": "2026-08-01",
        },
    )

    verdict = evaluate_admission(ROOT, forged)

    assert verdict.production_authorized is False
    assert any("does not exist" in problem for problem in verdict.problems), verdict.problems


def test_an_attestation_whose_digest_does_not_match_the_document_is_refused(
    tmp_path: Path,
) -> None:
    """Otherwise the digest field is decoration and any document clears any ground."""
    forged = _cleared(_register(), "2.5", _attested(tmp_path, sha256="a" * 64))

    verdict = evaluate_admission(ROOT, forged)

    assert verdict.production_authorized is False
    assert any("digest" in problem for problem in verdict.problems), verdict.problems


def test_an_attestation_signed_in_the_future_is_refused(tmp_path: Path) -> None:
    """A date nobody has reached yet is not a date somebody signed on."""
    forged = _cleared(_register(), "2.5", _attested(tmp_path, signed_at="2099-01-01"))

    verdict = evaluate_admission(ROOT, forged)

    assert verdict.production_authorized is False
    assert any("future" in problem for problem in verdict.problems), verdict.problems


@pytest.mark.parametrize("signed_at", ["yesterday", "2026-13-01", "", "2026/08/01"])
def test_an_unparseable_signature_date_is_refused(signed_at: str, tmp_path: Path) -> None:
    forged = _cleared(_register(), "2.5", _attested(tmp_path, signed_at=signed_at))

    verdict = evaluate_admission(ROOT, forged)

    assert verdict.production_authorized is False


def test_an_independent_assessment_signed_by_the_engineering_owner_is_refused(
    tmp_path: Path,
) -> None:
    """§2.5 exists because the internal tests were written by the process that wrote
    the code. An assessment signed by that same process clears nothing — it restates
    the position the ground was raised against."""
    forged = _cleared(_register(), "2.5", _attested(tmp_path, signed_by="інженерія"))

    verdict = evaluate_admission(ROOT, forged)

    assert verdict.production_authorized is False
    assert any("independent" in problem for problem in verdict.problems), verdict.problems


def test_a_correctly_attested_ground_is_accepted(tmp_path: Path) -> None:
    """The rules must be satisfiable, or they are a refusal wearing a procedure.

    A real document, a matching digest, a past date and a signer who is not the
    engineering that built the thing: that clears the ground, and the remaining open
    grounds keep the verdict false — which is the correct outcome, not a failure.
    """
    forged = _cleared(_register(), "2.5", _attested(tmp_path))

    verdict = evaluate_admission(ROOT, forged)

    assert "2.5" in verdict.cleared_grounds
    assert not any(problem.startswith("2.5") for problem in verdict.problems), verdict.problems
    assert verdict.production_authorized is False  # 2.6, 2.7, 2.9 remain


def test_clearing_every_ground_with_forged_attestations_still_withholds() -> None:
    """The exact sequence that produced `production_authorized = True` on 2026-08-05."""
    forged = _register()
    for ground in forged["grounds"]:
        if ground["status"] == "open":
            ground["status"] = "cleared"
            ground["evidence"] = [REAL_EVIDENCE]
            ground["attestation"] = {
                "document": "docs/operations/NO_SUCH_DOCUMENT.pdf",
                "sha256": "f" * 64,
                "signed_by": "себе-ж",
                "signed_at": "2030-01-01",
            }

    verdict = evaluate_admission(ROOT, forged)

    assert verdict.production_authorized is False
    assert len(verdict.problems) >= 4, verdict.problems
