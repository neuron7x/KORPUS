from __future__ import annotations

import hashlib
from collections.abc import Mapping


def collection_checks(
    payload: Mapping[str, object], observed: dict[str, int] | None
) -> dict[str, bool]:
    raw = payload.get("collection_nodeids")
    nodeids = [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    exact_list = bool(nodeids) and len(nodeids) == len(set(nodeids)) and nodeids == sorted(nodeids)
    digest = hashlib.sha256("\n".join(nodeids).encode("utf-8")).hexdigest()
    total = observed["tests"] + observed["skipped"] if observed is not None else -1
    return {
        "collection_list_exact": exact_list and len(nodeids) == len(raw),
        "collection_count_exact": payload.get("collection_count") == len(nodeids) == total,
        "collection_digest_exact": payload.get("collection_digest") == digest,
        "pytest_args_exact": payload.get("pytest_args") == ["apps/api/tests"],
    }
