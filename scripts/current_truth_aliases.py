from __future__ import annotations

from pathlib import Path


def alias_checks(root: Path, release: str) -> dict[str, bool]:
    """Aliases and package instructions are not current-source evidence.

    These paths have no producer that binds schema + verdict + current source digest.
    Admitting them by matching only the release string let an arbitrarily stale alias
    stay green through every source mutation.  They remain distributed documents, but
    contribute no predicate to current truth.
    """
    del root, release
    return {}
