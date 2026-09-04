from __future__ import annotations

import json
from pathlib import Path

from korpus.application.provenance import compute_source_digest
from korpus.application.release_claims import claim_ledger

from scripts.current_truth_admission import claim_admission_checks, owner_packet_checks
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


# ── Пакет власника: єдиний доказ релізу, який доти не звірявся НІЧИМ.
# Виміряно 04.09.2026: `grep -rl OWNER_PILOT_RELEASE_PACKET scripts/ apps/api/ config/
# Makefile` давав порожньо, а сам пакет називав чотири чужі коміти й жодного разу
# кандидата. Механіка боронила машинні артефакти й лишила людський вхід без нагляду.

PACKET = "reports/OWNER_PILOT_RELEASE_PACKET.md"


def _packet(tmp_path: Path, body: str) -> Path:
    target = tmp_path / PACKET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return tmp_path


def test_a_packet_naming_this_candidate_is_bound(tmp_path: Path) -> None:
    """Позитивне плече: пакет, що називає реліз І дайджест дерева, прив'язаний."""
    root = _packet(tmp_path, "# Пакет\n\nреліз v0.9.7, дерево " + "a" * 64 + "\n")
    checks = owner_packet_checks(root, "v0.9.7", "a" * 64)
    assert checks[f"{PACKET}.present"] is True
    assert checks[f"{PACKET}.release_bound"] is True
    assert checks[f"{PACKET}.source_bound"] is True


def test_a_packet_about_another_tree_is_not_source_bound(tmp_path: Path) -> None:
    """Саме та вада, що була: назва релізу спільна для всіх кандидатів v0.9.7.

    Без дайджесту пакет про попередній коміт виглядав би прив'язаним, і власник
    підписував би стан, якого документ не описує.
    """
    root = _packet(tmp_path, "# Пакет\n\nреліз v0.9.7, дерево " + "b" * 64 + "\n")
    checks = owner_packet_checks(root, "v0.9.7", "a" * 64)
    assert checks[f"{PACKET}.release_bound"] is True
    assert checks[f"{PACKET}.source_bound"] is False


def test_a_packet_about_another_release_is_not_release_bound(tmp_path: Path) -> None:
    root = _packet(tmp_path, "# Пакет\n\nреліз v0.9.6, дерево " + "a" * 64 + "\n")
    checks = owner_packet_checks(root, "v0.9.7", "a" * 64)
    assert checks[f"{PACKET}.release_bound"] is False


def test_an_absent_packet_is_absent_not_silently_fine(tmp_path: Path) -> None:
    """Відсутній пакет — це «власнику нема на чому вирішувати», а не «скарг немає».

    Порожній перелік перевірок читався б як згода: `all([])` істинне.
    """
    checks = owner_packet_checks(tmp_path, "v0.9.7", "a" * 64)
    assert checks == {f"{PACKET}.present": False}
    assert checks[f"{PACKET}.present"] is False


def test_empty_release_or_digest_cannot_bind_anything(tmp_path: Path) -> None:
    """Порожній рядок міститься в будь-якому тексті: без цієї сторожі прив'язка
    задовольнялась би тим, що дайджест не обчислили."""
    root = _packet(tmp_path, "# Пакет без жодних міток\n")
    checks = owner_packet_checks(root, "", "")
    assert checks[f"{PACKET}.release_bound"] is False
    assert checks[f"{PACKET}.source_bound"] is False
