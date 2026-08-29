"""One way to write the doctrine catalogue, because a snapshot erases other people's work.

A run that reads the catalogue, spends minutes measuring documents, and writes back the
copy it started with does not merge badly — it erases completely. Caught 2026-08-29 with
5245 lines of a parallel session's work already on disk, seconds before a capture run
would have overwritten them. Two tools write this file, so this is one module rather than
two implementations of the same care: a second definition of "how to write the catalogue"
is how the two would drift, and the drift would be invisible until something was lost.

The rules:

    read at write time, never at start time — the window between them is the whole risk;
    touch only the fields this run measured, on the ids it measured;
    a source that vanished meanwhile is reported, never recreated — that was a deletion;
    compare CONTENT, not mtime — restoring a file with `cp` changes mtime while the bytes
        stay identical, and a check on mtime would refuse a write for no reason, which is
        the same disease as a false `dead`;
    a changed file means retry the merge, not refuse it, and retries are bounded so two
        concurrent runs cannot spin against each other while both report progress.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_MERGE_ATTEMPTS = 5


def merge_write(
    path: Path,
    apply: Callable[[dict[str, Any]], list[str]],
    *,
    attempt: int = 1,
) -> list[str]:
    """Re-read `path`, let `apply` edit the catalogue, refuse or write. Returns problems.

    `apply` receives the catalogue as it is on disk right now — the whole object, because
    the counters a ratchet lowers live beside `sources`, not inside it — edits what this
    run measured, and returns any reason the write must not happen. It is called again
    from scratch on a retry, so it must not depend on having been called before.
    """
    raw = path.read_text(encoding="utf-8")
    catalog = json.loads(raw)
    problems = apply(catalog)
    if problems:
        return problems
    if (
        hashlib.sha256(path.read_bytes()).hexdigest()
        != hashlib.sha256(raw.encode("utf-8")).hexdigest()
    ):
        if attempt >= MAX_MERGE_ATTEMPTS:
            return [
                f"каталог змінювався {attempt} разів підряд під час запису — здаюся, "
                "щоб не крутитись у циклі проти чужого прогону"
            ]
        return merge_write(path, apply, attempt=attempt + 1)
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return []


def by_id(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(s["id"]): s for s in catalog["sources"] if isinstance(s, dict)}


def vanished_problem(claimed: set[str], present: set[str]) -> list[str]:
    """Ids this run measured that are no longer in the catalogue. Somebody removed them."""
    gone = sorted(claimed - present)
    if not gone:
        return []
    return [
        f"джерела зникли з каталогу під час прогону: {gone} — це чиєсь видалення, "
        "і відтворювати їх тут означало б скасувати його"
    ]
