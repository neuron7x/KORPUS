"""Доказ мусить описувати стан, до якого МОЖНА повернутись.

Виміряно 01.09.2026. `compute_source_digest` рахує РОБОЧЕ дерево; одна правка в
доказовому файлі розводить його з HEAD:

    дерево робоче : e4c4d94295e72fde21477e33
    дерево HEAD   : 9c1960c0158310dca0b694e1

Ніщо в дереві цієї розбіжності не питало. Отже звіт про забезпечення міг бути
виданий, підписаний і опублікований із `source_digest`, якого немає в жодному
коміті: байти, які він описує, існували лише в дереві, якого вже немає.

Тут перевіряється саме ЕКВІВАЛЕНТНІСТЬ двох обчислень, бо вона й є тим, що
робить прив'язку осмисленою: якби дайджест закоміченого рахувався іншою
функцією, розбіжність означала б «інша формула», а не «інший вміст».
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from korpus.application.provenance import EVIDENCE_SOURCE_PATHS, compute_source_digest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from evidence_source_binding import (  # noqa: E402
    committed_evidence_source_digest,
    evidence_source_binding_failure,
)
from snapshot_assurance import SOURCES  # noqa: E402


def _evidence_surface_is_clean() -> bool:
    """Чи має робоче дерево правки ВСЕРЕДИНІ доказової поверхні."""
    changed = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", *EVIDENCE_SOURCE_PATHS],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return changed == ""


def test_the_two_computations_agree_exactly_when_the_surface_is_clean() -> None:
    """Головне твердження, і воно виміряне в ОБИДВА боки.

    Чисте дерево ⇒ числа тотожні. Брудне ⇒ прив'язка мусить це НАЗВАТИ, а не
    мовчати: «однакові» й «не порівнювали» інакше не розрізняються.
    """
    working = compute_source_digest(ROOT)
    committed = committed_evidence_source_digest(root=ROOT)
    if _evidence_surface_is_clean():
        assert working == committed
        assert evidence_source_binding_failure(working, root=ROOT) is None
    else:
        assert evidence_source_binding_failure(working, root=ROOT) == (
            "assurance evidence source digest does not match committed HEAD"
        )


def test_the_committed_digest_binds_to_itself() -> None:
    """Дуал: перевірка, що відмовляє завжди, доводить лише власну поломку."""
    assert (
        evidence_source_binding_failure(committed_evidence_source_digest(root=ROOT), root=ROOT)
        is None
    )


@pytest.mark.parametrize(
    ("claimed", "reason"),
    [
        (None, "assurance evidence source digest is missing or malformed"),
        ("", "assurance evidence source digest is missing or malformed"),
        ("a" * 63, "assurance evidence source digest is missing or malformed"),
        ("z" * 64, "assurance evidence source digest is missing or malformed"),
        (12345, "assurance evidence source digest is missing or malformed"),
        ("a" * 64, "assurance evidence source digest does not match committed HEAD"),
    ],
)
def test_absence_and_mismatch_are_named_apart(claimed: object, reason: str) -> None:
    """«Дайджесту немає» і «дайджест інший» — різні стани.

    Злиття їх в один рядок зробило б відсутність невідрізненною від підміни, а
    це рівно та форма, у якій хибне значення виглядає як відсутнє.
    """
    assert evidence_source_binding_failure(claimed, root=ROOT) == reason


def test_an_unreadable_ref_is_a_refusal_not_a_pass() -> None:
    assert (
        evidence_source_binding_failure("a" * 64, ref="refs/heads/гілка-якої-немає", root=ROOT)
        == "assurance evidence source digest cannot be verified against committed HEAD"
    )


def test_path_git_substitution_cannot_forge_committed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "fake-git-invoked"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\nprintf '%s' invoked > {marker}\nexit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    expected = committed_evidence_source_digest(root=ROOT)

    monkeypatch.setenv("PATH", str(fake_bin))

    assert committed_evidence_source_digest(root=ROOT) == expected
    assert not marker.exists()


def _release_verifier():
    script = ROOT / "scripts" / "verify_release_evidence.py"
    spec = importlib.util.spec_from_file_location("verify_release_evidence_binding_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_fixture(tmp_path: Path, evidence_digest: str) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir()
    assurance_path = reports / "RESEARCH_ASSURANCE_REPORT.json"
    assurance_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_tree_sha256": "tracked-head",
                "evidence_source_sha256": evidence_digest,
            }
        ),
        encoding="utf-8",
    )
    records = []
    for name in (*SOURCES, "RESEARCH_ASSURANCE_REPORT.json"):
        path = reports / name
        if not path.is_file():
            path.write_bytes(f"fixture:{name}\n".encode())
        content = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(tmp_path).as_posix(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    (reports / "ASSURANCE_SNAPSHOT.json").write_text(
        json.dumps(
            {
                "schema": "korpus.assurance-snapshot.v1",
                "status": "PASS",
                "release": "v-test",
                "records": records,
                "limitations": [],
            }
        ),
        encoding="utf-8",
    )
    return reports


def test_release_verifier_rejects_evidence_source_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _release_verifier()
    monkeypatch.setattr(module, "REPORTS", _release_fixture(tmp_path, "a" * 64))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setitem(module.complete_snapshot_records.__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(module, "release_tag", lambda: "v-test")
    monkeypatch.setattr(module, "source_tree_digest", lambda _ref="HEAD": "tracked-head")
    monkeypatch.setattr(
        module,
        "evidence_source_binding_failure",
        lambda _claimed: "assurance evidence source digest does not match committed HEAD",
    )
    assert module.main() == 1


def test_release_verifier_accepts_matching_evidence_source_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _release_verifier()
    monkeypatch.setattr(module, "REPORTS", _release_fixture(tmp_path, "b" * 64))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setitem(module.complete_snapshot_records.__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(module, "release_tag", lambda: "v-test")
    monkeypatch.setattr(module, "source_tree_digest", lambda _ref="HEAD": "tracked-head")
    monkeypatch.setattr(module, "evidence_source_binding_failure", lambda _claimed: None)
    assert module.main() == 0


def test_release_verifier_rejects_an_empty_snapshot_record_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _release_verifier()
    reports = _release_fixture(tmp_path, "b" * 64)
    snapshot = reports / "ASSURANCE_SNAPSHOT.json"
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["records"] = []
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(module, "REPORTS", reports)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setitem(module.complete_snapshot_records.__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(module, "release_tag", lambda: "v-test")
    monkeypatch.setattr(module, "source_tree_digest", lambda _ref="HEAD": "tracked-head")
    monkeypatch.setattr(module, "evidence_source_binding_failure", lambda _claimed: None)
    assert module.main() == 1


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("schema", "wrong.schema"),
        ("bytes", True),
        ("unexpected", "field"),
        ("limitations", True),
        ("limitations", "not-a-list"),
        ("limitations", {}),
        ("limitations", [1]),
    ],
)
def test_release_verifier_rejects_malformed_snapshot_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, value: object
) -> None:
    module = _release_verifier()
    reports = _release_fixture(tmp_path, "b" * 64)
    snapshot = reports / "ASSURANCE_SNAPSHOT.json"
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    target = payload if mutation in {"schema", "limitations"} else payload["records"][0]
    target[mutation] = value
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(module, "REPORTS", reports)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setitem(module.complete_snapshot_records.__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(module, "release_tag", lambda: "v-test")
    monkeypatch.setattr(module, "source_tree_digest", lambda _ref="HEAD": "tracked-head")
    monkeypatch.setattr(module, "evidence_source_binding_failure", lambda _claimed: None)
    assert module.main() == 1


def test_release_verifier_rejects_duplicate_snapshot_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _release_verifier()
    reports = _release_fixture(tmp_path, "b" * 64)
    snapshot = reports / "ASSURANCE_SNAPSHOT.json"
    text = snapshot.read_text(encoding="utf-8")
    snapshot.write_text(
        text.replace('"schema":', '"schema": "wrong.schema", "schema":', 1),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPORTS", reports)
    with pytest.raises(ValueError, match="duplicate key"):
        module.main()


def test_release_verifier_rejects_snapshot_limitation_omission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _release_verifier()
    reports = _release_fixture(tmp_path, "b" * 64)
    assurance = reports / "RESEARCH_ASSURANCE_REPORT.json"
    payload = json.loads(assurance.read_text(encoding="utf-8"))
    payload["limitations"] = ["DO NOT DEPLOY"]
    assurance.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = reports / "ASSURANCE_SNAPSHOT.json"
    snapshot_payload = json.loads(snapshot.read_text(encoding="utf-8"))
    for record in snapshot_payload["records"]:
        if record["path"] == "reports/RESEARCH_ASSURANCE_REPORT.json":
            content = assurance.read_bytes()
            record.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    snapshot.write_text(json.dumps(snapshot_payload), encoding="utf-8")
    monkeypatch.setattr(module, "REPORTS", reports)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setitem(module.complete_snapshot_records.__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(module, "release_tag", lambda: "v-test")
    monkeypatch.setattr(module, "source_tree_digest", lambda _ref="HEAD": "tracked-head")
    monkeypatch.setattr(module, "evidence_source_binding_failure", lambda _claimed: None)
    assert module.main() == 1
