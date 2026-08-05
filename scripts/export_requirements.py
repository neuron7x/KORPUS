#!/usr/bin/env python3
"""Write every requirement this system states about itself as one readable register.

§2.5 asks an outside party to assess this system. The first thing they need is the
list of properties it claims — not a program that produces that list as a side effect
of running, and not a hundred `if` statements to be traced.

Three registers feed it: the infrastructure substrate, the repository contract, and the
conditions under which a controlled deployment may run at all. They were separate
accidents of where the code happened to live; to a reader they are one document.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.requirements import as_catalogue, duplicate_ids  # noqa: E402
from korpus.controlled_requirements import CONTROLLED_REQUIREMENTS  # noqa: E402
from korpus.infrastructure_requirements import INFRASTRUCTURE_REQUIREMENTS  # noqa: E402
from korpus.repository_requirements import REPOSITORY_REQUIREMENTS  # noqa: E402

OUTPUT = ROOT / "docs/operations/REQUIREMENTS_REGISTER.md"


def main() -> int:
    controlled = [
        {
            "id": f"controlled.{requirement.name}",
            "subject": "controlled-environment",
            "statement": requirement.message,
            "rationale": "",
        }
        for requirement in CONTROLLED_REQUIREMENTS
    ]
    infrastructure = as_catalogue(INFRASTRUCTURE_REQUIREMENTS)
    repository = as_catalogue(REPOSITORY_REQUIREMENTS)
    duplicates = duplicate_ids(
        (*INFRASTRUCTURE_REQUIREMENTS, *REPOSITORY_REQUIREMENTS)
    )
    if duplicates:
        print(json.dumps({"status": "FAIL", "duplicate_ids": duplicates}, indent=2))
        return 1

    entries = infrastructure + repository + controlled
    subjects: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        subjects.setdefault(str(entry["subject"]), []).append(entry)

    lines = [
        "# Реєстр вимог КОРПУСу",
        "",
        "Згенеровано `scripts/export_requirements.py`. Не редагувати вручну — джерело "
        "це `korpus/infrastructure_requirements.py` та `korpus/controlled_requirements.py`.",
        "",
        f"Усього вимог: **{len(entries)}**.",
        "",
        "Кожна має ідентифікатор, за яким її можна процитувати в аудиті, позначити як "
        "прийнятий ризик із названим власником, зіставити з мутантом і порахувати. До "
        "05.08.2026 їх не було: перевірка існувала як рядок, дописаний у місці збою.",
        "",
    ]
    for subject in sorted(subjects):
        lines += [f"## {subject}", "", "| id | вимога | чому |", "|---|---|---|"]
        for entry in sorted(subjects[subject], key=lambda item: str(item["id"])):
            rationale = str(entry["rationale"]).replace("|", "\\|") or "—"
            statement = str(entry["statement"]).replace("|", "\\|")
            lines.append(f"| `{entry['id']}` | {statement} | {rationale} |")
        lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "requirements": len(entries),
                "subjects": {name: len(items) for name, items in sorted(subjects.items())},
                "path": str(OUTPUT.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
