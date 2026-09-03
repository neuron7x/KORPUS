#!/usr/bin/env python3
"""Чи зведення гілок нічого не втратило — питання до ВМІСТУ, не до графа комітів.

01.09.2026 гілок було сорок: локальні, `gitlab/*` і двадцять п'ять `origin/*` із лінії,
що розійшлася 12–19 серпня. Їх зводять в одну канонічну. Це та операція, після якої
«загублене» і «ніколи не існувало» виглядають однаково — тому знімок робиться ДО, і
робиться ТЕГАМИ, а не файлом: файл у скретчпаді переживе не кожен день, тег живе в
самому репозиторії й тримає коміт від збирача сміття.

## Що саме перевіряється

1. **Жоден зафіксований тіп не став недосяжним.** Сорок тегів `archive/<дата>/*` — це
   і є база порівняння. Тег, що зник або більше не вказує на коміт, означає, що гілку
   прибрали разом із роботою.
2. **Канон нічого не ВТРАТИВ.** Дерево канону порівнюється з його ж тегом-знімком:
   файл, що був і зник, — це втрата, навіть якщо мердж «пройшов зелено». Саме цього
   бояться при зведенні старої лінії поверх нової.
3. **Alembic має РІВНО ОДНУ голову.** Три номери міграцій означають різні міграції у
   двох лініях (0016 `learning_course_graph` проти `temporal_corpus_snapshot`, і те саме
   на 0017 та 0018). Наївний мердж дає дві голови або тихо хибний порядок на базі, яка
   вже розгорнута з канонічними.
4. **Лан `validate` виміряний цілком**, а не спинений на першій відмові: `not_run` = 0.
5. **Профіль осей** — вердикт PASS і жодна вісь не під підлогою.
6. **Мутанти** — вбито стільки ж, скільки є, `survived` порожній.

Кожне твердження падає окремо й називає, ЩО саме не так. Відсутній звіт — це UNKNOWN,
не PASS: лан, якого не ганяли, нічого не доводить.

    verify_branch_consolidation.py [--canonical work/converge-semantic] [--prefix archive/2026-09-01]
    verify_branch_consolidation.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


#: Корінь визначається репозиторієм, а не батьком файла: інструмент контролю мусить
#: працювати й ЗЗОВНІ дерева. Під час заморозки він там і лежить — скрипт у `scripts/`
#: без цілі в Makefile червонить `test_every_script_is_reachable_from_a_runner`, і
#: 01.09.2026 він так зіпсував чужий прогін доказів. Тобто інструмент контролю ледь не
#: став джерелом того, що контролює.
def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        registry = candidate / "config/operations/canonical-state.json"
        if (candidate / ".git").exists() or registry.is_file():
            return candidate
    return start


ROOT = _repo_root(Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def baseline_tags(prefix: str) -> dict[str, str]:
    """Тег → коміт. База порівняння живе в репозиторії, не в теці процесу."""
    pairs: dict[str, str] = {}
    for line in git(
        "for-each-ref", "--format=%(refname:short) %(objectname)", f"refs/tags/{prefix}"
    ).splitlines():
        name, _, sha = line.partition(" ")
        if name:
            pairs[name] = git("rev-parse", f"{name}^{{commit}}") or sha
    return pairs


def unreachable(tags: dict[str, str]) -> list[str]:
    return [name for name, sha in tags.items() if git("cat-file", "-t", sha) != "commit"]


def files_lost(canonical: str, snapshot: str) -> list[str]:
    """Файли, які були в каноні на момент знімка і зникли. Втрата, навіть якщо зелено."""
    before = set(git("ls-tree", "-r", "--name-only", snapshot).splitlines())
    after = set(git("ls-tree", "-r", "--name-only", canonical).splitlines())
    return sorted(before - after)


def alembic_heads() -> list[str]:
    versions = ROOT / "apps/api/migrations/versions"
    if not versions.is_dir():
        return []
    revisions: dict[str, str] = {}
    parents: set[str] = set()
    for path in sorted(versions.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = _literal(text, "revision")
        previous = _literal(text, "down_revision")
        if revision:
            revisions[revision] = path.name
        if previous:
            parents.add(previous)
    return sorted(name for key, name in revisions.items() if key not in parents)


def _literal(text: str, name: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith((f"{name} =", f"{name}:")):
            value = stripped.split("=", 1)[-1].split(":", 1)[-1].strip().strip("\"'")
            return None if value in {"None", ""} else value
    return None


def _report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded


def report_is_stale(ran_at: str, head_epoch: int) -> bool:
    """Звіт, знятий РАНІШЕ за поточний HEAD, описує інше дерево.

    Лишено як ГРУБИЙ фільтр і як сумісність зі звітами без тотожності. Первинна перевірка
    тепер `lane_binding_failure`: годинник каже КОЛИ, а не ЩО, і прогін, що почався до
    коміту й скінчився після нього, за часом виглядає свіжим.
    """
    try:
        moment = int(datetime.fromisoformat(ran_at).timestamp())
    except (TypeError, ValueError):
        return True
    return moment < head_epoch


def lane_binding_failure(lane: dict[str, Any], head_commit: str, tree_digest: str) -> str | None:
    """Чому цей звіт НЕ про це дерево — або None, якщо він саме про нього.

    Звіт, що не називає свого дерева, недоказовий: довести свіжість мусить він, а не той,
    хто його читає. Тому відсутня тотожність — така сама відмова, як розбіжна, і обидві
    йдуть у `problems`, а не в `unknown`. Виміряно 02.09.2026: вирок читав лан із іншого
    дерева і називав це UNKNOWN, тобто «не виміряно», хоча виміряно було ІНШЕ.
    """
    claimed_commit = str(lane.get("source_commit") or "")
    claimed_digest = str(lane.get("source_digest") or "")
    if not claimed_commit or not claimed_digest:
        return "звіт лану не називає дерева, яке міряв — перезніми лан"
    if lane.get("source_moved_during_run"):
        return "джерело зрушило ПІД ЧАС лану — половина звіту про інше дерево"
    if claimed_commit != head_commit:
        return f"лан знято на {claimed_commit[:7]}, HEAD {head_commit[:7]} — це різні дерева"
    if claimed_digest != tree_digest:
        return "лан знято на тому ж коміті, але з іншим вмістом — дерево було брудне"
    return None


def _lane_findings(
    lane: dict[str, Any] | None, stale: bool, binding: str | None
) -> tuple[list[str], list[str]]:
    if lane is None:
        return [], ["немає var/lane-validate.json — лан не ганяли, отже нічого не доведено"]
    if binding is not None:
        return [f"лан не прив'язаний до HEAD: {binding}"], []
    if stale:
        return ["звіт лану СТАРШИЙ за HEAD — він про інше дерево, прожени лан заново"], []
    if lane.get("not_run") or lane.get("failed"):
        return [f"лан: впало {lane.get('failed')}, НЕ ЗАПУСКАЛОСЬ {lane.get('not_run')}"], []
    return [], []


def _axes_findings(axes: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """UNKNOWN і FAIL — різні вироки, і плутати їх тут найдорожче.

    Вісь `evidence_bases` має стелю віку одна година, тож профіль стає UNKNOWN сам
    собою. Приписати це зведенню означало б звинуватити мердж у власному
    протермінованому вході. Нижче підлоги — шкода; несвіжий вхід — UNKNOWN.
    """
    if axes is None:
        return [], ["немає var/answer-axes.json — профіль осей не міряли"]
    below = [
        item["axis"]
        for item in axes.get("axes", [])
        if item.get("state") == "MEASURED" and item.get("below_floor")
    ]
    stale = [
        f"{item['axis']}: {item.get('reason', '')}"
        for item in axes.get("axes", [])
        if item.get("state") != "MEASURED"
    ]
    problems = [f"осі ПІД ПІДЛОГОЮ: {below}"] if below else []
    if axes.get("verdict") == "FAIL" and not below:
        problems.append("вердикт осей FAIL без названої осі — звіт суперечить сам собі")
    return problems, stale


def _mutation_findings(mutation: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Внутрішня узгодженість звіту НЕ означає, що він бачив каталог.

    Після зведення каталог виріс до 525, а звіт лишився про 511 і виглядав цілим:
    511 із 511, `survived` порожній. Тому питаємо окремий гейт свіжості.
    """
    problems: list[str] = []
    freshness = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_mutation_report_freshness.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if freshness.returncode != 0:
        unseen = re.findall(r"каталог має (\d+) мутантів", freshness.stdout)
        problems.append(
            f"звіт мутацій не бачив {unseen[0]} мутантів каталогу"
            if unseen
            else "звіт мутацій розійшовся з каталогом"
        )
    if mutation is None:
        return problems, ["немає reports/MUTATION_REPORT.json"]
    problems.extend(mutation_consistency(mutation))
    return problems, []


