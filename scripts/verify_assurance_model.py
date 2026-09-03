#!/usr/bin/env python3
"""Структурна незалежність замінює організаційну ЛИШЕ поки її замінники виконані.

Owner оголосив 03.09.2026: зовнішнього незалежного оцінювача в проєкті немає й він не є
доступним ресурсом. Тримати його блокуючою умовою означало б мати гейт, якого ніхто не
може пройти, — а такий гейт прибирають, а не задовольняють.

Заміна законна рівно тому, що вона НЕ послаблення. Зникла умова, якої не можна
задовольнити наявними ресурсами; жодна умова, яку МОЖНА задовольнити, не знята. Цей
гейт існує, щоб друге твердження було перевіреним, а не обіцяним: якщо структурний
замінник не виконаний, реліз блокує ВІН, і блокує так само твердо.

## Прив'язка до стану — без неї гейт читав власне оголошення

Перша редакція (03.09.2026, ранок) читала артефакти замінників як факти: файл є і
каже PASS — замінник виконаний. Незалежна верифікація тієї ж години провела три
отрути по даних, і всі три пройшли: `var/clean-clone.json` про ЧУЖИЙ коміт давав
SI-6 SATISFIED; засвідчення, написане самим виконавцем, давало SI-1 і SI-2
SATISFIED; звіт живості з одним вигаданим гейтом давав SI-3 SATISFIED. Тепер кожен
артефакт мусить нести `commit` або `source_digest` і збігатися з деревом; артефакт
без прив'язки — NOT_MEASURED, з чужою — NOT_SATISFIED. «State mismatch invalidates
authority» — не гасло, а перший рядок кожної перевірки.

## Межа, названа чесно: SI-1 і SI-2

На одній машині під одним користувачем файлова система не розрізняє, хто написав
засвідчення. Тому «виконавець ≠ верифікатор» і «окремий контекст» тримаються на
ОГОЛОШЕННІ, а механіка перевіряє лише те, що може: за засвідченням стоїть артефакт
верифікатора з правильним дайджестом, про ЦЕЙ коміт, зі станом PASS. Стан цих двох
замінників ніколи не буває `SATISFIED` — лише `SATISFIED_BY_DECLARATION`, і це слово
виходить у кожен звіт. Інваріант «заміна не послаблює» для них тримається на честі,
не на коді; писати інакше означало б брехати про власну силу.

## Чого цей гейт НЕ робить

Він не звітує зовнішню незалежність як пройдену. Її стан лишається `NOT_PERFORMED`, і це
видно в кожному звіті. Невиконане не стає виконаним від того, що перестало блокувати —
інакше ми б відтворили рівно ту ваду, проти якої КОРПУС і будується.

    verify_assurance_model.py [--selftest] [--out ФАЙЛ]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "config/governance/assurance-model.json"
sys.path.insert(0, str(ROOT / "apps/api/src"))

#: Стани замінника. `NOT_SATISFIED` блокує; `NOT_MEASURED` теж блокує, бо невимірене не
#: є виконаним; розрізняються тим, що друге називає брак ВИМІРУ, а не брак факту.
#: `SATISFIED_BY_DECLARATION` не блокує, але ніколи не пишеться як `SATISFIED`: це стан
#: замінника, який механіка перевірити не може і тримає на оголошенні.
SATISFIED = "SATISFIED"
SATISFIED_BY_DECLARATION = "SATISFIED_BY_DECLARATION"
NOT_SATISFIED = "NOT_SATISFIED"
NOT_MEASURED = "NOT_MEASURED"
MET = frozenset({SATISFIED, SATISFIED_BY_DECLARATION})

Verdict = tuple[str, str]
Identity = dict[str, str]
Check = Callable[[Path, Identity], Verdict]


def _json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def identity(root: Path) -> Identity:
    """Тотожність дерева: коміт і дайджест джерела. Порожній рядок — не обчислено."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()
    digest = ""
    try:
        from korpus.application.provenance import compute_source_digest
    except ImportError:
        # Чуже дерево без пакета: дайджесту НЕМАЄ, і це стан «не виміряно», не збій.
        # Ширше `except` тут ловило б і ProvenanceError («джерело змінилося під час
        # хешування»), і OSError — справжні збої, які мовчки читалися б як «не виміряно».
        return {"commit": head, "source_digest": ""}
    digest = str(compute_source_digest(root))
    return {"commit": head, "source_digest": digest}


