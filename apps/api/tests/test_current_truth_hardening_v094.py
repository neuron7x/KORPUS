from __future__ import annotations

import json
from pathlib import Path

from korpus.application.provenance import compute_source_digest
from korpus.application.release_claims import claim_ledger

from scripts.current_truth_admission import claim_admission_checks
from scripts.current_truth_aliases import alias_checks


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_digest_binds_web_and_ci_release_surfaces(tmp_path: Path) -> None:
    for rel, data in {
        "apps/api/src/korpus/a.py": "x=1\n",
        "apps/web/public/app.js": "export const x=1;\n",
        ".github/workflows/release.yml": "name: release\n",
    }.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")
    first = compute_source_digest(tmp_path)
    (tmp_path / "apps/web/public/app.js").write_text("export const x=2;\n", encoding="utf-8")
    second = compute_source_digest(tmp_path)
    (tmp_path / ".github/workflows/release.yml").write_text("name: hardened\n", encoding="utf-8")
    third = compute_source_digest(tmp_path)
    assert len({first, second, third}) == 3


def test_supported_claim_must_resolve_to_current_evidence(tmp_path: Path) -> None:
    release, digest = "v9", "a" * 64
    ledger = tmp_path / f"reports/release/{release}/final/CLAIM_LEDGER.json"
    _write(ledger, {"claims": [{"status": "SUPPORTED", "evidence": "evidence.json"}]})
    _write(
        tmp_path / "evidence.json",
        {"release": release, "source_tree_sha256": "b" * 64, "status": "PASS"},
    )
    assert (
        claim_admission_checks(tmp_path, release, digest)[
            "CLAIM_LEDGER.supported_evidence_resolves"
        ]
        is False
    )
    _write(
        tmp_path / "evidence.json",
        {"release": release, "source_tree_sha256": digest, "status": "PASS"},
    )
    assert (
        claim_admission_checks(tmp_path, release, digest)[
            "CLAIM_LEDGER.supported_evidence_resolves"
        ]
        is True
    )


def test_alias_checks_bind_git_imports_and_package_build(tmp_path: Path) -> None:
    release, artifact = "v9", "KORPUS_v9.zip"
    _write(tmp_path / "apps/api/src/korpus/release.json", {"distribution_artifact": artifact})
    _write(tmp_path / "RELEASE_ENVELOPE.json", {"release": release})
    report = {"release": release}
    _write(tmp_path / "CANONICAL_RELEASE_REPORT.json", report)
    _write(tmp_path / "reports/CANONICAL_RELEASE_REPORT.json", report)
    _write(
        tmp_path / "FULL_SSOT_PACKAGE_RECEIPT.json",
        {"release": release, "package_role": "FULL_SSOT_CANONICAL"},
    )
    _write(tmp_path / "PACKAGE_BUILD.json", {"release": release})
    for name in ("GITHUB_IMPORT.md", "GITLAB_IMPORT.md"):
        (tmp_path / name).write_text(f"{release} {artifact}\n", encoding="utf-8")
    checks = alias_checks(tmp_path, release)
    assert all(checks.values())
    (tmp_path / "GITHUB_IMPORT.md").write_text(f"{release} stale.zip\n", encoding="utf-8")
    assert alias_checks(tmp_path, release)["GITHUB_IMPORT.md.artifact_bound"] is False


def test_release_claims_use_portable_mutation_evidence(tmp_path: Path) -> None:
    release, digest = "v9", "a" * 64
    ledger = claim_ledger(tmp_path, digest, release)
    mutation = next(claim for claim in ledger["claims"] if claim["id"] == "CLM-MUTATION")
    assert mutation["evidence"] == "reports/MUTATION_FULL_CATALOGUE_CURRENT.json"
    assert not mutation["evidence"].startswith("var/")


def test_source_integrity_claim_uses_a_bound_verification_report(tmp_path: Path) -> None:
    ledger = claim_ledger(tmp_path, "a" * 64, "v9")
    source = next(claim for claim in ledger["claims"] if claim["id"] == "CLM-SOURCE-INTEGRITY")
    assert source["evidence"] == "reports/SOURCE_MANIFEST_VERIFICATION_CURRENT.json"


def _registry(tmp_path: Path, release: str, digest: str, evidence_digest: object) -> Path:
    """Реєстр блокерів, прив'язаний до дерева, з оголошеним (або ні) входом."""
    payload: dict[str, object] = {
        "release": release,
        "source_tree_sha256": digest,
        "hard_predicate_report_current": True,
        "internal_executable_unresolved": 0,
        "items": [],
    }
    if evidence_digest is not None:
        payload["evidence_sha256"] = evidence_digest
    path = tmp_path / f"reports/release/{release}/final/BLOCKER_REGISTRY.json"
    _write(path, payload)
    return path


