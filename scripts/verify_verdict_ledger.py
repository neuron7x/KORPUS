#!/usr/bin/env python3
"""A claim about this system's own gates exists in the ledger or it does not exist.

Two sessions spent a day trading findings in chat. Every verdict in that conversation was
real work — poisons run, exit codes read — and none of it survived the conversation. A
statement that lives only in a message is not evidence anybody can check later, and the
same claim gets re-litigated by whoever reads the code next.

The rules are the ones that made the findings worth having:

  1. A verdict on a claim may not come from the actor who made it. Producer and acceptor
     being the same is the failure this whole day was about — an implementation agent
     verifying its own implementation reports what it already believed.
  2. Refuting yourself is exempt. Withdrawing a claim needs no second party, and making it
     hard would only buy silence.
  3. OPEN_FOR_REVIEW from the producer is a request, not a verdict. It stays unsigned.
     CANNOT_ADJUDICATE from a reviewer is the same shape from the other side: a statement
     that this reviewer has no measurement of their own, recorded rather than left silent.
  4. One independent REFUTED outranks any number of ACCEPTED. A defect found once is found.
  5. Append-only. A later entry supersedes an earlier one; nothing is edited or deleted,
     so being wrong earlier stays visible.

    verify_verdict_ledger.py            # human-readable
    verify_verdict_ledger.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".verdict-ledger.jsonl"

#: Словник вироків живе в ОДНОМУ місці — `config/agents/axes.json`, разом із причиною,
#: чому кожне слово там, де воно є. Тут він раніше стояв другою копією, і копії розійшлись
#: рівно так, як розходяться копії: журнал набрав 32 записи `AMENDED`, яких цей файл не
#: знав, і гейт червонів на власній неповноті, а не на дефекті журналу. Друга розбіжність
#: була тихішою й гіршою: `ACKNOWLEDGED` тут закривав твердження, а в реєстрі — ні, з
#: написаною причиною «UNKNOWN не є PASS: вирок, який не може вирішити, не звільняє
#: бюджет». Тобто копія мовчки послаблювала правило, яке інший файл проголошував.
#:
#: Читати критерій із дерева небезпечно тим, що дерево редагується: додав слово в JSON —
#: роззброїв гейт. Тому нижче fail-closed на кожному кроці (немає файла, немає ключа,
#: порожній перелік — відмова, не «дозволено все»), а склад словника закріплено тестом
#: `test_verdict_vocabulary_has_one_source`: змінити його можна, непомітно — ні.
VOCABULARY = ROOT / "config/agents/axes.json"


def _vocabulary() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    if not VOCABULARY.exists():
        raise SystemExit(f"немає словника вироків: {VOCABULARY}")
    try:
        block = json.loads(VOCABULARY.read_text(encoding="utf-8"))["verdict_vocabulary"]
    except (KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"словник вироків нечитний: {exc}") from exc
    settles = frozenset(block.get("settles") or ())
    opens = frozenset(block.get("does_not_settle") or ())
    raising = frozenset(block.get("raising") or ())
    if not settles or not opens:
        raise SystemExit("словник вироків порожній — це відмова, а не дозвіл на все")
    if settles & opens:
        raise SystemExit(f"слово і закриває, і не закриває: {sorted(settles & opens)}")
    if not raising <= settles:
        raise SystemExit(f"піднімає, але не закриває: {sorted(raising - settles)}")
    #: Автор може ЗНИЗИТИ або відкрити власне твердження, підняти — ні. Це не перелік
    #: слів, а різниця: все, що не піднімає. Тоді нове слово успадковує правило само.
    return settles, (settles | opens) - raising, raising


SETTLING, SELF_ALLOWED, RAISING = _vocabulary()
#: Кожне слово, яким узагалі можна винести вирок. Невідоме слово раніше просто не
#: зараховувалось до тих, що закривають твердження, — тобто друкарська помилка в
#: `ACCEPTED` мовчки перетворювала вирок на тишу, і журнал звітував PASS. Тиша в одязі
#: вироку — це рівно те, від чого журнал існує.
#:
#: `CANNOT_ADJUDICATE` — окреме слово, а не мовчання. «Я не маю власного виміру, і
#: підписати означало б перетворити довіру на вирок» — це твердження про рецензента, і
#: воно варте запису: воно каже, ЧОМУ твердження досі не закрите, і кому його показати.
#: Той самий клас, що SCOPE_UNDECLARED у handoff-перевірці: «не можу судити» — інше
#: речення, ніж «усе гаразд», і правдиве з них лише одне.
KNOWN_VERDICTS = SETTLING | SELF_ALLOWED


def _rows() -> list[dict[str, Any]]:
    if not LEDGER.is_file():
        raise SystemExit(f"{LEDGER.name} is missing — a claim nobody recorded is not a claim")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(LEDGER.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{LEDGER.name}:{number} is not JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"{LEDGER.name}:{number} is not an object")
        rows.append(value)
    return rows


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    claims = {str(r["id"]): r for r in rows if r.get("kind") == "claim"}
    verdicts = [r for r in rows if r.get("kind") == "verdict"]
    problems: list[str] = []

    for verdict in verdicts:
        identifier = str(verdict.get("id", ""))
        claim = claims.get(identifier)
        if claim is None:
            problems.append(f"verdict on {identifier!r} names no claim in this ledger")
            continue
        outcome = str(verdict.get("verdict", ""))
        if outcome not in KNOWN_VERDICTS:
            problems.append(
                f"{identifier}: {outcome!r} не є вироком — слово поза словником не закриває "
                f"твердження й не відрізняється від мовчання (відомі: {sorted(KNOWN_VERDICTS)})"
            )
        if claim.get("actor") == verdict.get("actor") and outcome not in SELF_ALLOWED:
            problems.append(
                f"{identifier}: {outcome} signed by the actor who made the claim — "
                "the producer cannot be the acceptor, which is the finding this ledger exists "
                "to keep"
            )
        if not verdict.get("note") and not verdict.get("evidence"):
            problems.append(f"{identifier}: {outcome} carries neither a note nor evidence")

    settled: set[str] = set()
    refuted: set[str] = set()
    for verdict in verdicts:
        identifier = str(verdict.get("id", ""))
        outcome = str(verdict.get("verdict", ""))
        if outcome not in SETTLING:
            continue
        claim = claims.get(identifier)
        if claim is not None and claim.get("actor") != verdict.get("actor"):
            settled.add(identifier)
        if outcome == "REFUTED":
            refuted.add(identifier)

    unsigned = sorted(set(claims) - settled)
    return {
        "status": "PASS" if not problems else "FAIL",
        "claims": len(claims),
        "verdicts": len(verdicts),
        "independently_settled": len(settled),
        "unsigned": unsigned,
        "refuted": sorted(refuted),
        "problems": problems,
    }


def selftest() -> int:
    """Отрути по ДАНИХ: гейт мусить червоніти на кожній, і зеленіти без них.

    Словник тепер читається з дерева, а дерево редагується: додав слово в JSON —
    роззброїв гейт. Тому перевіряється не лише «ловить погане слово», а й те, що
    зіпсований або відсутній словник — це ВІДМОВА, а не дозвіл на все.
    """
    import subprocess

    vocab_backup = VOCABULARY.read_bytes()
    ledger_backup = LEDGER.read_bytes()

    def run() -> int:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            capture_output=True,
            text=True,
            check=False,
        ).returncode

    def poison(name: str, write: object, want_fail: bool = True) -> bool:
        try:
            write()  # type: ignore[operator]
            rc = run()
            ok = (rc != 0) if want_fail else (rc == 0)
            print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: rc={rc}")
            return ok
        finally:
            VOCABULARY.write_bytes(vocab_backup)
            LEDGER.write_bytes(ledger_backup)

    def vocab_with(**over: object) -> object:
        def write() -> None:
            doc = json.loads(vocab_backup)
            doc["verdict_vocabulary"] = {**doc["verdict_vocabulary"], **over}
            VOCABULARY.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

        return write

    results = [
        poison("контроль без отрути", lambda: None, want_fail=False),
        poison(
            "слово поза словником у журналі",
            lambda: LEDGER.write_text(
                ledger_backup.decode("utf-8").replace('"ACCEPTED"', '"ACCEPTAD"', 1),
                encoding="utf-8",
            ),
        ),
        poison("словника немає", VOCABULARY.unlink),
        poison("порожній settles", vocab_with(settles=[])),
        poison("слово і закриває, і ні", vocab_with(does_not_settle=["ACCEPTED"])),
        poison("піднімає, але не закриває", vocab_with(raising=["NEVER_SETTLES"])),
        poison(
            "нечитний JSON",
            lambda: VOCABULARY.write_text("{зламано", encoding="utf-8"),
        ),
    ]
    passed = sum(1 for r in results if r)
    print(f"негативний контроль: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selftest", action="store_true", help="отрути по даних: чи здатен гейт почервоніти"
    )
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    report = evaluate(_rows())
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"verdict ledger: {report['status']}")
        print(
            f"  {report['claims']} claims · {report['verdicts']} verdicts · "
            f"{report['independently_settled']} independently settled"
        )
        if report["unsigned"]:
            print(f"  awaiting an independent verdict: {', '.join(report['unsigned'])}")
        if report["refuted"]:
            print(f"  refuted: {', '.join(report['refuted'])}")
        for problem in report["problems"]:
            print(f"  x {problem}")
    # Unsigned claims are the state of the work, not a failure of the ledger.
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
