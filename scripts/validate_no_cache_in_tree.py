#!/usr/bin/env python3
"""Gate: nothing writes a cache, a derived artifact or a scratch file inside the tree.

Why this shape and not a grep for a known path. The first guard against this searched the
SOURCE for the literal string `var/evidence-capture/derived` — so it caught that one path
returning and nothing else. A cache written to `scripts/.tmp`, `apps/api/.cache` or
`config/derived` would have passed while being the same defect. A rule keyed on a string
knows only the mistake already made.

This looks at the TREE instead. Any directory whose name says "this is regenerable" —
a cache, a scratch, a derived output — has no business existing inside a checkout, no
matter which tool put it there or what it is called in code. That catches the paths nobody
has thought of yet, which is the only kind that matters.

The two defects this exists for, both measured 2026-08-30:

  * `scripts/.mypy_cache` (24 MB) held the names of every module, and the gate asking
    "is every script reached by a runner" went green forever — a cache laundering a
    reachability claim. It survived a day past the fix that created it, because
    `make clean` removed `.mypy_cache` at the ROOT and this one was one level down.
  * A cache of extracted text was placed in `var/evidence-capture/derived` — inside the
    one directory whose purpose is to be deleted. One `make clean` erased it along with
    50 MB of database and 530 MB of captured bytes.

The rule those two share: a measurement must live where neither editing, nor cleaning,
nor a rollback can reach it. `~/.korpus-cache/` and similar are outside the tree by
construction; anything inside it is one routine operation away from gone.

`--selftest` plants each shape and requires the gate to find it.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Імена, що САМІ кажуть «це відтворюване» — незалежно від того, який інструмент їх створив.
REGENERABLE = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".cache",
    "cache",
    ".tmp",
    "tmp",
    "derived",
    ".scratch",
    "scratch",
    ".ipynb_checkpoints",
}
#: Каталоги, всередину яких не заходимо: чужа територія або сам стан.
SKIP = {".git", "node_modules", ".venv", "venv", "var"}
#: Дозволені ЗА ІМЕНЕМ, кожен із причиною. Виняток без причини нічим не кращий за дірку,
#: тому словник, а не множина: додати ім'я не назвавши, чому, тут неможливо.
ALLOWED_NAMES: dict[str, str] = {
    "__pycache__": (
        "створює сам інтерпретатор при кожному імпорті — прибрати його з дерева не можна, "
        "можна лише не читати. ЗАЛИШКОВИЙ РИЗИК названий: .pyc містить імена модулів, тож "
        "будь-який пошук ТЕКСТОМ по дереву може ними відмитися — рівно те, що зробив "
        "scripts/.mypy_cache із гейтом досяжності. Компенсація: усі такі пошуки зобов'язані "
        "виключати кеші за іменем, і саме це перевіряє test_every_script_is_reachable, "
        "показаний падаючим на підкладеній сироті."
    ),
}
#: Дозволені за ТОЧНИМ шляхом — для окремих випадків, яких ще немає.
ALLOWED: dict[str, str] = {}


def offenders(root: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & SKIP:
            continue
        if path.name not in REGENERABLE or path.name in ALLOWED_NAMES:
            continue
        rel = str(path.relative_to(root))
        if rel in ALLOWED:
            continue
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        found.append((path.relative_to(root), f"{size / 1e6:.1f} МБ"))
    return sorted(found)


def selftest() -> int:
    cases = [
        ("кеш mypy на другому рівні", "scripts/.mypy_cache", True),
        ("кеш під іншим іменем", "apps/api/.cache", True),
        ("похідні дані в конфігу", "config/derived", True),
        ("тимчасове в довільному місці", "docs/.tmp", True),
        ("нормальна тека", "docs/architecture", False),
        ("__pycache__ дозволений із причиною", "apps/api/src/__pycache__", False),
        ("усередині var — не наша справа, там стан", "var/evidence-capture/derived", False),
        ("усередині .git — чужа територія", ".git/objects/cache", False),
    ]
    bad = 0
    #: Кожне дозволене ім'я мусить нести причину від 60 символів. Порожній рядок або
    #: заповнювач робить звільнення невидимим — та сама вада, що звільнення без причини
    #: в module-budget.
    for name, why in ALLOWED_NAMES.items():
        ok = len(why.strip()) >= 60
        bad += not ok
        print(f"  {'✓' if ok else '✗'} дозвіл «{name}» несе причину ({len(why.strip())} символів)")
    with tempfile.TemporaryDirectory() as td:
        for name, rel, want in cases:
            root = Path(td) / "tree"
            shutil.rmtree(root, ignore_errors=True)
            (root / rel).mkdir(parents=True, exist_ok=True)
            (root / rel / "blob").write_text("x" * 100, encoding="utf-8")
            got = bool(offenders(root))
            ok = got == want
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {name}: {'знайдено' if got else 'пропущено'}")
    total = len(cases) + len(ALLOWED_NAMES)
    print(f"негативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    found = offenders(ROOT)
    if found:
        print("cache in tree: FAIL")
        for rel, size in found:
            print(
                f"  ✗ {rel} ({size}) — відтворюване всередині дерева: одна рутинна "
                "операція від зникнення, і воно вміє відмивати гейти"
            )
        return 1
    print("cache in tree: PASS")
    print(f"  жодного відтворюваного каталогу поза var/ · шукали {len(REGENERABLE)} імен")
    for name, why in ALLOWED_NAMES.items():
        print(f"  дозволено «{name}»: {why[:96]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
