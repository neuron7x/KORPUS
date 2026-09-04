#!/usr/bin/env python3
"""Зібрати ВХІДНИЙ пакет для доменного TEVV — усе, крім людських міток.

Політика (`evals/GOLD_ANNOTATION_LEDGER_TEMPLATE.json`) вимагає щонайменше 200 запитів,
40 сліпих холдаутів, двох анотаторів і Cohen's kappa >= 0.6. Машина може зробити все,
крім МІТОК: зібрати запити, заморозити їхній дайджест, розділити холдаут ДО того, як
хтось побачив відповіді, прив'язати пакет до дерева й корпусу, і подати анотаторам
готові аркуші.

Міток тут немає й не буде: два контексти LLM не є двома незалежними предметними
анотаторами, і жодне число, виведене з них, не є вимірюванням згоди.

Пакет лежить у `reports/`, який НЕ входить у `source_tree_sha256`, тож його поява не
зсуває кандидата й не знецінює жодного доказу, знятого на ньому.

    python3 reports/tevv-bundle/assemble.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/tevv-bundle"
#: Порядок сталий: пакет, зібраний двічі, мусить мати той самий дайджест.
SOURCES = (
    "reference",
    "domain_boundary",
    "assurance",
    "paraphrase_stability",
    "subject_inflection",
    "frozen",
    "seed",
    "pec/pec_eval",
)
HOLDOUT_MINIMUM = 40


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _queries() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for name in SOURCES:
        path = ROOT / f"evals/datasets/{name}.jsonl"
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            text = item.get("query") or item.get("question") or item.get("text") or ""
            if not text or text in seen:
                # Один і той самий запит із двох наборів — один рядок, не два: інакше
                # згода анотаторів рахувалась би двічі на тому самому предметі.
                continue
            seen.add(text)
            rows.append(
                {
                    "id": f"{name.replace('/', '-')}-{index:03d}",
                    "query": text,
                    "origin_dataset": name,
                    "origin_id": item.get("id"),
                    "stratum": item.get("stratum") or item.get("identity") or "unspecified",
                }
            )
    return rows


def _holdout(rows: list[dict[str, object]]) -> list[str]:
    """Холдаут обирається ДЕТЕРМІНОВАНО і ДО перегляду відповідей.

    Вибір за хешем ідентифікатора, не за порядком і не рукою: інакше «сліпий» холдаут
    можна було б підібрати після того, як стало видно, де система слабка.
    """
    ranked = sorted(rows, key=lambda row: _digest(str(row["id"]).encode()))
    count = max(HOLDOUT_MINIMUM, len(rows) // 5)
    return sorted(str(row["id"]) for row in ranked[:count])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _queries()
    query_lines = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    (OUT / "query_set.jsonl").write_text(query_lines + "\n", encoding="utf-8")
    query_digest = _digest((query_lines + "\n").encode("utf-8"))

    holdout = _holdout(rows)
    (OUT / "holdout.json").write_text(
        json.dumps(
            {
                "schema": "korpus.tevv-holdout.v1",
                "selection": "sha256(id), детерміновано, до перегляду відповідей",
                "count": len(holdout),
                "query_ids": holdout,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    for annotator in ("annotator-1", "annotator-2"):
        with (OUT / f"worksheet-{annotator}.csv").open("w", encoding="utf-8", newline="") as handle:
            # LF, не CRLF: маніфест уже ламався на CRLF, і аркуш, який людина
            # відкриє в редакторі й збереже, не має привозити із собою цю ваду.
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["query_id", "query", "label", "evidence_span_ids", "note"])
            for row in rows:
                writer.writerow([row["id"], row["query"], "", "", ""])

    template = json.loads((ROOT / "evals/GOLD_ANNOTATION_LEDGER_TEMPLATE.json").read_text("utf-8"))
    protocol = (ROOT / "evals/EVALUATION_PROTOCOL.md").read_bytes()
    source_digest = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;sys.path.insert(0,'apps/api/src');"
            "from pathlib import Path;"
            "from korpus.application.provenance import compute_source_digest;"
            "print(compute_source_digest(Path('.')))",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    release = json.loads((ROOT / "apps/api/src/korpus/release.json").read_text("utf-8"))["tag"]
    template["bindings"].update(
        {
            "source_tree_sha256": source_digest,
            "release": release,
            "query_set_sha256": query_digest,
            "annotation_protocol_sha256": _digest(protocol),
        }
    )
    template["tuning_query_ids"] = [row["id"] for row in rows if str(row["id"]) not in set(holdout)]
    (OUT / "ledger.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "queries": len(rows),
                "holdout": len(holdout),
                "query_set_sha256": query_digest,
                "source_tree_sha256": source_digest,
                "still_required_from_humans": [
                    "два незалежні предметні анотатори заповнюють worksheet-annotator-1.csv "
                    "і worksheet-annotator-2.csv стовпчик label",
                    "суддя, який не є жодним із них, розв'язує розбіжності",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
