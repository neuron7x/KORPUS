#!/usr/bin/env python3
"""Одна публікація, заведена в каталог двічі, мовчки роздвоюється всюди далі.

Знайдено виміром, не оглядом: у корпусі 5 пар документів мають БАЙТ-ІДЕНТИЧНИЙ вміст
(відбиток від відсортованого переліку sha256 усіх фрагментів), і в каталозі кожна пара
має один і той самий `source_uri` під двома id розділів:

    ARM-ATP-4-33-2024    = LOG-ATP-4-33-2024     ARN44809-ATP_4-33
    CAM-ATP-3-34-40-2023 = ENG-ATP-3-34-40-2023  ARN37985-ATP_3-34.40
    SIG-FM-3-12-2025     = EW-FM-3-12-2025       ARN45009-FM_3-12
    SIG-ATP-3-12.3-2023  = EW-ATP-3-12-3-2023    ARN44803-ATP_3-12.3
    SIG-ATP-3-12.4-2023  = EW-ATP-3-12-4-2023    ARN37162-ATP_3-12.4

Наслідки, кожен окремо: лічильники каталогу завищені на 5; кожна копія займає власне
місце у видачі пошуку (у виміряному промаху дві копії ATP 3-12.4 стояли на 2 і 3
позиціях); докази збираються двічі для одного файла.

**Гейт НЕ вимагає видалення.** Публікація справді може належати двом розділам — ATP 3-12.4
це і звʼязок, і РЕБ. Дефект не в тому, що запис подвоєно, а в тому, що подвоєння МОВЧАЗНЕ:
нізвідки не видно, який запис канонічний, і споживач лічильника не має шансу це врахувати.
Тому вимагається лише оголошення: неканонічний запис несе `cross_listed_of` з id канонічного.

Вимірюється СТАН каталогу, а не текст коду — інакше перевірка охороняла б власне
формулювання (guard-reads-past-what-it-guards).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

CATALOG = Path("config/corpus/doctrine_catalog_2026.json")
CANON = "canonical_id"
CROSS = "cross_listed_as"


def load(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data["sources"] if isinstance(data, dict) else data
    return [row for row in sources if isinstance(row, dict)]


def check(sources: list[dict[str, Any]]) -> list[str]:
    by_id = {s["id"]: s for s in sources}
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        uri = (s.get("source_uri") or "").strip()
        if uri:
            groups[uri].append(s)

    problems: list[str] = []
    for uri, items in sorted(groups.items()):
        ids = sorted(s["id"] for s in items)
        if len(items) < 2:
            if items[0].get(CANON) and items[0][CANON] != items[0]["id"]:
                problems.append(
                    f"{items[0]['id']}: оголошено `{CANON}`={items[0][CANON]}, але цей "
                    f"`source_uri` більше ніде не трапляється — крос-лістингу немає"
                )
            continue
        #: 1. кожен член групи мусить оголоситись — мовчазний член і є той дефект,
        #:    заради якого правило існує.
        silent = [s["id"] for s in items if not s.get(CANON)]
        if silent:
            problems.append(
                f"{uri}: {len(items)} записів ({', '.join(ids)}); без `{CANON}`: "
                f"{', '.join(silent)}"
            )
            continue
        #: 2. усі мусять назвати ОДИН і той самий канонічний, і він мусить бути в групі.
        #:    Дві різні законні відповіді на питання «який брати» гірші за жодної.
        named = {s[CANON] for s in items}
        if len(named) > 1:
            problems.append(
                f"{uri}: група називає РІЗНІ канонічні записи ({', '.join(sorted(named))}) — "
                f"збірник дістане дві законні відповіді на одне питання"
            )
            continue
        canon = named.pop()
        if canon not in ids:
            problems.append(f"{uri}: `{CANON}`={canon} не належить групі ({', '.join(ids)})")
            continue
        #: 3. `cross_listed_as` мусить називати рівно решту групи — з ОБОХ боків.
        for s in items:
            want = sorted(i for i in ids if i != s["id"])
            got = sorted(s.get(CROSS) or [])
            if got != want:
                problems.append(f"{s['id']}: `{CROSS}`={got} не збігається з рештою групи {want}")
        #: 4. НАСЛІДОК живе не в полі, а у СПОЖИВАЧАХ — див. check_consumers().
        #:    Перша версія вимагала знімати `ingestible` з неканонічних, і це було
        #:    неправильно: `ingestible` означає «права й форма дозволяють це взяти»,
        #:    і для перехресного розміщення це правда для ОБОХ записів — права ті самі,
        #:    форма та сама, документ той самий. Знявши його, ми записали б властивість
        #:    НАШОГО конвеєра як факт про документ, і одинадцять гейтів, які лише
        #:    РАХУЮТЬ придатні, почали б рахувати 160 замість 166 — підлога допустимості
        #:    поїхала б за виправленням дедупу. Це та сама підміна, через яку раніше
        #:    ледь не заблокували три джерела за нашою мережею.

    #: `canonical_id` на документ з ІНШИМ URI — заявлений звʼязок без предмета.
    for s in sources:
        target = s.get(CANON)
        if target and target in by_id and target != s["id"]:
            if (by_id[target].get("source_uri") or "").strip() != (
                s.get("source_uri") or ""
            ).strip():
                problems.append(
                    f"{s['id']}: `{CANON}`={target}, але їхні `source_uri` РІЗНІ — "
                    f"це не крос-лістинг, а два різні документи"
                )
        elif target and target not in by_id:
            problems.append(f"{s['id']}: `{CANON}`={target!r} — такого id в каталозі немає")
    return problems


#: Файли, які читають `ingestible`, але НЕ інжестять — лише рахують. Кожен із
#: причиною: перелік винятків без причин через місяць не відрізнити від недогляду.
COUNTING_ONLY = {
    "scripts/validate_doctrine_catalog.py": "гейт: рахує придатні джерела й перевіряє правила каталогу, у корпус не пише",
    "scripts/validate_content_signals.py": "гейт: перевіряє сигнали вмісту, у корпус не пише",
    "scripts/validate_document_probe.py": "гейт: перевіряє проби документів, у корпус не пише",
    "scripts/validate_page_probe.py": "гейт: перевіряє проби сторінок, у корпус не пише",
    "scripts/validate_remote_digest.py": "гейт: перевіряє віддалені відбитки, у корпус не пише",
    "scripts/validate_evidence_refusal.py": "гейт: перевіряє таксономію відмов, у корпус не пише",
    "scripts/validate_catalog_uri_uniqueness.py": "цей гейт",
    "scripts/recheck_blocked_sources.py": "переміряє досяжність заблокованих джерел і дописує `reachability_recheck` у сам каталог; байтів у корпус не інжестить",
    "scripts/capture_source_evidence.py": "збирає ДОКАЗИ про джерело; дублікат тут нешкідливий — байти лягають під власним id, у корпус не інжестяться",
}
CONSUMER_HINT = "canonical_id"


def check_consumers(root: Path) -> list[str]:
    """Кожен споживач `ingestible`, який ІНЖЕСТИТЬ, мусить фільтрувати й за канонічністю.

    Наслідок дедупу не може жити в полі каталогу — воно про права, не про наш конвеєр.
    Тому він живе у споживачах, і саме це перевіряється: не текст правила, а СТАН дерева.
    Інакше завтра зʼявиться другий збірник, і дублікат повернеться мовчки — рівно так,
    як він і зʼявився вперше.
    """
    problems: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith((".git/", "tests/", "var/")) or "/tests/" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        reads_field = (
            'get("ingestible")' in text or "get('ingestible')" in text or '["ingestible"]' in text
        )
        #: `ingestible` — ОМОНІМ. У знімачах Drive так зветься «чи ми вміємо читати цей
        #: тип файла» (за суфіксом імені), і до поля каталогу доктрини воно не має
        #: стосунку. Перша версія матчила рядок, а не предмет, і почервоніла на двох
        #: скриптах, які каталогу навіть не відкривають — рівно та вада, від якої цей
        #: гейт існує. Споживачем вважається лише той, хто читає САМ каталог.
        reads_catalog = "doctrine_catalog" in text
        if not (reads_field and reads_catalog):
            continue
        if CONSUMER_HINT in text:
            continue
        reason = COUNTING_ONLY.get(rel)
        if reason is None:
            problems.append(
                f"{rel}: фільтрує за `ingestible`, але не за `{CONSUMER_HINT}` — якщо він "
                f"інжестить, візьме ті самі байти двічі; якщо лише рахує, впиши його в "
                f"COUNTING_ONLY з причиною"
            )
        elif len(reason) < 40:
            problems.append(
                f"{rel}: причина в COUNTING_ONLY коротша за 40 символів — "
                f"перелік винятків без причин не відрізнити від недогляду"
            )
    return problems


def selftest() -> int:
    """Кожне правило мусить бути показане червоним, інакше воно не охороняє нічого."""

    def pair(**over: dict[str, Any]) -> list[dict[str, Any]]:
        a: dict[str, Any] = {
            "id": "A",
            "source_uri": "u1",
            CANON: "A",
            CROSS: ["B"],
            "ingestible": True,
        }
        b: dict[str, Any] = {
            "id": "B",
            "source_uri": "u1",
            CANON: "A",
            CROSS: ["A"],
            "ingestible": False,
        }
        a.update(over.get("a", {}))
        b.update(over.get("b", {}))
        return [a, b, {"id": "Z", "source_uri": "u9", "ingestible": True}]

    cases: list[tuple[str, list[dict[str, Any]], bool]] = [
        ("оголошена група з одним придатним — зелений", pair(), False),
        ("мовчазний член групи — червоний", pair(b={CANON: None}), True),
        ("група називає різні канонічні — червоний", pair(b={CANON: "B"}), True),
        ("канонічний поза групою — червоний", pair(a={CANON: "Z"}, b={CANON: "Z"}), True),
        (
            "обидва придатні — ЗЕЛЕНИЙ: права ті самі для обох записів",
            pair(b={"ingestible": True}),
            False,
        ),
        (
            "канонічний непридатний, інший придатний — ЗЕЛЕНИЙ з тієї ж причини",
            pair(a={"ingestible": False}, b={"ingestible": True}),
            False,
        ),
        ("cross_listed_as не називає сусіда — червоний", pair(a={CROSS: []}), True),
        ("cross_listed_as називає зайвого — червоний", pair(a={CROSS: ["B", "Z"]}), True),
        ("canonical_id на неіснуючий id — червоний", pair(a={CANON: "QQ"}, b={CANON: "QQ"}), True),
        (
            "canonical_id на документ з іншим URI — червоний",
            [
                {"id": "A", "source_uri": "u1", CANON: "Z", CROSS: [], "ingestible": True},
                {"id": "Z", "source_uri": "u9", "ingestible": True},
            ],
            True,
        ),
        (
            "крос-лістинг оголошено там, де URI унікальний — червоний",
            [
                {"id": "A", "source_uri": "u1", CANON: "B", "ingestible": True},
                {"id": "B", "source_uri": "u2", "ingestible": True},
            ],
            True,
        ),
        (
            "самотній запис без оголошень — зелений",
            [{"id": "A", "source_uri": "u1", "ingestible": True}],
            False,
        ),
        (
            "порожній URI не групується",
            [
                {"id": "A", "source_uri": "", "ingestible": True},
                {"id": "B", "source_uri": "", "ingestible": True},
            ],
            False,
        ),
        (
            "трійка, усі оголошені, один придатний — зелений",
            [
                {"id": "A", "source_uri": "u1", CANON: "A", CROSS: ["B", "C"], "ingestible": True},
                {"id": "B", "source_uri": "u1", CANON: "A", CROSS: ["A", "C"], "ingestible": False},
                {"id": "C", "source_uri": "u1", CANON: "A", CROSS: ["A", "B"], "ingestible": False},
            ],
            False,
        ),
        (
            "трійка, третій мовчить — червоний",
            [
                {"id": "A", "source_uri": "u1", CANON: "A", CROSS: ["B", "C"], "ingestible": True},
                {"id": "B", "source_uri": "u1", CANON: "A", CROSS: ["A", "C"], "ingestible": False},
                {"id": "C", "source_uri": "u1", "ingestible": False},
            ],
            True,
        ),
    ]
    bad = 0
    for name, sources, want_red in cases:
        red = bool(check(sources))
        ok = red == want_red
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}")
    print(f"\nсамоперевірка: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--catalog", type=Path, default=CATALOG)
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.catalog.exists():
        print(f"каталог не знайдено: {args.catalog}", file=sys.stderr)
        return 2
    problems = check(load(args.catalog)) + check_consumers(Path.cwd())
    if problems:
        print(f"catalog-uri-uniqueness: ВІДМОВЛЕНО — {len(problems)} проблем", file=sys.stderr)
        for p in problems:
            print("  ·", p, file=sys.stderr)
        print(
            "\nВиправлення НЕ означає видалення: перехресне розміщення дозволене, але мусить\n"
            "бути СКАЗАНЕ (`canonical_id` + `cross_listed_as` з обох боків) і мати наслідок —\n"
            "придатним до інжесту лишається рівно один запис групи.",
            file=sys.stderr,
        )
        return 1
    print("catalog-uri-uniqueness: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
