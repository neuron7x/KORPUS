#!/usr/bin/env python3
"""Протокол багатоагентної роботи: реєстр ОСЕЙ, бюджет на твердження, приймання.

Три правила, і жодне з них не про «ролі агентів»:

**Агент не верифікує агента — верифікує ІНША ТОЧКА.** Два агенти на тих самих даних
це один агент за подвійну ціну: вони зійдуться, і згода буде порожньою. Тому реєстр
описує не роль, а ВІСЬ: свої дані, свій критерій, своя мережева позиція, свій
інструмент. Другий агент на вже зайнятій осі відмовляється як витрата.
Виміряно 2026-08-30: паралельна сесія знайшла ваду мого відбитка звітів, бо мала
ІНШИЙ корпус; те саме джерело віддало нам HTTP 403 і їм повний текст — і це виявилось
не суперечністю, а різними точками доступу.

**Вирок живе ПОЗА агентами.** Агент виробляє твердження; PASS виносить механіка —
гейт, мутація, ратчет. Того ж дня чотири перевірки сказали неправду, і жодну не
спіймала дискусія: спіймали отрута в код, відкладений набір і негативний контроль
на самому контролі. Більше агентів дало б більше ВПЕВНЕНОЇ ЗГОДИ, не більше правди.

**Твердження коштує.** Журнал приймав claim безкоштовно, тож ніщо не тисло до виміру:
на 69 тверджень було 25 вироків. Бюджет на актора змушує домогтися вироку по старих,
перш ніж додавати нові — тоді дешевше поміряти, ніж наполягати.

⚠ МЕЖА, яку треба назвати: `can_accept` перевіряється відсутністю Write/Edit у
переліку інструментів агента — але агент із `Bash` однаково може писати файли.
Тобто це правило слабше, ніж виглядає: воно робить запис НЕЗРУЧНИМ, а не неможливим.
Не називати цього означало б продати гарантію, якої немає.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config/agents/axes.json"
LEDGER = ROOT / ".verdict-ledger.jsonl"
AGENT_DIR = Path.home() / ".claude/agents"
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
#: Інструменти, які пишуть НЕ називаючись записом. `Bash` дозволяє `echo > file`,
#: `Agent` може підняти виконавця з правом запису. Підстава `no-write-tools` без
#: їхнього оголошення продає гарантію, якої немає: я назвала цю межу в докстрінгу
#: і лишила її на слово читача. Слово читача — не перевірка.
RESIDUAL_WRITE_TOOLS = {"Bash", "Agent", "Task", "Workflow"}
MIN_EVIDENCE = 2
MIN_INSTRUMENT_CHARS = 30


def load_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def agent_tools(name: str) -> set[str] | None:
    """Інструменти агента з його frontmatter. None — файла немає."""
    path = AGENT_DIR / f"{name}.md"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines()[:12]:
        m = re.match(r"^tools:\s*(.+)$", line.strip())
        if m:
            return {t.strip() for t in m.group(1).split(",") if t.strip()}
    return set()


#: Розділено на правила-функції не заради краси: `check_registry` мала складність 23
#: при стелі 15, і стелю в цьому проєкті не піднімають — піднята стеля перестає бути
#: межею й починає бути записом того, що вже сталося. Кожне правило нижче перевіряє
#: РІВНО одну властивість реєстру й повертає свої зауваги; поведінка не змінена,
#: доведено збігом виводу --selftest/--registry/--ledger до і після.
def _unique_agents(agents: list[dict]) -> list[str]:
    """Один агент — один запис. Дубль означає дві різні декларації тієї самої ролі."""
    return [f"агент {name!r} оголошений {n} разів"
            for name, n in Counter(a.get("agent") for a in agents).items() if n > 1]


def _one_agent_per_axis(agents: list[dict]) -> list[str]:
    """Вісь на тих самих даних, зайнята двічі, не додає осі — додає витрату."""
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for a in agents:
        pairs[(a.get("axis", ""), a.get("data_scope", ""))].append(a.get("agent", "?"))
    return [f"вісь {axis!r} на даних {scope!r} зайнята кількома агентами "
            f"({', '.join(who)}) — другий не приносить нової осі, це витрата"
            for (axis, scope), who in sorted(pairs.items()) if len(who) > 1]


def _instrument_described(a: dict) -> list[str]:
    """`instrument` мусить описувати інструмент, а не повторювати назву ролі."""
    if len((a.get("instrument") or "").strip()) < MIN_INSTRUMENT_CHARS:
        return [f"{a.get('agent')}: `instrument` коротший за {MIN_INSTRUMENT_CHARS} "
                f"символів — назва ролі замість опису інструмента"]
    return []


def _acceptance_basis(a: dict, tools_of) -> list[str]:
    """ДВІ різні підстави приймати, і плутати їх не можна. Підагент приймає тому,
    що не має чим писати. Паралельна сесія писати може — вона приймає тому, що
    стоїть в ІНШІЙ точці: інші дані, інша мережа. Перша версія знала лише першу
    підставу й відмовила сесії за відсутність файла агента, хоча сесія й не
    мусить його мати. Підстава оголошується явно, інакше приймальник спирається
    на гарантію, якої в нього немає.
    """
    if not a.get("can_accept"):
        return []
    basis = a.get("accept_basis")
    if basis not in {"no-write-tools", "different-vantage"}:
        return [f"{a.get('agent')}: приймальник без оголошеної підстави "
                f"`accept_basis` (no-write-tools | different-vantage)"]
    if basis == "different-vantage":
        if len((a.get("vantage") or "").strip()) < MIN_INSTRUMENT_CHARS:
            return [f"{a.get('agent')}: підстава `different-vantage` без опису "
                    f"`vantage` — «інша точка» без опису точки нічим не інша"]
        return []
    tools = tools_of(a.get("agent", ""))
    if tools is None:
        return [f"{a.get('agent')}: підстава `no-write-tools`, але опису агента немає"]
    if tools & WRITE_TOOLS:
        return [f"{a.get('agent')}: приймальник із правом запису "
                f"({', '.join(sorted(tools & WRITE_TOOLS))}) — виробник не може "
                f"приймати власну роботу"]
    return _residual_declared(a, tools)


def _residual_declared(a: dict, tools: set[str]) -> list[str]:
    """Залишкові шляхи запису мусять бути ОГОЛОШЕНІ, і оголошення мусить збігатися
    з тим, що агент справді має. Тоді «no-write-tools» перестає читатись як
    гарантія й починає читатись як те, чим є: запис незручний, а не неможливий.
    """
    bad: list[str] = []
    residual = sorted(tools & RESIDUAL_WRITE_TOOLS)
    declared = sorted(a.get("residual_write_paths") or [])
    if residual and declared != residual:
        bad.append(f"{a.get('agent')}: має залишкові шляхи запису {residual}, "
                   f"оголошено {declared or 'нічого'} — підстава `no-write-tools` "
                   f"без цього оголошення обіцяє неможливість запису, а він лише "
                   f"незручний")
    if declared and not residual:
        bad.append(f"{a.get('agent')}: оголошено залишкові шляхи {declared}, "
                   f"яких у агента немає — оголошення описує не цього агента")
    return bad


def check_registry(reg: dict, tools_of=agent_tools) -> list[str]:
    agents = reg.get("agents", [])
    bad = _unique_agents(agents) + _one_agent_per_axis(agents)
    for a in agents:
        bad += _instrument_described(a) + _acceptance_basis(a, tools_of)
    return bad

def _verdicts(records: list[dict], claims: dict, vocab: dict) -> tuple[set[str], list[str]]:
    """Розбирає вироки: що вони закривають і чим із них є заперечення."""
    settles, opens = set(vocab["settles"]), set(vocab["does_not_settle"])
    raising = set(vocab.get("raising", ["ACCEPTED"]))
    bad: list[str] = []
    settled: set[str] = set()
    for r in records:
        if r.get("kind") != "verdict":
            continue
        word = r.get("verdict")
        if word not in settles | opens:
            #: слово поза словником — це ВІДМОВА, а не тиша: інакше друкарська
            #: помилка в `ACCEPTED` перестає бути вироком і журнал звітує PASS
            bad.append(f"вирок {r.get('id')}: слово {word!r} поза словником "
                       f"({', '.join(sorted(settles | opens))})")
            continue
        claim = claims.get(r.get("id"))
        if claim is None:
            bad.append(f"вирок {r.get('id')}: твердження з таким id немає")
            continue
        if r.get("actor") == claim.get("actor") and word in raising:
            #: Самоприйняття заборонене, САМОСПРОСТУВАННЯ — ні. Перша версія рівняла
            #: їх і назвала порушенням сім записів, з яких усі сім були REFUTED,
            #: AMENDED або OPEN_FOR_REVIEW — тобто автор ЗНИЖУВАВ власне твердження.
            #: Конфлікт інтересу однонапрямлений: піднімати себе вигідно, знижувати ні.
            #: Це не суперечить правилу «тягар сліпий до валентності»: там ідеться про
            #: обсяг доказу, тут — про те, хто має право виносити вирок.
            bad.append(f"{r.get('id')}: виробник {claim.get('actor')} ПІДНІМАЄ власне "
                       f"твердження вироком {word} — приймати себе не можна")
            continue
        if word in settles:
            settled.add(r["id"])
    return settled, bad


def _evidence_floor(claims: dict, settled: set[str]) -> list[str]:
    """Тонкий доказ — вада ВІДКРИТОГО твердження, не закритого.

    Поки ніхто не судив, твердження тримається лише на власному доказі, і одного
    рядка мало. Після вироку його тримає вирок разом із доказами приймальника, і
    вимагати того самого від автора означає карати за роботу, яку вже зроблено.
    Перша версія червоніла на двох твердженнях, розсуджених ще вчора, — тобто
    вимагала доробити те, що вже закрито.
    """
    return [f"ВІДКРИТЕ твердження {cid}: доказів {len(c.get('evidence') or [])} "
            f"(треба ≥{MIN_EVIDENCE}) — поки вироку немає, воно тримається лише на "
            f"власному доказі"
            for cid, c in claims.items()
            if cid not in settled and len(c.get("evidence") or []) < MIN_EVIDENCE]


def _claim_budget(claims: dict, settled: set[str], budget: int) -> list[str]:
    """Стеля на НЕЗАКРИТІ твердження одного актора: борг мусить тиснути на автора."""
    open_by_actor = Counter(c["actor"] for cid, c in claims.items() if cid not in settled)
    return [f"актор {actor}: {n} тверджень без вироку при бюджеті {budget} — "
            f"домогтися вироку по старих, перш ніж додавати нові"
            for actor, n in sorted(open_by_actor.items()) if n > budget]


def check_ledger(reg: dict, records: list[dict]) -> list[str]:
    claims = {r["id"]: r for r in records if r.get("kind") == "claim"}
    settled, bad = _verdicts(records, claims, reg["verdict_vocabulary"])
    return (bad + _evidence_floor(claims, settled)
            + _claim_budget(claims, settled, int(reg["claim_budget_per_actor"])))


def check_plan(reg: dict, plan: dict) -> list[str]:
    """Два законні режими, і правило «≥2 осі» стосується лише одного.

    `produce` — щось виробляється, тож потрібні щонайменше дві РІЗНІ осі: один
    виробник із приймальником це не багатоагентність, а пара.
    `adjudicate` — нічого не виробляється, судяться вже наявні твердження. Вимагати
    там двох виробників означало б вимагати виробництва заради форми плану.
    Перша версія знала лише перший режим і відмовила б чинній задачі «розсудити
    відкриті твердження» — виявлено тим, що ця задача справді знадобилась.
    """
    bad: list[str] = []
    by_name = {a["agent"]: a for a in reg.get("agents", [])}
    producers = list(plan.get("producers") or [])
    acceptor = plan.get("acceptor")
    mode = plan.get("mode", "produce")
    if mode not in {"produce", "adjudicate"}:
        bad.append(f"режим {mode!r} поза словником (produce | adjudicate)")
        return bad
    for p in producers:
        if p not in by_name:
            bad.append(f"виробник {p!r} не в реєстрі осей")
    axes = {by_name[p]["axis"] for p in producers if p in by_name}
    if mode == "produce" and len(axes) < 2:
        bad.append(f"план покриває {len(axes)} вісь — це один агент за ціною кількох; "
                   f"потрібні щонайменше дві РІЗНІ осі")
    if mode == "adjudicate" and producers:
        bad.append(f"режим adjudicate нічого не виробляє, але оголошено виробників "
                   f"({', '.join(producers)}) — назви режим чесно")
    if not acceptor:
        bad.append("плану бракує приймальника")
    elif acceptor not in by_name:
        bad.append(f"приймальник {acceptor!r} не в реєстрі осей")
    else:
        if not by_name[acceptor].get("can_accept"):
            bad.append(f"{acceptor}: не оголошений приймальником")
        if acceptor in producers:
            bad.append(f"{acceptor}: одночасно виробник і приймальник у тому самому плані")
    return bad


def report(title: str, problems: list[str]) -> int:
    if problems:
        print(f"{title}: ВІДМОВЛЕНО — {len(problems)}", file=sys.stderr)
        for p in problems:
            print("  ·", p, file=sys.stderr)
        return 1
    print(f"{title}: PASS")
    return 0


def selftest() -> int:
    """Кожне правило показане червоним — інакше воно нічого не тримає."""
    def base_reg(**over) -> dict:
        reg = {"verdict_vocabulary": {"settles": ["ACCEPTED", "REFUTED"],
                                      "does_not_settle": ["CANNOT_ADJUDICATE"],
                                      "raising": ["ACCEPTED"]},
               "claim_budget_per_actor": 2,
               "agents": [
                   {"agent": "prod", "axis": "a", "data_scope": "s1",
                    "instrument": "інструмент, описаний достатньо докладно",
                    "can_accept": False},
                   {"agent": "acc", "axis": "b", "data_scope": "s1",
                    "instrument": "інший інструмент, описаний достатньо докладно",
                    "can_accept": True, "accept_basis": "no-write-tools",
                    #: фікстура тепер оголошує Bash, бо `tools_ok` його дає — інакше
                    #: базовий випадок червоніє за новим правилом, і це правильно
                    "residual_write_paths": ["Bash"]}]}
        reg.update(over)
        return reg

    def claim(cid, actor, ev=2):
        return {"kind": "claim", "id": cid, "actor": actor, "claim": "x",
                "evidence": ["е"] * ev}

    def verdict(cid, actor, word="ACCEPTED"):
        return {"kind": "verdict", "id": cid, "actor": actor, "verdict": word}

    tools_ok = lambda n: {"Read", "Bash"} if n == "acc" else {"Read", "Write"}
    tools_writer = lambda n: {"Read", "Write"}
    tools_missing = lambda n: None

    cases: list[tuple[str, bool, list[str]]] = [
        ("реєстр як є — зелений", False, check_registry(base_reg(), tools_ok)),
        ("дві осі однакові — червоний", True, check_registry(base_reg(agents=[
            {"agent": "x", "axis": "a", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False},
            {"agent": "y", "axis": "a", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False}]), tools_ok)),
        ("та сама вісь на ІНШИХ даних — зелений", False, check_registry(base_reg(agents=[
            {"agent": "x", "axis": "a", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False},
            {"agent": "y", "axis": "a", "data_scope": "s2", "instrument": "о" * 40,
             "can_accept": False}]), tools_ok)),
        ("дубльоване імʼя — червоний", True, check_registry(base_reg(agents=[
            {"agent": "x", "axis": "a", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False},
            {"agent": "x", "axis": "b", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False}]), tools_ok)),
        ("інструмент — лише назва ролі — червоний", True, check_registry(base_reg(agents=[
            {"agent": "x", "axis": "a", "data_scope": "s1", "instrument": "критик",
             "can_accept": False}]), tools_ok)),
        ("приймальник із правом запису — червоний", True,
         check_registry(base_reg(), tools_writer)),
        ("Bash без оголошення — червоний", True, check_registry(base_reg(agents=[
            {"agent": "acc", "axis": "b", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": True, "accept_basis": "no-write-tools"}]),
            lambda n: {"Read", "Bash"})),
        ("Bash оголошений — зелений", False, check_registry(base_reg(agents=[
            {"agent": "prod", "axis": "a", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False},
            {"agent": "acc", "axis": "b", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": True, "accept_basis": "no-write-tools",
             "residual_write_paths": ["Bash"]}]), lambda n: {"Read", "Bash"})),
        ("оголошено те, чого немає — червоний", True, check_registry(base_reg(agents=[
            {"agent": "acc", "axis": "b", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": True, "accept_basis": "no-write-tools",
             "residual_write_paths": ["Bash"]}]), lambda n: {"Read", "Grep"})),
        ("приймальника без опису агента — червоний", True,
         check_registry(base_reg(), tools_missing)),
        ("приймальник без оголошеної підстави — червоний", True, check_registry(base_reg(
            agents=[{"agent": "acc", "axis": "b", "data_scope": "s1",
                     "instrument": "о" * 40, "can_accept": True}]), tools_ok)),
        ("сесія з іншою точкою і описом — зелений", False, check_registry(base_reg(
            agents=[{"agent": "peer", "axis": "b", "data_scope": "s2",
                     "instrument": "о" * 40, "can_accept": True,
                     "accept_basis": "different-vantage", "vantage": "т" * 40}]),
            tools_missing)),
        ("сесія з іншою точкою БЕЗ опису точки — червоний", True, check_registry(base_reg(
            agents=[{"agent": "peer", "axis": "b", "data_scope": "s2",
                     "instrument": "о" * 40, "can_accept": True,
                     "accept_basis": "different-vantage", "vantage": "інша"}]),
            tools_missing)),

        ("журнал як є — зелений", False, check_ledger(base_reg(), [
            claim("c1", "prod"), verdict("c1", "acc")])),
        ("виробник ПРИЙМАЄ себе — червоний", True, check_ledger(base_reg(), [
            claim("c1", "prod"), verdict("c1", "prod", "ACCEPTED")])),
        ("виробник СПРОСТОВУЄ себе — зелений", False, check_ledger(base_reg(), [
            claim("c1", "prod"), verdict("c1", "prod", "REFUTED")])),
        ("слово поза словником — червоний", True, check_ledger(base_reg(), [
            claim("c1", "prod"), verdict("c1", "acc", "ACCEPTEDD")])),
        ("вирок без твердження — червоний", True, check_ledger(base_reg(), [
            verdict("нема", "acc")])),
        ("одного доказу мало у ВІДКРИТОМУ — червоний", True, check_ledger(base_reg(), [
            claim("c1", "prod", ev=1)])),
        ("одного доказу досить у РОЗСУДЖЕНОМУ — зелений", False, check_ledger(base_reg(), [
            claim("c1", "prod", ev=1), verdict("c1", "acc")])),
        ("одного доказу мало, якщо вирок НЕ закриває — червоний", True,
         check_ledger(base_reg(), [claim("c1", "prod", ev=1),
                                   verdict("c1", "acc", "CANNOT_ADJUDICATE")])),
        ("CANNOT_ADJUDICATE не звільняє бюджет — червоний", True,
         check_ledger(base_reg(), [claim(f"c{i}", "prod") for i in range(3)]
                      + [verdict(f"c{i}", "acc", "CANNOT_ADJUDICATE") for i in range(3)])),
        ("бюджет вичерпано — червоний", True, check_ledger(base_reg(), [
            claim(f"c{i}", "prod") for i in range(3)])),
        ("бюджет звільнено вироками — зелений", False, check_ledger(base_reg(), [
            claim(f"c{i}", "prod") for i in range(3)]
            + [verdict(f"c{i}", "acc") for i in range(3)])),

        ("план як є — зелений", False, check_plan(base_reg(agents=base_reg()["agents"] + [
            {"agent": "prod2", "axis": "c", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False}]), {"producers": ["prod", "prod2"], "acceptor": "acc"})),
        ("одна вісь у плані — червоний", True, check_plan(base_reg(),
            {"producers": ["prod"], "acceptor": "acc"})),
        ("adjudicate без виробників — зелений", False, check_plan(base_reg(),
            {"mode": "adjudicate", "producers": [], "acceptor": "acc"})),
        ("adjudicate З виробниками — червоний", True, check_plan(base_reg(),
            {"mode": "adjudicate", "producers": ["prod"], "acceptor": "acc"})),
        ("режим поза словником — червоний", True, check_plan(base_reg(),
            {"mode": "думати", "producers": ["prod"], "acceptor": "acc"})),
        ("приймальник він же виробник — червоний", True, check_plan(base_reg(agents=[
            {"agent": "prod", "axis": "a", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": True},
            {"agent": "p2", "axis": "b", "data_scope": "s1", "instrument": "о" * 40,
             "can_accept": False}]), {"producers": ["prod", "p2"], "acceptor": "prod"})),
        ("виробник поза реєстром — червоний", True, check_plan(base_reg(),
            {"producers": ["prod", "хтось"], "acceptor": "acc"})),
        ("приймальник не оголошений таким — червоний", True, check_plan(base_reg(),
            {"producers": ["prod", "acc"], "acceptor": "prod"})),
    ]
    bad = 0
    for name, want_red, problems in cases:
        red = bool(problems)
        ok = red == want_red
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}")
    print(f"\nсамоперевірка: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--registry", action="store_true")
    ap.add_argument("--ledger", action="store_true")
    ap.add_argument("--plan", help="JSON: {\"producers\": [...], \"acceptor\": \"...\"}")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    reg = load_registry(REGISTRY)
    rc = 0
    if args.registry or not (args.ledger or args.plan):
        rc |= report("axes-registry", check_registry(reg))
    if args.ledger or not (args.registry or args.plan):
        records = [json.loads(l) for l in LEDGER.open(encoding="utf-8") if l.strip()]
        rc |= report("verdict-ledger", check_ledger(reg, records))
    if args.plan:
        rc |= report("plan", check_plan(reg, json.loads(args.plan)))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