def mutation_consistency(mutation: dict[str, Any]) -> list[str]:
    """Чому одного `killed == mutants` не досить.

    Виміряно 02.09.2026 на цьому ж коді: `{"killed": 0, "mutants": 0, "survived": []}`
    давало НУЛЬ проблем, бо `0 != 0` хибне. Прогін, який не мутував нічого, читався як
    доказ. Порожній звіт `{}` проходив із тієї самої причини: `None != None` теж хибне.
    Це `NOT_EXECUTED -> PASS` у чистому вигляді, і гейт свіжості його не ловить —
    звіт, що перелічує всі ідентифікатори каталогу й не вбиває жодного, свіжий.

    Тому три окремі твердження, кожне падає своїм рядком: мутантів БУЛО скільки їх є,
    вбито рівно стільки ж, вижилих немає.
    """
    problems: list[str] = []
    total, killed = mutation.get("mutants"), mutation.get("killed")
    if not isinstance(total, int) or total <= 0:
        problems.append(f"звіт мутацій не називає жодного мутанта: mutants={total!r}")
        return problems
    if not isinstance(killed, int) or killed != total:
        problems.append(f"мутанти: {killed!r}/{total}, а мусить бути {total}/{total}")
    survived = mutation.get("survived")
    if survived:
        problems.append(f"вижили мутанти: {survived}")
    return problems