def bound(report: dict[str, Any], who: Identity, what: str) -> Verdict | None:
    """None, якщо звіт описує ЦЕ дерево; інакше стан і причина.

    Прив'язка — за `commit` або за `provenance.source_digest` / `source_digest`.
    Звіт без жодного з них не прив'язаний ні до чого, тобто не є виміром цього дерева.
    """
    commit = str(report.get("commit") or "")
    provenance = report.get("provenance")
    digest = str(
        (provenance.get("source_digest") if isinstance(provenance, dict) else None)
        or report.get("source_digest")
        or ""
    )
    if not commit and not digest:
        return NOT_MEASURED, f"{what}: звіт не несе ні commit, ні source_digest — не прив'язаний"
    if commit and commit != who["commit"]:
        return NOT_SATISFIED, f"{what}: звіт про {commit[:8]}, HEAD {who['commit'][:8]}"
    if digest and not commit and not who["source_digest"]:
        return NOT_MEASURED, f"{what}: дайджест дерева не обчислено, звірити нема з чим"
    if digest and who["source_digest"] and digest != who["source_digest"]:
        return NOT_SATISFIED, (
            f"{what}: дайджест звіту {digest[:8]}, дерева {who['source_digest'][:8]}"
        )
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attestation(root: Path) -> dict[str, Any] | None:
    return _json(root / "var/production/verifier-attestation.json")


def _verifier_artefact(root: Path, attestation: dict[str, Any], who: Identity) -> str | None:
    """Причина відмови, або None, якщо за засвідченням стоїть артефакт верифікатора."""
    relative = str(attestation.get("verifier_report") or "")
    declared = str(attestation.get("verifier_report_sha256") or "")
    if not relative or not declared:
        return "засвідчення не називає артефакт верифікатора і його дайджест"
    path = root / relative
    if not path.is_file():
        return f"артефакт верифікатора {relative} відсутній"
    actual = _sha256(path)
    if actual != declared:
        return f"дайджест артефакта {actual[:8]} не збігається з засвідченим {declared[:8]}"
    report = _json(path)
    if report is None:
        return f"артефакт верифікатора {relative} не є звітом"
    unbound = bound(report, who, "артефакт верифікатора")
    if unbound is not None:
        return unbound[1]
    if str(report.get("status")) != "PASS":
        return f"артефакт верифікатора каже {report.get('status')}, не PASS"
    return None


def si1_executor_is_not_verifier(root: Path, who: Identity) -> Verdict:
    """Верифікацію виконав ІНШИЙ агент, ніж той, що робив зміну.

    Предикат, не правило в документі — але предикат про ОГОЛОШЕННЯ. Механіка звіряє
    сторони, кандидата й артефакт верифікатора; що сторони справді різні, вона знати
    не може, тому найкращий стан тут — SATISFIED_BY_DECLARATION.
    """
    attestation = _attestation(root)
    if attestation is None:
        return NOT_MEASURED, "засвідчення верифікатора відсутнє"
    executor = str(attestation.get("executor_agent") or "")
    verifier = str(attestation.get("verifier_agent") or "")
    candidate = str(attestation.get("candidate_commit") or "")
    if not executor or not verifier or not candidate:
        return NOT_SATISFIED, "засвідчення не називає обидві сторони й кандидата"
    if executor == verifier:
        return NOT_SATISFIED, f"виконавець і верифікатор — одна сторона: {executor}"
    if candidate != who["commit"]:
        return NOT_SATISFIED, f"засвідчення про {candidate[:8]}, а HEAD {who['commit'][:8]}"
    missing = _verifier_artefact(root, attestation, who)
    if missing is not None:
        return NOT_SATISFIED, missing
    return SATISFIED_BY_DECLARATION, (
        f"{verifier} перевірив роботу {executor} на {candidate[:8]}; артефакт "
        f"{attestation['verifier_report']} прив'язаний до HEAD. Різність сторін ОГОЛОШЕНА."
    )


