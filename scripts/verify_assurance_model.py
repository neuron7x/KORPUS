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
ENVELOPE = "RELEASE_ENVELOPE.json"
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
        # ДВА різні стани доти мали одну назву. Якщо дайджест джерела той самий,
        # засвідчення застаріло щодо дерева цілком, а не щодо предмета, про який
        # воно свідчить: між такими комітами міг змінитись лише `reports/`.
        # Вирок не мʼякшає — мʼякшає лише мовчання: вічне NOT_SATISFIED без цієї
        # різниці є недосяжністю, яка виглядає як очікування на людину.
        same_source = bool(digest and who["source_digest"] and digest == who["source_digest"])
        if same_source:
            return NOT_SATISFIED, (
                f"{what}: звіт про {commit[:8]}, HEAD {who['commit'][:8]} — "
                f"ДЖЕРЕЛО те саме ({digest[:8]}), застаріла лише прив'язка до коміту; "
                "перезняти на цьому HEAD"
            )
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


def _expectation_problem(
    expected: dict[str, str], reasons: dict[str, str], root: Path = ROOT
) -> str | None:
    """Очікуваний вирок береться з конфігу. Дефолт — ARMED; інше мусить нести написану
    причину і вкладатись у стелю: «очікувано червоний» без стелі — спосіб зняти вимогу.

    Стеля читається з ТОГО дерева, яке судять. Доти вона бралася з робочої копії навіть
    тоді, коли предметом було чуже піддерево, — проба успадковувала умову від середовища
    замість створювати її, і мовчки вироджувалась разом зі зміною моделі.
    """
    ceiling = int(_model_field("expected_non_armed_ceiling", 0, root))
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
    problem = _expectation_problem(expected, reasons, root)
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
    """Каталог мутантів кредитує реліз лише цілим знаменником про ЦЕЙ кандидат.

    Порожній каталог задовольняв би кожну умову про склад: нуль вижилих, нуль invalid,
    ставка 1.0 над нулем результатів. Тому кількість мутантів — теж умова, а не звіт.
    Так само реліз: звіт із чужим тегом описує іншого кандидата навіть на тому ж дереві.
    """
    report, refusal = _status_report(
        root / "reports/MUTATION_FULL_CATALOGUE_CURRENT.json", who, "каталог мутантів"
    )
    if report is None:
        return refusal or (NOT_MEASURED, "")
    unbound = _mutation_release(root, report)
    if unbound is not None:
        return unbound
    return _mutation_denominator(report, str(report.get("release")))


def _mutation_release(root: Path, report: dict[str, Any]) -> Verdict | None:
    """None, якщо каталог про реліз цього кандидата."""
    wanted = _release(root)
    carried = str(report.get("release") or "")
    if not carried:
        return NOT_MEASURED, "каталог не називає релізу — не прив'язаний до кандидата"
    if wanted and carried != wanted:
        return NOT_SATISFIED, f"каталог про реліз {carried}, кандидат {wanted}"
    return None


def _mutation_denominator(report: dict[str, Any], release: str) -> Verdict:
    """Знаменник цілий: не порожній, увесь застосовний і увесь убитий."""
    survived, invalid = report.get("survived") or [], report.get("invalid") or []
    errors = report.get("errors") or []
    mutants = int(report.get("mutants") or 0)
    killed = int(report.get("killed") or 0)
    valid = int(report.get("valid_mutants") or 0)
    over = report.get("mutation_score_over_catalogue")
    if mutants <= 0:
        return NOT_SATISFIED, "нуль мутантів: знаменник порожній, а не цілий"
    if valid != mutants:
        return NOT_SATISFIED, f"каталог неповний: застосовних {valid} із {mutants}"
    if killed != mutants:
        return NOT_SATISFIED, f"убито {killed} із {mutants}"
    if survived or invalid or errors or over != 1.0:
        return NOT_SATISFIED, (
            f"вижили {len(survived)}, invalid {len(invalid)}, помилок {len(errors)}, score {over}"
        )
    return SATISFIED, f"{killed}/{mutants} убито на {release}, знаменник цілий"