def _produce_axes() -> dict[str, Any] | None:
    """Профіль виробляється ТУТ: він не має власного `--out`, а вік входів вимірюється
    годинами, тож учорашній файл питає про інший стан."""
    path = ROOT / "var/answer-axes.json"
    produced = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_answer_axes.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if produced.stdout.strip().startswith("{"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(produced.stdout, encoding="utf-8")
    return _report(path)


def _tree_findings(
    tags: dict[str, str],
    prefix: str,
    snapshot: str,
    gone: list[str],
    lost: list[str],
    heads: list[str],
) -> list[str]:
    """Твердження про сам репозиторій: база порівняння, втрати, ланцюг міграцій."""
    problems: list[str] = []
    if not tags:
        problems.append(f"немає жодного тега {prefix}/* — база порівняння відсутня")
    if gone:
        problems.append(f"тіпи стали недосяжними: {gone}")
    if snapshot not in tags:
        problems.append(f"немає знімка канону {snapshot} — «що втрачено» порахувати нічим")
    if lost:
        problems.append(f"канон ВТРАТИВ {len(lost)} файлів, напр. {lost[:5]}")
    if len(heads) != 1:
        problems.append(f"alembic голів {len(heads)}, мусить бути 1: {heads}")
    return problems


def gather(canonical: str, prefix: str) -> dict[str, Any]:
    tags = baseline_tags(prefix)
    snapshot = f"{prefix}/{canonical.replace('/', '-')}"
    lost = files_lost(canonical, snapshot) if snapshot in tags else []
    heads = alembic_heads()
    head_time = int(git("log", "-1", "--format=%ct", canonical) or 0)
    head_commit = git("rev-parse", canonical) or ""
    tree_digest = compute_source_digest(ROOT)
    lane = _report(ROOT / "var/lane-validate.json")
    lane_stale = lane is not None and report_is_stale(str(lane.get("ran_at", "")), head_time)
    lane_binding = lane_binding_failure(lane, head_commit, tree_digest) if lane else None

    gone = unreachable(tags)
    problems: list[str] = _tree_findings(tags, prefix, snapshot, gone, lost, heads)
    unknown: list[str] = []
    for source in (
        _lane_findings(lane, lane_stale, lane_binding),
        _axes_findings(_produce_axes()),
        _mutation_findings(_report(ROOT / "reports/MUTATION_REPORT.json")),
    ):
        problems.extend(source[0])
        unknown.extend(source[1])

    axes = _report(ROOT / "var/answer-axes.json")
    mutation = _report(ROOT / "reports/MUTATION_REPORT.json")
    return {
        "schema": "korpus.branch-consolidation.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "canonical": canonical,
        "canonical_head": git("rev-parse", "--short", canonical),
        "baseline_tags": len(tags),
        "tips_unreachable": gone,
        "files_lost_from_canonical": lost[:40],
        "files_lost_count": len(lost),
        "alembic_heads": heads,
        "lane": {k: lane.get(k) for k in ("passed", "failed", "not_run")} if lane else None,
        "axes_verdict": axes.get("verdict") if axes else None,
        "mutation": (
            {"killed": mutation.get("killed"), "mutants": mutation.get("mutants")}
            if mutation
            else None
        ),
        "branches_now": len(git("for-each-ref", "--format=%(refname)", "refs/heads").splitlines()),
        "problems": problems,
        "unknown": unknown,
        # Вирок названий ОБСЯГОМ, а не голим словом. Рецензія 03.09.2026: `ACCEPTED`
        # поруч із `production_authorized: false` в іншому звіті того самого дерева
        # легко переноситься на право випуску, якого тут не встановлювали. Ця перевірка
        # питає рівно одне: чи зведення гілок нічого не втратило й чи виміри описують
        # ЦЕЙ коміт. Вона не питає про безпеку, відтворення з нуля, незалежну
        # верифікацію й врядування, тож і сказати «прийнято» без обсягу не має права.
        "verdict": (
            "REJECTED" if problems else ("UNKNOWN" if unknown else "BRANCH_CONSOLIDATION_ACCEPTED")
        ),
        "scope": "branch consolidation and state binding only; NOT release authority",
        "production_authority": False,
        "ACCEPTED": not problems and not unknown,
    }


def selftest() -> int:
    checks: list[tuple[str, Any, Any]] = [
        ("голова без нащадків — голова", _literal("revision = '0018_x'", "revision"), "0018_x"),
        ("None читається як відсутність", _literal("down_revision = None", "down_revision"), None),
        ("порожнє — теж відсутність", _literal("down_revision = ''", "down_revision"), None),
        ("лапки знімаються", _literal('revision = "0001"', "revision"), "0001"),
        ("чужий рядок не плутається", _literal("# revision = 'x'", "revision"), None),
    ]
    heads = alembic_heads()
    checks.append(("у цьому дереві рівно одна голова", len(heads), 1))
    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def _declared_canonical() -> str:
    """Канонічна гілка — з `canonical-state.json` через спільний модуль.

    Перша версія читала `branch-integration.json` і мала дефолт `"main"`. Обидва
    рішення були хибні: оголошень стало два, а дефолт зробив би реєстр без імені
    невідрізненним від реєстру, що назвав правильно.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from canonical_declaration import canonical_branch

    return canonical_branch(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Канонічну гілку НЕ вписувати сюди константою. Вона вже оголошена в реєстрі, і
    # два оголошення розходяться мовчки: 01.09.2026 канон переїхав на `main`, а цей
    # сторож ще пів дня звітував ACCEPTED про `work/converge-semantic` — дзеркало,
    # застигле на комітах тому. Вирок був правдивий про той ref і хибний про предмет.
    parser.add_argument("--canonical", default=_declared_canonical())
    parser.add_argument("--prefix", default="archive/2026-09-01")
    parser.add_argument("--out", type=Path, default=ROOT / "var/branch-consolidation.json")
    parser.add_argument("--root", type=Path, default=None, help="корінь репозиторію")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.root:
        globals()["ROOT"] = arguments.root
    if arguments.selftest:
        return selftest()
    report = gather(arguments.canonical, arguments.prefix)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    arguments.out.write_text(rendered, encoding="utf-8")
    print(rendered)
    if report["problems"]:
        return 1
    return 0 if not report["unknown"] else 2


if __name__ == "__main__":
    sys.exit(main())
