#!/usr/bin/env python3
"""Заморозити кандидата: тотожність стає незмінною, знаменник гейтів — сталим.

Перехід VERIFIED → RELEASE_CANDIDATE виконує наявна машина станів
(`korpus.application.release_state_machine`); цей скрипт — її вхід із дерева. Він не
створює нового протоколу: він обчислює ТОТОЖНІСТЬ кандидата й вписує її в
`RELEASE_ENVELOPE.json`, який уже є єдиним конвертом релізу.

Заморозка законна лише тоді, коли кожна умова ВИМІРЯНА на цьому ж дереві:

* дерево чисте — інакше заморожується не те, що перевірялось;
* лан релізу пройшов і його звіт про ЦЕЙ коміт;
* модель впевненості каже PASS — жоден блокуючий замінник не невиконаний;
* жоден предикат із дорогою в продакшен не блокує (OWNER_ACTION і доведене
  NOT_IN_RELEASE_PATH не блокують — див. `production_hard_predicates`).

Після заморозки знаменник обов'язкових гейтів не росте: новий гейт можна додати лише
доведенням, що він охороняє вже обов'язковий інваріант, і це рішення людини, не лану.

    freeze_release_candidate.py [--selftest] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.release_state_machine import (  # noqa: E402
    PromotionPolicy,
    ReleaseIdentity,
    ReleaseRecord,
    ReleaseStage,
    evaluate_promotion,
)

ENVELOPE = ROOT / "RELEASE_ENVELOPE.json"
PROFILE = ROOT / "config/assurance/production-v1.json"
LOCKS = ("apps/api/requirements.runtime.lock", "apps/api/requirements.dev.lock")
MIGRATIONS = ROOT / "apps/api/migrations/versions"
_REVISION = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", re.M)
_DOWN = re.compile(r"^down_revision(?::\s*str\s*\|\s*None)?\s*=\s*[\"']([^\"']+)[\"']", re.M)


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def schema_revision(directory: Path = MIGRATIONS) -> str:
    """Голова міграцій: ревізія, на яку не посилається жодна інша як на попередню.

    Не «найбільший номер у назві»: назва — оформлення, а батьківство — факт. Дві голови
    означають розкол, і сказати про це треба, а не обрати одну.
    """
    revisions: dict[str, str | None] = {}
    for path in sorted(directory.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        found = _REVISION.search(text)
        if not found:
            continue
        parent = _DOWN.search(text)
        revisions[found.group(1)] = parent.group(1) if parent else None
    parents = {parent for parent in revisions.values() if parent}
    heads = sorted(set(revisions) - parents)
    if len(heads) != 1:
        return f"AMBIGUOUS:{','.join(heads) or 'none'}"
    return heads[0]


def corpus_identity(envelope: dict[str, Any]) -> dict[str, Any]:
    """Тотожність корпусу, який ОБСЛУГОВУЄТЬСЯ, а не того, який зручно порахувати."""
    candidate = envelope.get("release_candidate", {})
    topology = candidate.get("deployment_topology", {}) if isinstance(candidate, dict) else {}
    database = topology.get("database", {}) if isinstance(topology, dict) else {}
    relative = str(database.get("path") or "var/runtime/corpus-v6-20260807/korpus.db")
    path = ROOT / relative
    if not path.is_file():
        return {"path": relative, "state": "ВІДСУТНІЙ"}
    return {
        "path": relative,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "state": "ВИМІРЯНО",
    }


def blockers(root: Path = ROOT) -> list[str]:
    """Кожна умова заморозки, яка НЕ виконана. Порожній перелік — не за замовчуванням."""
    problems: list[str] = []
    if [line for line in _git("status", "--porcelain").splitlines() if line]:
        problems.append("дерево брудне: заморожувалось би не те, що перевірялось")

    lane = _json(root / "var/release-verify.json")
    if not lane:
        problems.append("звіту лану релізу немає — заморозка без прогону")
    else:
        problems.extend(_lane_problems(lane, root))

    model = _json(root / "var/assurance-model-independence.json")
    if not model:
        problems.append("звіту моделі впевненості немає")
    elif str(model.get("status")) != "PASS":
        problems.append(f"модель впевненості: {model.get('unmet_blocking_substitutes')}")

    predicates = _json(root / "reports/PRODUCTION_HARD_PREDICATES.json")
    states = predicates.get("states") or []
    if not states:
        problems.append("звіту про предикати продакшену немає")
    blocking = [str(item.get("id")) for item in states if item.get("blocks_candidate")]
    if blocking:
        problems.append(f"предикати блокують кандидата: {blocking}")
    return problems


def _lane_problems(lane: dict[str, Any], root: Path) -> list[str]:
    """Чому звіт лану НЕ кредитує заморозку. Порожній перелік — не за замовчуванням.

    Прив'язка за ДАЙДЖЕСТОМ ДЖЕРЕЛА, а не за комітом. Коміт доказу чіпає лише
    `reports/` і `var/`, яких немає в обсязі дайджесту, тож лан, знятий до нього,
    описує ТЕ САМЕ джерело. Вимога збігу комітів означала б вимогу лану, після якого
    нічого не комітили, — а докази комітити треба.

    Обсяг звіту перевіряється окремо. `run_release_verify.py --closure-only` пише ТОЙ
    САМИЙ файл із тими самими полями `status`/`stopped_at`, але лише про дві цілі; без
    цієї умови заморозка прийняла б замикання за повний лан. Названо незалежною
    верифікацією 03.09.2026: сьогодні цей шлях ховають інші блокери, і саме тому його
    треба закрити ДО того, як їх не стане.
    """
    problems: list[str] = []
    if str(lane.get("status")) != "PASS":
        problems.append(f"лан релізу: {lane.get('status')} (спинився на {lane.get('stopped_at')})")
    carried = str(lane.get("source_digest") or "")
    current = compute_source_digest(root)
    if not carried:
        problems.append("звіт лану не несе дайджесту джерела — не прив'язаний до кандидата")
    elif carried != current:
        problems.append(f"лан про джерело {carried[:8]}, дерево {current[:8]}")
    # Шлях відносний НАВМИСНО. `ENVELOPE` — абсолютний, а в pathlib `root / <абсолютний>`
    # дорівнює абсолютному: корінь ігнорується, і негативний контроль читав би СПРАВЖНІЙ
    # конверт репозиторію замість свого. Проба, яка не керує змінною, яку називає, не є
    # пробою: випадок «замикання замість повного лану» був зелений із хибної причини —
    # він порівнювався з реальними вісімнадцятьма цілями, а не зі своїми двома.
    candidate = (_json(root / "RELEASE_ENVELOPE.json") or {}).get("release_candidate", {})
    mandatory = {str(name) for name in candidate.get("mandatory_gate_set") or []}
    measured = {str(step.get("target")) for step in lane.get("steps") or []}
    if not mandatory:
        problems.append("конверт не називає обов'язкового набору цілей")
    elif mandatory - measured:
        problems.append(f"звіт лану не покриває обов'язкових цілей: {sorted(mandatory - measured)}")
    return problems


def identity(envelope: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    return {
        "candidate_commit": _git("rev-parse", "HEAD"),
        "source_digest": compute_source_digest(root),
        "production_profile_digest": _sha256(PROFILE),
        "dependency_lock_digest": hashlib.sha256(
            b"".join((root / name).read_bytes() for name in LOCKS)
        ).hexdigest(),
        "schema_revision": schema_revision(),
        "corpus_identity": corpus_identity(envelope),
        "frozen_at": datetime.now(UTC).isoformat(),
    }


def promotion(envelope: dict[str, Any], stamp: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Перехід виконує НАЯВНА машина станів; тут лише її вхід."""
    release = ReleaseIdentity(
        release=str(envelope["release"]),
        source_digest=str(stamp["source_digest"]),
        evidence_digest=hashlib.sha256(
            json.dumps(stamp, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    )
    record = ReleaseRecord(
        identity=release, stage=ReleaseStage.VERIFIED, author_subject="korpus-release-executor"
    )
    verdict = evaluate_promotion(
        record,
        ReleaseStage.RELEASE_CANDIDATE,
        PromotionPolicy(verification_gates=(), candidate_gates=(), production_gates=()),
        {},
        verifier_subject="korpus-release-verifier",
    )
    return verdict.allowed, verdict.failures


def selftest() -> int:
    """Негативні контролі: заморозка мусить відмовляти, а не «намагатися»."""
    import tempfile

    failures: list[str] = []
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("лану немає", {}, "звіту лану релізу немає"),
        (
            "лан про чуже джерело",
            {"var/release-verify.json": {"status": "PASS", "source_digest": "b" * 64}},
            "лан про джерело",
        ),
        (
            "замикання замість повного лану — не покриває обов'язкових цілей",
            {
                "var/release-verify.json": {
                    "status": "PASS",
                    "source_digest": compute_source_digest(ROOT),
                    "steps": [{"target": "operational-gate"}, {"target": "lane-report"}],
                },
                "RELEASE_ENVELOPE.json": {
                    "release_candidate": {"mandatory_gate_set": ["api-test", "validate"]}
                },
            },
            "не покриває обов'язкових цілей",
        ),
        (
            "конверт без обов'язкового набору — тепер ДОСЯЖНО",
            {
                "var/release-verify.json": {
                    "status": "PASS",
                    "source_digest": compute_source_digest(ROOT),
                    "steps": [{"target": "api-test"}],
                },
                "RELEASE_ENVELOPE.json": {"release_candidate": {"mandatory_gate_set": []}},
            },
            "конверт не називає обов'язкового набору цілей",
        ),
        (
            "лан без дайджесту джерела",
            {"var/release-verify.json": {"status": "PASS", "steps": []}},
            "не несе дайджесту джерела",
        ),
        (
            "лан не PASS",
            {"var/release-verify.json": {"status": "FAIL"}},
            "лан релізу: FAIL",
        ),
        (
            "модель впевненості не PASS",
            {
                "var/release-verify.json": {"status": "PASS"},
                "var/assurance-model-independence.json": {
                    "status": "FAIL",
                    "unmet_blocking_substitutes": ["SI-5"],
                },
            },
            "модель впевненості",
        ),
        (
            "предикат блокує",
            {
                "var/release-verify.json": {"status": "PASS"},
                "var/assurance-model-independence.json": {"status": "PASS"},
                "reports/PRODUCTION_HARD_PREDICATES.json": {
                    "states": [{"id": "live_postgres_rls", "blocks_candidate": True}]
                },
            },
            "предикати блокують",
        ),
    ]
    with tempfile.TemporaryDirectory() as raw:
        for index, (name, files, expected) in enumerate(cases):
            sub = Path(raw) / f"case-{index}"
            for relative, payload in files.items():
                target = sub / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload), encoding="utf-8")
            found = blockers(sub)
            if not any(expected in problem for problem in found):
                failures.append(f"{name}: очікувалось «{expected}», отримано {found}")
    revision = schema_revision()
    if not revision or revision.startswith("AMBIGUOUS"):
        failures.append(f"голова міграцій не одна: {revision}")
    print(
        json.dumps(
            {
                "selftest": "PASS" if not failures else "FAIL",
                "cases": len(cases) + 1,
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
    parser.add_argument("--dry-run", action="store_true", help="показати вирок, не писати")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    envelope = _json(ENVELOPE)
    candidate = envelope.get("release_candidate", {})
    refusals = blockers()
    stamp = identity(envelope)
    allowed, promotion_failures = promotion(envelope, stamp)
    if not allowed:
        refusals.extend(promotion_failures)
    verdict = {
        "schema": "korpus.release-freeze.v1",
        "release": envelope.get("release"),
        "status": "FROZEN" if not refusals else "REFUSED",
        "identity": stamp,
        "blockers": refusals,
        "mandatory_gate_set": candidate.get("mandatory_gate_set", []),
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    if refusals or arguments.dry_run:
        return 1 if refusals else 0
    candidate["identity"] = stamp
    candidate["state"] = "RELEASE_CANDIDATE"
    candidate["frozen"] = True
    candidate["readiness"] = "READY_FOR_OWNER_APPROVAL"
    envelope["release_candidate"] = candidate
    ENVELOPE.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
