#!/usr/bin/env python3
"""Які звіти доказів описують ІНШЕ дерево — і чим саме їх перевипустити.

Звіт — це твердження про дерево, не про світ. Щойно джерело змінилось, кожен звіт,
знятий раніше, говорить про щось інше, і гейти нижче кажуть це трьома різними словами:
`evidence_provenance`, `generated from a different source tree`, `доказ описує стан,
якого немає в жодному коміті`. Три повідомлення, одна причина, і дізнаєшся про неї аж на
третьому гейті. Ця перевірка ставить те саме питання ПЕРШОЮ і називає команду.

ДВІ РОЛІ, І ЇХ НЕ МОЖНА ПЕРЕВІРЯТИ ОДНАКОВО.

Виробник (`eval`, `mutation`, `migration`, `scale`) кладе в себе `provenance.source_digest` —
тотожність дерева, яке він міряв. Споживач (`operational-gate`) кладе `evidence_sha256` —
хеші ФАЙЛІВ, які він прочитав. Перший застаріває від зміни джерела, другий — від
перевипуску будь-якого виробника, і саме це `snapshot` каже словами «the gate passed over
a different file than the one about to be promoted».

`var/pytest.xml` тут немає навмисно: JUnit не несе походження взагалі, тож питати його
про дерево означало б завжди діставати відповідь «не знаю» й читати її як несвіжість.

Обмеження, назване тут, бо його легко переплутати: у дереві живуть ДВІ міри джерела —
`compute_source_digest` (обсяг EVIDENCE_SOURCE_PATHS) і `source_digest.source_tree_digest`
(усе відстежене мінус reports/var/dist). Порівняння однієї з другою читається як
«не прив'язано», хоча насправді порівняли два різні виміри. Тут ПЕРША, бо саме її кладуть
у `provenance.source_digest` виробники.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402

#: Виробник -> ціль, що його перевипускає. Порядок у кортежі і є порядком перевипуску:
#: кожен нижче читає те, що пише хтось вище.
PRODUCERS: tuple[tuple[str, str], ...] = (
    ("var/mutation-report.json", "mutation"),
    ("var/eval-report.json", "eval"),
    ("var/migration-report.json", "migration-gate"),
    ("var/scale-report.json", "scale"),
)

#: Споживач -> ціль. Він не міряє дерево; він хешує чужі звіти, і його вирок дійсний
#: рівно доти, доки ті файли байт у байт ті самі.
CONSUMERS: tuple[tuple[str, str, dict[str, str]], ...] = (
    (
        "var/operational-gate.json",
        "operational-gate",
        {
            "eval": "var/eval-report.json",
            "mutation": "var/mutation-report.json",
            "migration": "var/migration-report.json",
            "scale": "var/scale-report.json",
        },
    ),
)


def _load(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _producer_state(root: Path, relative: str, expected: str) -> tuple[str, str]:
    payload = _load(root / relative)
    if payload is None:
        return "ВІДСУТНІЙ", ""
    provenance = payload.get("provenance")
    claimed = provenance.get("source_digest") if isinstance(provenance, dict) else None
    if not isinstance(claimed, str):
        return "БЕЗ ПОХОДЖЕННЯ", ""
    return ("СВІЖИЙ" if claimed == expected else "ПРО ІНШЕ ДЕРЕВО"), claimed[:16]


def _consumer_state(root: Path, relative: str, inputs: dict[str, str]) -> tuple[str, list[str]]:
    payload = _load(root / relative)
    if payload is None:
        return "ВІДСУТНІЙ", []
    hashed = payload.get("evidence_sha256")
    if not isinstance(hashed, dict):
        return "БЕЗ ПОХОДЖЕННЯ", []
    moved = [name for name, source in inputs.items() if hashed.get(name) != _sha256(root / source)]
    return ("СВІЖИЙ" if not moved else "СУДИВ ІНШІ ФАЙЛИ"), sorted(moved)


def evaluate(root: Path) -> dict[str, object]:
    expected = compute_source_digest(root)
    rows: list[dict[str, object]] = []
    rerun: list[str] = []
    for relative, target in PRODUCERS:
        state, claimed = _producer_state(root, relative, expected)
        rows.append(
            {
                "report": relative,
                "role": "виробник",
                "target": target,
                "state": state,
                "digest": claimed,
            }
        )
        if state != "СВІЖИЙ":
            rerun.append(target)
    for relative, target, inputs in CONSUMERS:
        state, moved = _consumer_state(root, relative, inputs)
        rows.append(
            {
                "report": relative,
                "role": "споживач",
                "target": target,
                "state": state,
                "moved_inputs": moved,
            }
        )
        if state != "СВІЖИЙ":
            rerun.append(target)
    return {
        "status": "FAIL" if rerun else "PASS",
        "expected_source_digest": expected[:16],
        "reports": rows,
        "rerun_in_this_order": rerun,
    }


def selftest() -> int:
    """Негативний контроль: перевірка, яка не вміє почервоніти, нею не є."""
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        verdict = evaluate(Path(raw))
        if verdict["status"] != "FAIL":
            print("selftest FAIL: порожнє дерево мусить дати FAIL", file=sys.stderr)
            return 1
        rerun = verdict["rerun_in_this_order"]
        if not isinstance(rerun, list) or len(rerun) != len(PRODUCERS) + len(CONSUMERS):
            print("selftest FAIL: не всі відсутні звіти названі", file=sys.stderr)
            return 1

    with tempfile.TemporaryDirectory() as raw:
        # Позитивний контроль на СПОЖИВАЧІ: звіт, що судив саме ці байти, свіжий;
        # зміна одного байта у вході робить його несвіжим і називає, якого саме.
        tree = Path(raw)
        (tree / "var").mkdir()
        for _, source in CONSUMERS[0][2].items():
            (tree / source).write_text('{"provenance": {"source_digest": "x"}}', encoding="utf-8")
        hashes = {n: _sha256(tree / s) for n, s in CONSUMERS[0][2].items()}
        (tree / CONSUMERS[0][0]).write_text(
            json.dumps({"evidence_sha256": hashes}), encoding="utf-8"
        )
        state, moved = _consumer_state(tree, CONSUMERS[0][0], CONSUMERS[0][2])
        if state != "СВІЖИЙ" or moved:
            print(f"selftest FAIL: незмінений вхід прочитано як {state}", file=sys.stderr)
            return 1
        (tree / "var/scale-report.json").write_text("{}", encoding="utf-8")
        state, moved = _consumer_state(tree, CONSUMERS[0][0], CONSUMERS[0][2])
        if state != "СУДИВ ІНШІ ФАЙЛИ" or moved != ["scale"]:
            print(f"selftest FAIL: зміну входу не названо ({state}, {moved})", file=sys.stderr)
            return 1

    print(json.dumps({"selftest": "PASS"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    verdict = evaluate(ROOT)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