def si2_separate_context(root: Path, who: Identity) -> Verdict:
    attestation = _attestation(root)
    if attestation is None:
        return NOT_MEASURED, "засвідчення верифікатора відсутнє"
    context = str(attestation.get("verifier_context") or "")
    if not context:
        return NOT_SATISFIED, "засвідчення не називає контексту верифікатора"
    if context == str(attestation.get("executor_context") or ""):
        return NOT_SATISFIED, "верифікатор працював у контексті виконавця"
    missing = _verifier_artefact(root, attestation, who)
    if missing is not None:
        return NOT_SATISFIED, missing
    return SATISFIED_BY_DECLARATION, f"контекст верифікатора {context}; окремість ОГОЛОШЕНА"


def _liveness_expectations(root: Path) -> tuple[dict[str, str], dict[str, str], set[str]] | None:
    """Очікуваний вирок кожного гейта, його причина і ПОВНА множина оголошених гейтів."""
    try:
        import yaml

        config = yaml.safe_load(
            (root / "config/operations/gate-liveness.yaml").read_text(encoding="utf-8")
        )
    except (OSError, ImportError, ValueError):
        return None
    expected: dict[str, str] = {}
    reasons: dict[str, str] = {}
    declared: set[str] = set()
    for gate in config.get("gates", ()):
        name = str(gate["name"])
        declared.add(name)
        if gate.get("expected"):
            expected[name] = str(gate["expected"])
            reasons[name] = str(gate.get("expected_reason") or "")
    return expected, reasons, declared


def _expectation_problem(expected: dict[str, str], reasons: dict[str, str]) -> str | None:
    """Очікуваний вирок береться з конфігу. Дефолт — ARMED; інше мусить нести написану
    причину і вкладатись у стелю: «очікувано червоний» без стелі — спосіб зняти вимогу."""
    ceiling = int(_model_field("expected_non_armed_ceiling", 0))
    non_armed = sorted(name for name, want in expected.items() if want != "ARMED")
    if len(non_armed) > ceiling:
        return f"гейтів з очікуванням ≠ ARMED {len(non_armed)} > стелі {ceiling}"
    unreasoned = [name for name in non_armed if len(reasons.get(name, "").strip()) < 40]
    if unreasoned:
        return f"очікування без написаної причини: {unreasoned}"
    return None


def si3_adversarial(root: Path, who: Identity) -> Verdict:
    """Гейти мусять мати ДОВЕДЕНУ здатність відхилити — усі оголошені, на цьому дереві."""
    report = _json(root / "var/liveness-all.json")
    if report is None:
        return NOT_MEASURED, "звіту про живість гейтів немає або він старої форми (список)"
    unbound = bound(report, who, "звіт живості")
    if unbound is not None:
        return unbound
    gates = [item for item in report.get("gates") or [] if isinstance(item, dict)]
    if not gates:
        return NOT_MEASURED, "звіт про живість порожній"
    expectations = _liveness_expectations(root)
    if expectations is None:
        return NOT_MEASURED, "конфіг живості не прочитано — очікування невідомі"
    expected, reasons, declared = expectations
    measured = {str(item.get("gate")) for item in gates}
    absent = sorted(declared - measured)
    if absent:
        return NOT_SATISFIED, f"звіт не міряє оголошених гейтів: {absent}"
    problem = _expectation_problem(expected, reasons)
    if problem is not None:
        return NOT_SATISFIED, problem
    mismatched = [
        f"{item.get('gate')}: {item.get('verdict')} замість {expected.get(str(item.get('gate')), 'ARMED')}"
        for item in gates
        if str(item.get("verdict")) != expected.get(str(item.get("gate")), "ARMED")
    ]
    if mismatched:
        return NOT_SATISFIED, "; ".join(mismatched[:3])
    return SATISFIED, f"{len(gates)} гейтів мають очікуваний вирок на {who['commit'][:8]}"


def _status_report(
    path: Path, who: Identity, what: str
) -> tuple[dict[str, Any] | None, Verdict | None]:
    report = _json(path)
    if report is None:
        return None, (NOT_MEASURED, f"{what}: звіту немає")
    unbound = bound(report, who, what)
    if unbound is not None:
        return None, unbound
    return report, None