def si6_clean_room(root: Path, who: Identity) -> Verdict:
    """PASS чистого клону кредитує рівно ті цілі, які він назвав, і жодної більше.

    Звіт, що каже PASS про один `api-test`, і звіт про повний заморожений набір
    відрізняються ОДНИМ полем; без його читання перший проходив як другий.
    """
    report, refusal = _status_report(root / "var/clean-clone.json", who, "чистий клон")
    if report is None:
        return refusal or (NOT_MEASURED, "")
    if str(report.get("status")) != "PASS":
        return NOT_SATISFIED, f"відтворення: {report.get('status')}"
    required = set(_candidate(root).get("clean_clone_targets") or [])
    if not required:
        return NOT_MEASURED, "конверт релізу не називає обов'язкових цілей чистого клону"
    measured = set(str(report.get("targets") or "").split())
    missing = sorted(required - measured)
    if missing:
        return NOT_SATISFIED, f"клон не ганяв обов'язкових цілей: {missing}"
    return SATISFIED, (
        f"кандидат {who['commit'][:8]} відтворює {len(required)} обов'язкових цілей з клону"
    )


def si7_ci_hard_gates(root: Path, who: Identity) -> Verdict:
    """Дзеркало каже, що конвеєр ЗАПУСТИВ БИ ті самі команди. Це не запуск.

    Дві різні властивості носили одну назву: збіг переліків (структура) і виконання
    на кандидаті (подія). Перша тут — передумова; кредитує реліз лише друга, і лише
    коли конвеєр бігав на ТОМУ САМОМУ коміті. Конвеєр, який не бігав, — NOT_MEASURED:
    невимірене не є пройденим.
    """
    mirror, refusal = _status_report(root / "var/ci-mirror.json", who, "дзеркало CI")
    if mirror is None:
        return refusal or (NOT_MEASURED, "")
    if str(mirror.get("status")) != "PASS":
        return NOT_SATISFIED, f"дзеркало CI: {mirror.get('status')}"
    run, refusal = _status_report(root / "var/ci-run.json", who, "прогін CI")
    if run is None:
        if refusal and refusal[0] == NOT_MEASURED:
            return NOT_MEASURED, f"{refusal[1]}: конвеєр для цього кандидата ще не бігав"
        return refusal or (NOT_MEASURED, "")
    if str(run.get("status")) != "PASS":
        return NOT_SATISFIED, f"прогін CI: {run.get('status')} ({run.get('pipeline')})"
    lanes = [str(name) for name in run.get("completed_jobs") or []]
    required = [str(name) for name in run.get("required_jobs") or []]
    if not required:
        return NOT_MEASURED, "звіт прогону не називає обов'язкових джобів"
    missing = sorted(set(required) - set(lanes))
    if missing:
        return NOT_SATISFIED, f"обов'язкові джоби не завершені: {missing}"
    return SATISFIED, (
        f"конвеєр {run.get('pipeline')} пройшов {len(required)} обов'язкових джобів "
        f"на {who['commit'][:8]}"
    )


def si8_runtime_evidence(root: Path, who: Identity) -> Verdict:
    """Обслуговує ТЕ, що оголошене топологією, і несе код кандидата.

    `absence(stale) => current` — не висновок, а те саме UNKNOWN іншими словами:
    нуль процесів дає порожній перелік старих. Тому кількість процесів і присутність
    оголошених юнітів — окремі умови, а не наслідок ставки.
    """
    report, refusal = _status_report(
        root / "var/serving-freshness.json", who, "свіжість обслуговування"
    )
    if report is None:
        return refusal or (NOT_MEASURED, "")
    if str(report.get("status")) != "MEASURED":
        return NOT_MEASURED, (
            f"свіжість обслуговування {report.get('status')}: процесів {report.get('processes')}"
        )
    processes = int(report.get("processes") or 0)
    if processes <= 0:
        return NOT_MEASURED, "нуль процесів: відсутність предмета не є згодою"
    absent = report.get("units_not_serving")
    if absent is None:
        return NOT_MEASURED, "звіт не міряв оголошених юнітів — старої форми"
    if absent:
        return NOT_SATISFIED, f"оголошені юніти не обслуговують: {absent}"
    if report.get("stale") or report.get("rate") != 1.0:
        return NOT_SATISFIED, f"процеси, старші за код: {report.get('stale')}"
    return SATISFIED, f"{processes} процеси оголошених юнітів несуть код {who['commit'][:8]}"


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


