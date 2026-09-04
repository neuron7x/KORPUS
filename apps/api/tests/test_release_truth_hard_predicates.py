from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from korpus.application.production_hard_predicates import (
    evaluate_hard_predicates,
    load_hard_predicate_profile,
)

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "config/assurance/production-hard-predicates-v1.json"


def _release_truth_module():
    path = ROOT / "scripts/generate_release_truth.py"
    spec = importlib.util.spec_from_file_location("generate_release_truth_tested", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_software_artifact_is_internal_blocker(tmp_path: Path) -> None:
    profile = load_hard_predicate_profile(PROFILE)
    mutated = json.loads(json.dumps(profile))
    mutated["predicates"][0]["software_artifacts"].append("definitely/missing/proof-path")
    states = evaluate_hard_predicates(ROOT, mutated, {})
    first = next(state for state in states if state.predicate_id == "external_independent_redteam")
    assert first.software_ready is False
    assert "definitely/missing/proof-path" in first.missing_software_artifacts
    assert first.production_satisfied is False


def test_release_truth_rejects_stale_hard_predicate_report(monkeypatch, tmp_path: Path) -> None:
    module = _release_truth_module()
    report = ROOT / "reports/PRODUCTION_HARD_PREDICATES.json"
    original = report.read_bytes()
    payload = json.loads(original)
    payload["source_tree_sha256"] = "0" * 64
    report.write_text(json.dumps(payload), encoding="utf-8")
    try:
        registry = module._blockers("1" * 64, str(payload.get("release")))
    finally:
        report.write_bytes(original)
    hard = [
        item
        for item in registry["items"]
        if item["id"] in {p["id"] for p in json.loads(PROFILE.read_text())["predicates"]}
    ]
    assert registry["hard_predicate_report_current"] is False
    assert len(hard) == len(json.loads(PROFILE.read_text())["predicates"])
    assert all(item["state"] == "INTERNAL_BLOCKED" for item in hard)
    assert all(item["evidence_current"] is False for item in hard)


def test_release_truth_current_report_preserves_each_external_boundary() -> None:
    module = _release_truth_module()
    report = json.loads((ROOT / "reports/PRODUCTION_HARD_PREDICATES.json").read_text())
    registry = module._blockers(str(report["source_tree_sha256"]), str(report["release"]))
    hard_ids = {p["id"] for p in json.loads(PROFILE.read_text())["predicates"]}
    hard = [item for item in registry["items"] if item["id"] in hard_ids]
    assert registry["hard_predicate_report_current"] is True
    assert len(hard) == len(json.loads(PROFILE.read_text())["predicates"])
    assert all(item["software_ready"] is True for item in hard)
    reported = {item["id"]: item for item in report["states"]}
    assert all(
        item["externally_satisfied"] is reported[item["id"]]["externally_satisfied"]
        for item in hard
    )
    # Виправлено 04.09.2026. Доти тут стояв ДВІЙКОВИЙ поділ: усе незадоволене —
    # EXTERNAL_REQUIRED. Саме він і був вадою: предикат, чия єдина прогалина —
    # застаріла прив'язка доказу, закривається ПЕРЕЗНЯТТЯМ гейта, а не людиною.
    # Тепер стверджується триєдиний поділ, і кожна гілка названа окремо.
    from korpus.application.release_truth import EVIDENCE_BINDING_CHECKS

    for item in hard:
        failed = set(item["failed_external_checks"])
        if item["externally_satisfied"]:
            assert item["state"] == "CLOSED_ANCHORED"
        elif failed and failed <= EVIDENCE_BINDING_CHECKS:
            assert item["state"] == "INTERNAL_STALE_EVIDENCE"
            assert item["machine_closable"] is True
        else:
            assert item["state"] == "EXTERNAL_REQUIRED"
            assert item["machine_closable"] is False
    assert any(item["state"] == "EXTERNAL_REQUIRED" for item in hard)
    # Два числа мусять залишатись роздільними: сума внутрішніх і зовнішніх дорівнює
    # числу незакритих, інакше один клас мовчки поглинув би інший.
    unresolved = sum(1 for item in hard if item["state"] != "CLOSED_ANCHORED")
    assert (
        registry["internal_executable_unresolved"]
        + registry["production_external_or_runtime_unresolved"]
        == unresolved
    )


# ── Класифікація блокерів: «внутрішній» мусить означати «машина може закрити»,
# а не «бракує файла». Виміряно 04.09.2026 на кандидаті d2964c6e: п'ять із дев'яти
# блокуючих предикатів падали ВИКЛЮЧНО на `gate_source_bound`, і всі п'ять читались
# як EXTERNAL_REQUIRED, тобто `internal_executable_unresolved` показував нуль при
# п'яти машинних блокерах. Це число гейтує реліз через `current-truth`.


def _registry_root(tmp_path: Path, failed: list[str], *, artifacts_present: bool = True) -> Path:
    from korpus.application.release_truth import blocker_registry  # noqa: F401

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    first = profile["predicates"][0]
    (tmp_path / "config/assurance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/assurance/production-hard-predicates-v1.json").write_text(
        json.dumps({"predicates": [first]}), encoding="utf-8"
    )
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports/PRODUCTION_HARD_PREDICATES.json").write_text(
        json.dumps(
            {
                "source_tree_sha256": "d" * 64,
                "release": "v0.9.7",
                "states": [
                    {
                        "id": first["id"],
                        "software_ready": artifacts_present,
                        "externally_satisfied": not failed,
                        "failed_external_checks": failed,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _registry(tmp_path: Path, failed: list[str], **kwargs: object) -> dict:
    from korpus.application.release_truth import blocker_registry

    root = _registry_root(tmp_path, failed, **kwargs)  # type: ignore[arg-type]
    return blocker_registry(root, "d" * 64, "v0.9.7")


def test_a_gate_bound_to_another_tree_is_internal_not_external(tmp_path: Path) -> None:
    """Застаріла прив'язка закривається ПЕРЕЗНЯТТЯМ, а не людиною.

    Назвати її зовнішньою означає пообіцяти, що хтось зробить те, що зробить лан,
    і показати нуль там, де лишилась машинна робота.
    """
    registry = _registry(tmp_path, ["gate_source_bound"])
    assert registry["items"][0]["state"] == "INTERNAL_STALE_EVIDENCE"
    assert registry["items"][0]["machine_closable"] is True
    assert registry["internal_executable_unresolved"] == 1
    assert registry["internal_stale_evidence"] == 1
    assert registry["production_external_or_runtime_unresolved"] == 0


def test_a_substantive_external_gap_stays_external(tmp_path: Path) -> None:
    """Негативне плече: названий оцінювач або хмарний збирач машиною не закриваються."""
    registry = _registry(tmp_path, ["assessor_structured"])
    assert registry["items"][0]["state"] == "EXTERNAL_REQUIRED"
    assert registry["items"][0]["machine_closable"] is False
    assert registry["internal_executable_unresolved"] == 0
    assert registry["production_external_or_runtime_unresolved"] == 1


def test_binding_mixed_with_a_substantive_gap_stays_external(tmp_path: Path) -> None:
    """Прив'язка ПЛЮС справжня прогалина — це не машинна робота.

    Перезняття гейта не приведе людину, тож послаблювати вирок через те, що серед
    причин є й прив'язка, було б обміном суворості на зручність.
    """
    registry = _registry(tmp_path, ["gate_source_bound", "builder_provenance_verified"])
    assert registry["items"][0]["state"] == "EXTERNAL_REQUIRED"
    assert registry["internal_executable_unresolved"] == 0


def test_a_missing_software_artifact_is_still_internal_blocked(tmp_path: Path) -> None:
    """Стара поведінка збережена: бракує файла — INTERNAL_BLOCKED, окремим числом."""
    registry = _registry(tmp_path, ["gate_source_bound"], artifacts_present=False)
    assert registry["items"][0]["state"] == "INTERNAL_BLOCKED"
    assert registry["internal_missing_artifact"] == 1
    assert registry["internal_executable_unresolved"] == 1


def test_a_fully_satisfied_predicate_is_closed(tmp_path: Path) -> None:
    """Третє плече: без прогалин предикат закритий, і жодне з чисел не росте."""
    registry = _registry(tmp_path, [])
    assert registry["items"][0]["state"] == "CLOSED_ANCHORED"
    assert registry["internal_executable_unresolved"] == 0
    assert registry["production_external_or_runtime_unresolved"] == 0