def si4_negative_controls(root: Path, who: Identity) -> Verdict:
    report, refusal = _status_report(
        root / "var/selftest-coverage.json", who, "покриття самоперевірками"
    )
    if report is None:
        return refusal or (NOT_MEASURED, "")
    if str(report.get("status")) != "PASS":
        return NOT_SATISFIED, f"покриття самоперевірками: {report.get('status')}"
    return SATISFIED, "кожен скрипт із --selftest виконується на цьому дереві"


def si5_mutation(root: Path, who: Identity) -> Verdict:
    report, refusal = _status_report(
        root / "reports/MUTATION_FULL_CATALOGUE_CURRENT.json", who, "каталог мутантів"
    )
    if report is None:
        return refusal or (NOT_MEASURED, "")
    survived, invalid = report.get("survived") or [], report.get("invalid") or []
    over = report.get("mutation_score_over_catalogue")
    if survived or invalid or over != 1.0:
        return NOT_SATISFIED, f"вижили {len(survived)}, invalid {len(invalid)}, score {over}"
    return SATISFIED, f"{report.get('killed')}/{report.get('mutants')} убито, знаменник цілий"


def si6_clean_room(root: Path, who: Identity) -> Verdict:
    report, refusal = _status_report(root / "var/clean-clone.json", who, "чистий клон")
    if report is None:
        return refusal or (NOT_MEASURED, "")
    if str(report.get("status")) != "PASS":
        return NOT_SATISFIED, f"відтворення: {report.get('status')}"
    return SATISFIED, f"кандидат {who['commit'][:8]} відтворюється з чистого клону"


def si7_ci_hard_gates(root: Path, who: Identity) -> Verdict:
    report, refusal = _status_report(root / "var/ci-mirror.json", who, "дзеркало CI")
    if report is None:
        return refusal or (NOT_MEASURED, "")
    if str(report.get("status")) != "PASS":
        return NOT_SATISFIED, f"дзеркало CI: {report.get('status')}"
    return SATISFIED, "кожна команда лану виконується в конвеєрі тією самою командою"


def si8_runtime_evidence(root: Path, who: Identity) -> Verdict:
    report, refusal = _status_report(
        root / "var/serving-freshness.json", who, "свіжість обслуговування"
    )
    if report is None:
        return refusal or (NOT_MEASURED, "")
    if str(report.get("status")) != "MEASURED":
        return NOT_MEASURED, (
            f"свіжість обслуговування {report.get('status')}: процесів {report.get('processes')}"
        )
    if report.get("stale") or report.get("rate") != 1.0:
        return NOT_SATISFIED, f"процеси, старші за код: {report.get('stale')}"
    return SATISFIED, "процеси, що обслуговують, несуть поточний код"


CHECKS: dict[str, Check] = {
    "SI-1": si1_executor_is_not_verifier,
    "SI-2": si2_separate_context,
    "SI-3": si3_adversarial,
    "SI-4": si4_negative_controls,
    "SI-5": si5_mutation,
    "SI-6": si6_clean_room,
    "SI-7": si7_ci_hard_gates,
    "SI-8": si8_runtime_evidence,
}


def _model_field(name: str, default: Any) -> Any:
    model = _json(MODEL) or {}
    return model.get(name, default)