def _model_field(name: str, default: Any, root: Path = ROOT) -> Any:
    model = _json(root / MODEL.relative_to(ROOT)) or {}
    return model.get(name, default)


PRODUCTION_PROFILE = "config/assurance/production-v1.json"
TEVV_PROFILE = "config/assurance/tevv-production-v1.json"
EXTERNAL = "EXTERNAL_INDEPENDENT"


def policy_agreement(root: Path) -> list[str]:
    """Дві політики про одне — дефект, а не думка.

    До 03.09.2026 модель урядування казала «зовнішньої незалежності немає, вона не
    блокує», а профіль продакшену вимагав EXTERNAL_INDEPENDENT redteam і TEVV з
    довіреним підписантом. Обидві були «діючими», і яка з них діяла — залежало від
    того, який скрипт запустили. Тепер розбіжність називає себе сама, і В ОБИДВА
    боки: якщо модель ЗАТЯГНЕ вимогу назад, профіль, що лишився внутрішнім, теж
    буде розбіжністю, а не тихою поблажкою.
    """
    model = _json(root / MODEL.relative_to(ROOT)) if MODEL.is_absolute() else _json(MODEL)
    model = model or {}
    profile = _json(root / PRODUCTION_PROFILE) or {}
    tevv = _json(root / TEVV_PROFILE) or {}
    if not model or not profile:
        return []
    external = model.get("external_independent_assurance") or {}
    blocking = bool(external.get("blocking"))
    requirements = profile.get("external_requirements") or {}
    demands_external = [
        name
        for name in ("redteam_evidence_class", "tevv_independent_class")
        if requirements.get(name) == EXTERNAL
    ]
    demands_trust = [
        name
        for name in ("redteam_trusted_signer_required", "tevv_trusted_assessor_required")
        if bool(requirements.get(name))
    ]
    tevv_external = tevv.get("required_evidence_class") == EXTERNAL
    problems: list[str] = []
    if not blocking:
        if demands_external:
            problems.append(
                f"модель: зовнішня незалежність НЕ блокує; профіль вимагає {demands_external}"
            )
        if demands_trust:
            problems.append(f"профіль вимагає довірених підписантів ззовні: {demands_trust}")
        if tevv_external:
            problems.append("профіль TEVV вимагає класу доказу EXTERNAL_INDEPENDENT")
        if profile.get("governance_authority") != "config/governance/assurance-model.json":
            problems.append("профіль не називає моделі урядування єдиним джерелом")
    else:
        if not demands_external:
            problems.append(
                "модель: зовнішня незалежність БЛОКУЄ; профіль її вже не вимагає — "
                "затягнення моделі не дійшло до профілю"
            )
    return problems


def _at(block: Any, *path: str) -> str:
    """Значення за шляхом, як РЯДОК; будь-який обрив шляху дає порожній рядок."""
    for key in path:
        block = block.get(key) if isinstance(block, dict) else None
    return str(block) if isinstance(block, str) else ""


def topology_agreement(root: Path) -> list[str]:
    """Топологія обслуговування оголошена ДВІЧІ — конверт і профіль мусять збігтися.

    Виміряно 04.09.2026: профіль твердих предикатів казав «топологія обслуговування
    цього релізу — SQLite на loopback», а конверт уже цілий день називав
    `pilot-systemd-postgres-v1` на PostgreSQL. Розбіжність жила в ПРОЗІ, якої не міряв
    ніхто, і саме тому пережила зміну рішення. Тут вона стає станом.
    """
    candidate = _candidate(root)
    topology = candidate.get("deployment_topology")
    profile = _json(root / PRODUCTION_PROFILE)
    if not isinstance(topology, dict) or not profile:
        return []
    problems: list[str] = []
    declared = _at(topology, "database", "backend")
    required = _at(profile, "external_requirements", "postgres_backend")
    if required and declared != required:
        problems.append(f"конверт обслуговує на {declared!r}, профіль вимагає {required!r}")
    excluded = [str(item) for item in topology.get("not_in_this_release") or []]
    if _at(topology, "id") in excluded:
        problems.append(f"топологія {_at(topology, 'id')!r} названа й обраною, і виключеною")
    unit = _at(topology, "api", "unit")
    serving = [str(item) for item in candidate.get("required_serving_units") or []]
    if unit and serving and unit not in serving:
        problems.append(f"юніт топології {unit!r} не серед обов'язкових {serving}")
    return problems


