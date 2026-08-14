from __future__ import annotations

from types import SimpleNamespace

import pytest

from korpus.config_policy import _validate_review_identity


def _settings(database_url: str, review_database_url: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        database_url=database_url,
        review_database_url=review_database_url,
    )


def test_controlled_postgres_requires_review_identity() -> None:
    settings = _settings("postgresql+psycopg://app:one@db:5432/korpus", None)

    with pytest.raises(ValueError, match="requires a separate review database identity"):
        _validate_review_identity(settings, controlled=True)


def test_review_identity_must_use_distinct_login_on_same_database() -> None:
    primary = "postgresql+psycopg://app:one@db:5432/korpus"
    settings = _settings(primary, "postgresql+psycopg://app:two@db:5432/korpus")

    with pytest.raises(ValueError, match="distinct PostgreSQL login"):
        _validate_review_identity(settings, controlled=True)


def test_review_identity_cannot_point_to_another_database() -> None:
    primary = "postgresql+psycopg://app:one@db:5432/korpus"
    settings = _settings(primary, "postgresql+psycopg://review:two@db:5432/other")

    with pytest.raises(ValueError, match="must target the primary PostgreSQL database"):
        _validate_review_identity(settings, controlled=True)


def test_distinct_review_login_for_same_database_is_admitted() -> None:
    primary = "postgresql+psycopg://app:one@db:5432/korpus"
    settings = _settings(primary, "postgresql+psycopg://review:two@db:5432/korpus")

    _validate_review_identity(settings, controlled=True)
