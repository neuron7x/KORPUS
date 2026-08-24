from __future__ import annotations

import pytest
from korpus.application.regression_receipt_identity import parse_regression_identity

S = "a" * 64
C = "b" * 64


def receipt():
    return {
        "release_tag": "v0.9.7",
        "source_digest": S,
        "collection_digest": C,
        "shard_index": 1,
        "shard_count": 64,
        "nodeids": ["a::x", "b::y"],
    }


def test_regression_receipt_identity_accepts_exact_freeze():
    v = parse_regression_identity(
        receipt(), release_tag="v0.9.7", source_digest=S, collection_digest=C
    )
    assert v.shard_index == 1 and v.nodeids == ("a::x", "b::y")


def test_regression_receipt_identity_rejects_release_mix():
    r = receipt()
    r["release_tag"] = "v0.9.6"
    with pytest.raises(ValueError, match="release mismatch"):
        parse_regression_identity(r, release_tag="v0.9.7", source_digest=S, collection_digest=C)


def test_regression_receipt_identity_rejects_collection_mix():
    r = receipt()
    r["collection_digest"] = "c" * 64
    with pytest.raises(ValueError, match="collection mismatch"):
        parse_regression_identity(r, release_tag="v0.9.7", source_digest=S, collection_digest=C)


def test_regression_receipt_identity_rejects_duplicate_nodeids():
    r = receipt()
    r["nodeids"] = ["a::x", "a::x"]
    with pytest.raises(ValueError, match="unique"):
        parse_regression_identity(r, release_tag="v0.9.7", source_digest=S, collection_digest=C)
