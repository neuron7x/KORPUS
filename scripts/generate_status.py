#!/usr/bin/env python3
"""The one status a commander reads, generated from the registers so it cannot lie.

`TECHNICAL_DEBT_V5.md` says "31 EXTERNAL_DEBT". The closure register says nine. The prose
was written when thirty-one findings were external and twenty-two have since been mitigated
locally — but the number never moved, so a commander deciding whether to authorise reads
thirty-one blockers where there are nine. A hand-maintained count of a machine-tracked set
drifts the first time the set changes and nobody re-types the sentence.

So the count is not typed. This reads `KORPUS_v5_REMAINING_DEBT.json` (the closure register)
and `admission-grounds.json` (the reasons production is withheld) and writes one Ukrainian
status document from them. `test_status_document_matches_the_registers.py` fails if the
document and the registers disagree, so the number a commander reads is the number the
system holds.

    generate_status.py            # write docs/operations/CURRENT_STATUS.md
    generate_status.py --check    # fail if it is stale
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEBT = ROOT / "docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json"
GROUNDS = ROOT / "config/operations/admission-grounds.json"
GATE = ROOT / "reports/OPERATIONAL_GATE.json"
OUT = ROOT / "docs/operations/CURRENT_STATUS.md"


def _load(path: Path) -> dict[str, Any]:
    """json.loads returns Any; a loader that promises an object must refuse a list."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def render() -> str:
    debt = _load(DEBT)
    grounds = _load(GROUNDS)
    counts = Counter(item["v5_status"] for item in debt["items"])
    external = [item for item in debt["items"] if item["v5_status"] == "EXTERNAL_DEBT"]
    # Ground 2.8 ("gates must be able to go red") is a property of the system, not a reason
    # authorisation is withheld — it is excluded from the count of open blocking grounds.
    open_grounds = [g for g in grounds["grounds"] if g.get("id") != "2.8"]

    production_authorized = False
    if GATE.is_file():
        production_authorized = bool(_load(GATE).get("production_authorized", False))

    lines = [
        "# КОРПУС — поточний статус",
        "",
        "> Згенеровано з реєстрів `scripts/generate_status.py`. Не редагувати вручну —",
        "> `test_status_document_matches_the_registers.py` впаде, якщо цифри розійдуться",
        "> з реєстрами. Це той документ, по якому ухвалюють рішення про допуск.",
        "",
        f"**production_authorized:** `{str(production_authorized).lower()}`",
        "",
        "## Борг, який закривається лише поза кодом",
        "",
        f"**{counts['EXTERNAL_DEBT']}** зовнішніх боргів. Жоден не закривається кодом у цьому",
        "дереві — кожен потребує людини, підпису, інфраструктури або незалежної перевірки.",
        "",
        "| id | серйозність | що потрібно |",
        "|---|---|---|",
    ]
    for item in sorted(external, key=lambda i: i["id"]):
        action = item.get("required_action", "").replace("\n", " ")[:80]
        lines.append(f"| {item['id']} | {item['severity']} | {action} |")

    lines += [
        "",
        f"Локально помʼякшених (код зробив усе, що міг): **{counts['MITIGATED_LOCAL']}**.",
        "",
        "## Підстави, чому допуск не надано",
        "",
        f"**{len(open_grounds)}** відкритих підстав. Кожна — рішення людини, не коду.",
        "",
        "| підстава | що це |",
        "|---|---|",
    ]
    for ground in open_grounds:
        lines.append(f"| {ground.get('id')} | {ground.get('title', '')} |")

    lines += [
        "",
        "## Що доведено кодом",
        "",
        "Тести, покриття, мутація, цілісність аудиту, деградація під відмовою залежностей —",
        "усе виміряно запуском і лежить у `reports/`. Це доводить, що система робить те, що",
        "заявлено; воно **не** доводить дозволу на продакшн, прав на корпус, незалежної",
        "стійкості до атак чи оголошених цілей відновлення. Ці рядки — вище.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = render()
    if arguments.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != rendered:
            print("CURRENT_STATUS.md is stale; run scripts/generate_status.py")
            return 1
        print("CURRENT_STATUS.md matches the registers")
        return 0
    OUT.write_text(rendered, encoding="utf-8")
    print(str(OUT.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
