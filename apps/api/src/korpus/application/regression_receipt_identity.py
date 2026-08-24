from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RegressionReceiptIdentity:
    release_tag: str
    source_digest: str
    collection_digest: str
    shard_index: int
    shard_count: int
    nodeids: tuple[str, ...]


def parse_regression_identity(receipt: Mapping[str, object], *, release_tag: str, source_digest: str, collection_digest: str) -> RegressionReceiptIdentity:
    if str(receipt.get("release_tag", "")) != release_tag:
        raise ValueError("regression receipt release mismatch")
    if str(receipt.get("source_digest", "")) != source_digest:
        raise ValueError("regression receipt source mismatch")
    if str(receipt.get("collection_digest", "")) != collection_digest:
        raise ValueError("regression receipt collection mismatch")
    index, count = receipt.get("shard_index"), receipt.get("shard_count")
    if isinstance(index, bool) or not isinstance(index, int) or isinstance(count, bool) or not isinstance(count, int) or count <= 0 or not 0 <= index < count:
        raise ValueError("invalid shard coordinates")
    raw = receipt.get("nodeids")
    if not isinstance(raw, list) or not raw or any(not isinstance(item, str) or not item for item in raw):
        raise ValueError("nodeids must be a non-empty string list")
    nodeids = tuple(raw)
    if len(nodeids) != len(set(nodeids)):
        raise ValueError("nodeids must be unique within a shard")
    return RegressionReceiptIdentity(release_tag, source_digest, collection_digest, index, count, nodeids)