def assess(root: Path = ROOT, who: Identity | None = None) -> dict[str, Any]:
    model = _json(MODEL)
    if model is None:
        return {
            "schema": "korpus.assurance-model.v1",
            "status": "FAIL",
            "detail": "моделі впевненості немає в дереві",
        }
    who = who or identity(root)
    names = {item["id"]: item["name"] for item in model["structural_independence_substitutes"]}
    blocking = {
        item["id"] for item in model["structural_independence_substitutes"] if item["blocking"]
    }
    substitutes: dict[str, dict[str, Any]] = {}
    for key, check in CHECKS.items():
        state, detail = check(root, who)
        substitutes[key] = {
            "name": names.get(key, key),
            "state": state,
            "detail": detail,
            "blocking": key in blocking,
        }
    unmet = sorted(k for k, v in substitutes.items() if v["blocking"] and v["state"] not in MET)
    declared = sorted(k for k, v in substitutes.items() if v["state"] == SATISFIED_BY_DECLARATION)
    return {
        "schema": "korpus.assurance-model.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "commit": who["commit"],
        "source_digest": who["source_digest"],
        "model": model["model"],
        "release_authority": model["release_authority"]["holder"],
        # Стан зовнішньої незалежності виходить у КОЖЕН звіт і ніколи не є PASS.
        "external_independent_assurance": {
            "status": model["external_independent_assurance"]["status"],
            "blocking": model["external_independent_assurance"]["blocking"],
        },
        "substitutes": substitutes,
        "unmet_blocking_substitutes": unmet,
        "satisfied_by_declaration_only": declared,
        "status": "PASS" if not unmet else "FAIL",
        "interpretation": (
            "Структурна незалежність замінює організаційну. Заміна дійсна лише поки кожен "
            "блокуючий замінник виконаний НА ЦЬОМУ дереві; артефакт про інший коміт не "
            "рахується. Невиконаний замінник блокує реліз так само твердо, як блокувала б "
            "відсутня зовнішня сторона. Замінники в satisfied_by_declaration_only тримаються "
            "на оголошенні, не на механіці. Зовнішня незалежність лишається NOT_PERFORMED."
        ),
    }


# ------------------------------------------------------------------ негативні контролі

_WHO: Identity = {"commit": "a" * 40, "source_digest": "d" * 64}
_OTHER = "b" * 40
_LIVENESS_CONFIG = (
    "gates:\n- name: g1\n- name: g2\n  expected: ONE_WAY_FAIL\n  expected_reason: >-\n    "
    + "x" * 60
    + "\n"
)
_SAME_SIDE = {"executor_agent": "a", "verifier_agent": "a", "candidate_commit": _WHO["commit"]}
_FORGED = {
    "executor_agent": "opus",
    "verifier_agent": "fable",
    "candidate_commit": _WHO["commit"],
    "executor_context": "A",
    "verifier_context": "B",
}
_ARTEFACT = {"schema": "x", "status": "PASS", "commit": _WHO["commit"]}
_FOREIGN_ARTEFACT = {**_ARTEFACT, "commit": _OTHER}