def _envelope(root: Path) -> dict[str, Any]:
    return _json(root / ENVELOPE) or {}


def _release(root: Path) -> str:
    return str(_envelope(root).get("release") or "")


def _candidate(root: Path) -> dict[str, Any]:
    block = _envelope(root).get("release_candidate")
    return block if isinstance(block, dict) else {}


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
    disagreement = policy_agreement(root) + topology_agreement(root)
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
        "policy_disagreement": disagreement,
        "status": "PASS" if not unmet and not disagreement else "FAIL",
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
_MODEL_FILE = "config/governance/assurance-model.json"
#: Стеля — умова проби, а не властивість середовища: кожен випадок несе свою.
_CEILING_ONE = {"expected_non_armed_ceiling": 1}
_CEILING_ZERO = {"expected_non_armed_ceiling": 0}
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
_RELEASE = "v0.9.7"
_ENVELOPE_FILE = "RELEASE_ENVELOPE.json"
_CLEAN_CLONE_TARGETS = ["validate", "api-test"]
_ENVELOPE = {
    "release": _RELEASE,
    "release_candidate": {
        "clean_clone_targets": _CLEAN_CLONE_TARGETS,
        "required_serving_units": ["u.service"],
    },
}
_CLEAN_CATALOGUE = {
    "survived": [],
    "invalid": [],
    "errors": [],
    "mutation_score_over_catalogue": 1.0,
    "killed": 2,
    "mutants": 2,
    "valid_mutants": 2,
    "release": _RELEASE,
    "provenance": {"source_digest": _WHO["source_digest"]},
}
_CLEAN_CLONE = "var/clean-clone.json"
_CI_MIRROR = "var/ci-mirror.json"
_CI_RUN = "var/ci-run.json"
_SERVING = "var/serving-freshness.json"
_MIRROR_PASS = {"commit": _WHO["commit"], "status": "PASS"}
_RUN_PASS = {
    "commit": _WHO["commit"],
    "status": "PASS",
    "pipeline": "https://example/pipelines/1",
    "required_jobs": ["repository:validate"],
    "completed_jobs": ["repository:validate"],
}
_SERVING_PASS = {
    "commit": _WHO["commit"],
    "status": "MEASURED",
    "processes": 2,
    "stale": [],
    "rate": 1.0,
    "units_not_serving": [],
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
            _MODEL_FILE: _CEILING_ONE,
        },
    ),
    (
        "очікуваний провал понад стелею — відмова",
        "SI-3",
        NOT_SATISFIED,
        {
            _LIVENESS: {"commit": _WHO["commit"], "gates": _FULL_LIVENESS},
            _LIVENESS_YAML: _LIVENESS_CONFIG,
            _MODEL_FILE: _CEILING_ZERO,
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
        {_CI_MIRROR: {"commit": _WHO["commit"], "status": "FAIL"}},
    ),
    # --- знаменник мутації: склад без кількості задовольняється порожнечею
    (
        "порожній каталог мутантів — не цілий знаменник",
        "SI-5",
        NOT_SATISFIED,
        {
            _CATALOGUE: {
                **_CLEAN_CATALOGUE,
                "mutants": 0,
                "killed": 0,
                "valid_mutants": 0,
                "mutation_score_over_catalogue": 1.0,
            }
        },
    ),
    (
        "каталог неповний: частина мутантів не застосовна",
        "SI-5",
        NOT_SATISFIED,
        {_CATALOGUE: {**_CLEAN_CATALOGUE, "valid_mutants": 1}},
    ),
    (
        "убито менше, ніж мутантів",
        "SI-5",
        NOT_SATISFIED,
        {_CATALOGUE: {**_CLEAN_CATALOGUE, "killed": 1}},
    ),
    (
        "каталог про ЧУЖИЙ реліз",
        "SI-5",
        NOT_SATISFIED,
        {_CATALOGUE: {**_CLEAN_CATALOGUE, "release": "v0.0.1"}, _ENVELOPE_FILE: _ENVELOPE},
    ),
    (
        "каталог без релізу — не прив'язаний до кандидата",
        "SI-5",
        NOT_MEASURED,
        {
            _CATALOGUE: {k: v for k, v in _CLEAN_CATALOGUE.items() if k != "release"},
            _ENVELOPE_FILE: _ENVELOPE,
        },
    ),
    (
        "каталог цілий і про цей реліз",
        "SI-5",
        SATISFIED,
        {_CATALOGUE: _CLEAN_CATALOGUE, _ENVELOPE_FILE: _ENVELOPE},
    ),
    # --- чистий клон: PASS про ОДНУ ціль ≠ PASS про заморожений набір
    (
        "клон PASS, але ганяв не всі обов'язкові цілі",
        "SI-6",
        NOT_SATISFIED,
        {
            _CLEAN_CLONE: {**_MIRROR_PASS, "targets": "api-test"},
            _ENVELOPE_FILE: _ENVELOPE,
        },
    ),
    (
        "клон PASS без конверта — набір цілей нема з чим звіряти",
        "SI-6",
        NOT_MEASURED,
        {_CLEAN_CLONE: {**_MIRROR_PASS, "targets": "validate api-test"}},
    ),
    (
        "клон PASS на повному наборі",
        "SI-6",
        SATISFIED,
        {
            _CLEAN_CLONE: {**_MIRROR_PASS, "targets": "validate api-test"},
            _ENVELOPE_FILE: _ENVELOPE,
        },
    ),
    # --- CI: дзеркало не є прогоном
    (
        "дзеркало PASS, а конвеєр не бігав — NOT_MEASURED",
        "SI-7",
        NOT_MEASURED,
        {_CI_MIRROR: _MIRROR_PASS},
    ),
    (
        "прогін CI про ЧУЖИЙ коміт",
        "SI-7",
        NOT_SATISFIED,
        {_CI_MIRROR: _MIRROR_PASS, _CI_RUN: {**_RUN_PASS, "commit": _OTHER}},
    ),
    (
        "прогін CI FAIL",
        "SI-7",
        NOT_SATISFIED,
        {_CI_MIRROR: _MIRROR_PASS, _CI_RUN: {**_RUN_PASS, "status": "FAIL"}},
    ),
    (
        "прогін CI PASS, але обов'язковий джоб не завершено",
        "SI-7",
        NOT_SATISFIED,
        {_CI_MIRROR: _MIRROR_PASS, _CI_RUN: {**_RUN_PASS, "completed_jobs": []}},
    ),
    (
        "прогін CI повний на цьому коміті",
        "SI-7",
        SATISFIED,
        {_CI_MIRROR: _MIRROR_PASS, _CI_RUN: _RUN_PASS},
    ),
    # --- рантайм: відсутність предмета не є згодою
    (
        "звіт старої форми без виміру юнітів",
        "SI-8",
        NOT_MEASURED,
        {_SERVING: {k: v for k, v in _SERVING_PASS.items() if k != "units_not_serving"}},
    ),
    (
        "оголошений юніт не обслуговує",
        "SI-8",
        NOT_SATISFIED,
        {_SERVING: {**_SERVING_PASS, "units_not_serving": ["u.service"]}},
    ),
    (
        "процеси, старші за код",
        "SI-8",
        NOT_SATISFIED,
        {_SERVING: {**_SERVING_PASS, "stale": ["1"], "rate": 0.5}},
    ),
    (
        "оголошені юніти обслуговують поточний код",
        "SI-8",
        SATISFIED,
        {_SERVING: _SERVING_PASS},
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
    _MODEL_OPEN = {"external_independent_assurance": {"blocking": False}}
    _MODEL_STRICT = {"external_independent_assurance": {"blocking": True}}
    _OK_REQUIREMENTS: dict[str, Any] = {
        "redteam_evidence_class": "INTERNAL_ADVERSARIAL_CAMPAIGN",
        "tevv_independent_class": "INTERNAL_STRUCTURALLY_SEPARATED",
    }
    _PROFILE_OK: dict[str, Any] = {
        "governance_authority": "config/governance/assurance-model.json",
        "external_requirements": _OK_REQUIREMENTS,
    }
    _PROFILE_SPLIT = {
        "governance_authority": "config/governance/assurance-model.json",
        "external_requirements": {
            "redteam_evidence_class": EXTERNAL,
            "tevv_independent_class": EXTERNAL,
        },
    }
    policy_cases: list[tuple[str, dict[str, Any], bool]] = [
        (
            "злита політика — розбіжностей нема",
            {"model": _MODEL_OPEN, "profile": _PROFILE_OK},
            False,
        ),
        (
            "профіль вимагає зовнішнього, модель — ні",
            {"model": _MODEL_OPEN, "profile": _PROFILE_SPLIT},
            True,
        ),
        (
            "профіль вимагає довіреного підписанта ззовні",
            {
                "model": _MODEL_OPEN,
                "profile": {
                    **_PROFILE_OK,
                    "external_requirements": {
                        **_OK_REQUIREMENTS,
                        "redteam_trusted_signer_required": True,
                    },
                },
            },
            True,
        ),
        (
            "профіль не називає джерела політики",
            {"model": _MODEL_OPEN, "profile": {"external_requirements": {}}},
            True,
        ),
        (
            "модель затягнула вимогу, профіль лишився внутрішнім",
            {"model": _MODEL_STRICT, "profile": _PROFILE_OK},
            True,
        ),
    ]
    with tempfile.TemporaryDirectory() as raw:
        for index, (name, payload, expect_problem) in enumerate(policy_cases):
            sub = Path(raw) / f"policy-{index}"
            _write(sub, "config/governance/assurance-model.json", payload["model"])
            _write(sub, PRODUCTION_PROFILE, payload["profile"])
            problems = policy_agreement(sub)
            if bool(problems) != expect_problem:
                failures.append(f"{name}: {problems}, очікувалось problem={expect_problem}")

    # Топологія оголошена двічі. Кожен випадок СТВОРЮЄ свою розбіжність у власному
    # дереві — успадкувати її від робочого дерева означало б міряти сьогоднішній стан,
    # а не здатність проби почервоніти.
    def _topology(**changes: Any) -> dict[str, Any]:
        block: dict[str, Any] = {
            "deployment_topology": {
                "id": "t1",
                "database": {"backend": "postgresql"},
                "api": {"unit": "u.service"},
                "not_in_this_release": ["compose"],
            },
            "required_serving_units": ["u.service"],
        }
        block["deployment_topology"].update(changes)
        return {"release_candidate": block}

    topology_cases = [
        ("конверт і профіль згодні", _topology(), False),
        ("бекенд конверта інший", _topology(database={"backend": "sqlite"}), True),
        ("топологія і обрана, і виключена", _topology(not_in_this_release=["t1"]), True),
        ("юніт топології не обслуговує", _topology(api={"unit": "other.service"}), True),
    ]
    with tempfile.TemporaryDirectory() as raw:
        for index, (name, envelope, expect_problem) in enumerate(topology_cases):
            sub = Path(raw) / f"topology-{index}"
            _write(sub, ENVELOPE, envelope)
            # Профіль мусить НАЗИВАТИ бекенд, інакше проба інертна: перший її варіант
            # брав `_PROFILE_OK`, де `postgres_backend` немає, і «інший бекенд» давав
            # порожній перелік — фікстура не могла задати змінну, яку перевіряє.
            _write(
                sub,
                PRODUCTION_PROFILE,
                {
                    **_PROFILE_OK,
                    "external_requirements": {**_OK_REQUIREMENTS, "postgres_backend": "postgresql"},
                },
            )
            problems = topology_agreement(sub)
            if bool(problems) != expect_problem:
                failures.append(f"{name}: {problems}, очікувалось problem={expect_problem}")

    # Стеля очікувань ≠ ARMED мусить бути ОГОЛОШЕНА; її значення — ратчет, і нуль
    # законний. Доти тут стояло `< 1`, тобто самоперевірка вимагала лишати місце
    # принаймні для одного очікуваного провалу — і опустити ратчет до нуля означало б
    # зробити гейт червоним за покращення.
    if "expected_non_armed_ceiling" not in (_json(MODEL) or {}):
        failures.append("модель не оголошує стелі expected_non_armed_ceiling")
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
