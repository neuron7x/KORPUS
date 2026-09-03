from __future__ import annotations

import json
from pathlib import Path

from korpus.application.production_assurance import evaluate_production_assurance

ROOT = Path(__file__).resolve().parents[3]
PROFILE = json.loads((ROOT / "config/assurance/production-v1.json").read_text())


def _gate(gate_id: str, **extra: object) -> dict[str, object]:
    return {
        "gate_id": gate_id,
        "status": "PASS",
        "source_tree_sha256": "s",
        "release": "v",
        **extra,
    }


def test_production_assurance_requires_every_gate_and_declared_evidence_class() -> None:
    """Клас доказу мусить збігатися з ОГОЛОШЕНИМ у профілі — тепер внутрішнім.

    03.09.2026 дві політики зведено в одну: зовнішня незалежність NOT_PERFORMED і не
    блокує, її замінює виконуваний внутрішній доказ. Умова «клас збігається» лишилась
    дослівно тією самою — змінилось лише те, ЯКИЙ клас оголошений.
    """
    gates = {gate: _gate(gate) for gate in PROFILE["required_gates"]}
    gates["redteam"]["evidence_class"] = "INTERNAL_ADVERSARIAL_CAMPAIGN"
    gates["redteam"]["attestation_verified"] = False
    gates["redteam"]["trusted_signer"] = False
    gates["tevv"]["environment_class"] = "PRODUCTION_LIKE"
    gates["tevv"]["independent_class"] = "INTERNAL_STRUCTURALLY_SEPARATED"
    gates["tevv"]["checks"] = {"independent_class": True, "assessor_trusted_signer": False}
    gates["postgres_security"]["backend"] = "postgresql"
    gates["supply_chain"]["completeness"] = "COMPLETE"
    gates["mutation"]["scope"] = "FULL_CATALOGUE"
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert verdict.passed, verdict.failures


def test_redteam_of_the_wrong_class_cannot_promote_production() -> None:
    """Будь-який клас, крім оголошеного, відхиляється — і слабший, і «сильніший»."""
    gates = {gate: _gate(gate) for gate in PROFILE["required_gates"]}
    gates["redteam"]["evidence_class"] = "INTERNAL"
    gates["tevv"]["environment_class"] = "PRODUCTION"
    gates["tevv"]["independent_class"] = "INTERNAL_STRUCTURALLY_SEPARATED"
    gates["tevv"]["checks"] = {"independent_class": True, "assessor_trusted_signer": False}
    gates["postgres_security"]["backend"] = "postgresql"
    gates["supply_chain"]["completeness"] = "COMPLETE"
    gates["mutation"]["scope"] = "FULL_CATALOGUE"
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert not verdict.passed
    assert "redteam.independent" in verdict.failures


def test_stale_gate_digest_is_rejected_even_if_it_says_pass() -> None:
    gates = {gate: _gate(gate) for gate in PROFILE["required_gates"]}
    gates["redteam"]["evidence_class"] = "INTERNAL_ADVERSARIAL_CAMPAIGN"
    gates["redteam"]["attestation_verified"] = False
    gates["redteam"]["trusted_signer"] = False
    gates["tevv"]["environment_class"] = "PRODUCTION"
    gates["tevv"]["independent_class"] = "INTERNAL_STRUCTURALLY_SEPARATED"
    gates["tevv"]["checks"] = {"independent_class": True, "assessor_trusted_signer": False}
    gates["postgres_security"]["backend"] = "postgresql"
    gates["supply_chain"]["completeness"] = "COMPLETE"
    gates["mutation"]["scope"] = "FULL_CATALOGUE"
    gates["authorization"]["source_tree_sha256"] = "old"
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert "authorization.source_bound" in verdict.failures


def _sound_gates() -> dict[str, dict[str, object]]:
    gates = {gate: _gate(gate) for gate in PROFILE["required_gates"]}
    gates["redteam"]["evidence_class"] = "INTERNAL_ADVERSARIAL_CAMPAIGN"
    gates["redteam"]["attestation_verified"] = False
    gates["redteam"]["trusted_signer"] = False
    gates["tevv"]["environment_class"] = "PRODUCTION"
    gates["tevv"]["independent_class"] = "INTERNAL_STRUCTURALLY_SEPARATED"
    gates["tevv"]["checks"] = {"independent_class": True, "assessor_trusted_signer": False}
    gates["postgres_security"]["backend"] = "postgresql"
    gates["supply_chain"]["completeness"] = "COMPLETE"
    gates["mutation"]["scope"] = "FULL_CATALOGUE"
    return gates


def test_non_postgres_backend_cannot_promote_production() -> None:
    gates = _sound_gates()
    gates["postgres_security"]["backend"] = "sqlite"
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert "postgres.real_backend" in verdict.failures


def test_partial_supply_chain_evidence_cannot_promote_production() -> None:
    gates = _sound_gates()
    gates["supply_chain"]["completeness"] = "SOURCE_ONLY"
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert "supply_chain.complete" in verdict.failures


def test_partial_mutation_scope_cannot_promote_production() -> None:
    gates = _sound_gates()
    gates["mutation"]["scope"] = "PROBE"
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert "mutation.full_catalogue" in verdict.failures


def test_internal_campaign_cannot_call_itself_external_independent() -> None:
    """Внутрішній доказ, названий зовнішнім, відхиляється — і це той самий інваріант.

    Доти тут перевірялось, що САМООГОЛОШЕНА зовнішня команда без довіреного підпису не
    проходить. Після злиття політик зовнішнього класу профіль не вимагає ВЗАГАЛІ, тож
    небезпека перевернулась: тепер зловживанням є гейт, який називає внутрішню кампанію
    EXTERNAL_INDEPENDENT. Модель урядування забороняє це дослівно.
    """
    gates = _sound_gates()
    gates["redteam"]["evidence_class"] = "EXTERNAL_INDEPENDENT"
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert "redteam.independent" in verdict.failures
    assert not verdict.passed


def test_tevv_claiming_a_trusted_external_assessor_is_rejected() -> None:
    """Дзеркальний бік: оцінювач, названий довіреним ззовні, коли такого немає."""
    gates = _sound_gates()
    gates["tevv"]["checks"] = {"independent_class": True, "assessor_trusted_signer": True}
    verdict = evaluate_production_assurance(PROFILE, gates, source_digest="s", release="v")
    assert "tevv.trusted_assessor" in verdict.failures


def test_engineering_gate_uses_evidence_digest_not_git_digest_domain() -> None:
    text = (ROOT / "scripts" / "run_engineering_production_gate.py").read_text(encoding="utf-8")
    assert 'report.get("evidence_source_sha256") == source' in text
    assert 'report.get("source_tree_sha256") == source' not in text
    assert "report_path = (ROOT / args.report).resolve()" in text


def test_production_gate_generators_share_the_working_tree_digest_contract() -> None:
    scripts = (
        "export_authorization_matrix.py",
        "export_state_contracts.py",
        "run_engineering_production_gate.py",
        "run_exact_environment_gate.py",
        "run_inference_security_gate.py",
        "run_mutation_production_gate.py",
        "run_postgres_security_gate.py",
        "run_pytest_campaign.py",
        "run_reliability_gate.py",
        "run_supply_chain_gate.py",
        "run_tevv_production_gate.py",
        "verify_observability_contract.py",
        "validate_external_redteam_evidence.py",
    )
    for name in scripts:
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "source_tree_digest" not in text, name
        assert "compute_source_digest" in text, name