def _digest_of(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


_COMPLETE = {
    **_FORGED,
    "verifier_report": "var/v.json",
    "verifier_report_sha256": _digest_of(_ARTEFACT),
}
_ATTESTATION = "var/production/verifier-attestation.json"
_LIVENESS = "var/liveness-all.json"
_LIVENESS_YAML = "config/operations/gate-liveness.yaml"
_CATALOGUE = "reports/MUTATION_FULL_CATALOGUE_CURRENT.json"
_FULL_LIVENESS = [{"gate": "g1", "verdict": "ARMED"}, {"gate": "g2", "verdict": "ONE_WAY_FAIL"}]
_CLEAN_CATALOGUE = {
    "survived": [],
    "invalid": [],
    "mutation_score_over_catalogue": 1.0,
    "killed": 2,
    "mutants": 2,
}

#: (назва, замінник, очікуваний стан, файли піддерева). Таблиця — і є доказ: три отрути
#: з незалежної верифікації 03.09.2026 названі P1–P3, решта стережуть прив'язку.
_POISONS: list[tuple[str, str, str, dict[str, Any]]] = [
    ("самозасвідчення відхилено", "SI-1", NOT_SATISFIED, {_ATTESTATION: _SAME_SIDE}),
    ("контекст без оголошення не окремий", "SI-2", NOT_SATISFIED, {_ATTESTATION: _SAME_SIDE}),
    *[(f"{key}: відсутній артефакт → NOT_MEASURED", key, NOT_MEASURED, {}) for key in CHECKS],
    (
        "засвідчення без артефакта верифікатора — ОТРУТА P2",
        "SI-1",
        NOT_SATISFIED,
        {_ATTESTATION: _FORGED},
    ),
    (
        "повне засвідчення — лише BY_DECLARATION, ніколи SATISFIED",
        "SI-1",
        SATISFIED_BY_DECLARATION,
        {_ATTESTATION: _COMPLETE, "var/v.json": _ARTEFACT},
    ),
    (
        "артефакт верифікатора про інший коміт",
        "SI-1",
        NOT_SATISFIED,
        {
            _ATTESTATION: {**_COMPLETE, "verifier_report_sha256": _digest_of(_FOREIGN_ARTEFACT)},
            "var/v.json": _FOREIGN_ARTEFACT,
        },
    ),
    (
        "клон PASS про ЧУЖИЙ коміт — ОТРУТА P1",
        "SI-6",
        NOT_SATISFIED,
        {"var/clean-clone.json": {"status": "PASS", "commit": _OTHER}},
    ),
    (
        "клон PASS без commit — не прив'язаний",
        "SI-6",
        NOT_MEASURED,
        {"var/clean-clone.json": {"status": "PASS"}},
    ),
    (
        "клон PASS про цей коміт",
        "SI-6",
        SATISFIED,
        {"var/clean-clone.json": {"status": "PASS", "commit": _WHO["commit"]}},
    ),
    (
        "живість старої форми (список) — ОТРУТА P3",
        "SI-3",
        NOT_MEASURED,
        {_LIVENESS: [{"gate": "x", "verdict": "ARMED"}], _LIVENESS_YAML: _LIVENESS_CONFIG},
    ),
    (
        "живість не міряє оголошеного гейта",
        "SI-3",
        NOT_SATISFIED,
        {
            _LIVENESS: {"commit": _WHO["commit"], "gates": _FULL_LIVENESS[:1]},
            _LIVENESS_YAML: _LIVENESS_CONFIG,
        },
    ),
    (
        "живість повна й очікувана",
        "SI-3",
        SATISFIED,
        {
            _LIVENESS: {"commit": _WHO["commit"], "gates": _FULL_LIVENESS},
            _LIVENESS_YAML: _LIVENESS_CONFIG,
        },
    ),
    (
        "живість про інший коміт",
        "SI-3",
        NOT_SATISFIED,
        {_LIVENESS: {"commit": _OTHER, "gates": _FULL_LIVENESS}, _LIVENESS_YAML: _LIVENESS_CONFIG},
    ),
    (
        "вижилий мутант блокує",
        "SI-5",
        NOT_SATISFIED,
        {
            _CATALOGUE: {
                **_CLEAN_CATALOGUE,
                "survived": ["M1"],
                "provenance": {"source_digest": _WHO["source_digest"]},
            }
        },
    ),
    (
        "каталог мутантів про інший дайджест",
        "SI-5",
        NOT_SATISFIED,
        {_CATALOGUE: {**_CLEAN_CATALOGUE, "provenance": {"source_digest": "e" * 64}}},
    ),
    (
        "нуль процесів — UNKNOWN не є згодою",
        "SI-8",
        NOT_MEASURED,
        {
            "var/serving-freshness.json": {
                "commit": _WHO["commit"],
                "status": "UNKNOWN",
                "processes": 0,
                "stale": [],
                "rate": None,
            }
        },
    ),
    (
        "дзеркало CI FAIL блокує",
        "SI-7",
        NOT_SATISFIED,
        {"var/ci-mirror.json": {"commit": _WHO["commit"], "status": "FAIL"}},
    ),
]


def _write(root: Path, relative: str, payload: Any) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), "utf-8")


def selftest() -> int:
    """Отрути: заміна не сміє бути тихим послабленням, а гейт — читати оголошення."""
    import tempfile

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        for index, (name, key, expected, files) in enumerate(_POISONS):
            sub = Path(raw) / f"case-{index}"
            for relative, payload in files.items():
                _write(sub, relative, payload)
            state, detail = CHECKS[key](sub, _WHO)
            if state != expected:
                failures.append(f"{name}: {state} ({detail}), очікувалось {expected}")
    # Стеля очікувань ≠ ARMED читається з моделі; поза стелею — відмова.
    if int(_model_field("expected_non_armed_ceiling", 0)) < 1:
        failures.append("модель не оголошує стелі expected_non_armed_ceiling ≥ 1")
    print(
        json.dumps(
            {
                "selftest": "PASS" if not failures else "FAIL",
                "cases": len(_POISONS),
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report = assess()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.out:
        target = arguments.out if arguments.out.is_absolute() else ROOT / arguments.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
