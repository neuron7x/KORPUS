from __future__ import annotations

from datetime import date

import pytest

from korpus.application.corpus_snapshot import CorpusReadToken


def _token(release_id: str) -> CorpusReadToken:
    return CorpusReadToken(
        state_epoch=7,
        release_id=release_id,
        as_of=date(2026, 8, 14),
        corpus_ids=frozenset({"public"}),
        authorization_scope_id="b" * 64,
    )


def test_corpus_read_token_accepts_full_sha256_release_identity() -> None:
    token = _token("a" * 64)
    assert token.release_id == "a" * 64


@pytest.mark.parametrize(
    "release_id",
    [
        "a" * 16,
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
    ],
)
def test_corpus_read_token_rejects_truncated_or_noncanonical_release_identity(
    release_id: str,
) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _token(release_id)