def test_a_registry_bound_to_the_tree_can_still_be_built_from_stale_evidence(
    tmp_path: Path,
) -> None:
    """ВИМІРЯНО 04.09.2026 на кандидаті f311e83a.

    `BLOCKER_REGISTRY.json` зібрано о 13:20, а його єдиний вхід —
    `reports/PRODUCTION_HARD_PREDICATES.json` — перезібрано о 19:50 і закомічено В ТОМУ
    САМОМУ коміті. Перезбирання реєстру на НЕЗМІННОМУ дереві перевело 7 блокерів
    EXTERNAL_REQUIRED → CLOSED_ANCHORED. Допуск цього не бачив: він звіряв
    `source_tree_sha256`, і той збігався, бо `reports/` навмисно виключено з дайджесту
    дерева. Прив'язка трималась, зміст розійшовся.

    Твердження тут — не про напрямок дрейфу (цього разу він був у безпечний бік), а про
    те, що дрейф був НЕПОМІТНИЙ.
    """
    import hashlib

    from scripts.current_truth_admission import blocker_state_checks

    release, digest = "v9", "a" * 64
    evidence = tmp_path / "reports/PRODUCTION_HARD_PREDICATES.json"
    _write(evidence, {"predicates": []})
    recorded = hashlib.sha256(evidence.read_bytes()).hexdigest()
    _registry(tmp_path, release, digest, {"reports/PRODUCTION_HARD_PREDICATES.json": recorded})

    checks = blocker_state_checks(tmp_path, release, digest)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is True

    # Той самий реєстр, той самий дайджест дерева — і переписаний вхід.
    _write(evidence, {"predicates": [{"id": "x"}]})
    after = blocker_state_checks(tmp_path, release, digest)
    assert after["BLOCKER_REGISTRY.source_bound_current"] is True, "прив'язка до дерева тримається"
    assert after["BLOCKER_REGISTRY.evidence_inputs_current"] is False, "а зміст уже не той"


def test_a_registry_that_does_not_name_its_inputs_is_not_admitted(tmp_path: Path) -> None:
    """Реєстр без переліку входів не каже, з чого зібраний. Невимірене не є пройденим."""
    from scripts.current_truth_admission import blocker_state_checks

    release, digest = "v9", "a" * 64
    _write(tmp_path / "reports/PRODUCTION_HARD_PREDICATES.json", {"predicates": []})
    _registry(tmp_path, release, digest, None)
    checks = blocker_state_checks(tmp_path, release, digest)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False


def test_an_empty_input_list_is_not_agreement(tmp_path: Path) -> None:
    """`all([])` істинне. Порожній перелік входів мусить читатись як «не виміряно»."""
    from scripts.current_truth_admission import blocker_state_checks

    release, digest = "v9", "a" * 64
    _write(tmp_path / "reports/PRODUCTION_HARD_PREDICATES.json", {"predicates": []})
    _registry(tmp_path, release, digest, {})
    checks = blocker_state_checks(tmp_path, release, digest)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False


def test_a_vanished_input_is_not_agreement(tmp_path: Path) -> None:
    """Файл, названий входом і відсутній на диску, — теж розходження, не згода."""
    from scripts.current_truth_admission import blocker_state_checks

    release, digest = "v9", "a" * 64
    _registry(tmp_path, release, digest, {"reports/PRODUCTION_HARD_PREDICATES.json": "b" * 64})
    checks = blocker_state_checks(tmp_path, release, digest)
    assert checks["BLOCKER_REGISTRY.evidence_inputs_current"] is False


def test_the_registry_records_the_digest_of_the_evidence_it_read(tmp_path: Path) -> None:
    """Записаний дайджест мусить бути дайджестом ЗМІСТУ входу, а не сталою."""
    import hashlib

    from korpus.application.release_truth import blocker_registry

    _write(tmp_path / "config/assurance/production-hard-predicates-v1.json", {"predicates": []})
    evidence = tmp_path / "reports/PRODUCTION_HARD_PREDICATES.json"
    _write(evidence, {"predicates": [], "source_tree_sha256": "a" * 64, "release": "v9"})
    built = blocker_registry(tmp_path, "a" * 64, "v9")
    assert built["evidence_sha256"] == {
        "reports/PRODUCTION_HARD_PREDICATES.json": hashlib.sha256(evidence.read_bytes()).hexdigest()
    }
