"""Затвердження — не дія застосунку, і межа тут ГРАНТ, а не обіцянка коду.

Доти шлях перегляду й шлях застосунку ходили ОДНИМ логіном із табличним
`GRANT UPDATE`. Єдиним, що не давало застосунку самому проставити `approved_by`
і `evidence_digest`, була дисципліна виклику: писати лише через
`review_transitions`. Дисципліна не є межею — її не видно в каталозі, вона не
переживає нового шляху запису й ніколи не червоніє.

Тепер два твердження, і обидва перевіряються тут:

1. ПОКОЛОНКОВО. `korpus_app` не має `UPDATE` на колонках рішення рецензента;
   `korpus_review` має. Це факт каталогу, не наміру.
2. НА ВСТАВЦІ. Гранти на INSERT видаються на таблицю цілком, тож версію можна
   було НАРОДИТИ затвердженою й обійти весь розділ прав однією вставкою.
   Тригер `korpus_guard_app_version_insert` закриває саме це.

Позитивний контроль обов'язковий і стоїть поруч: шлях перегляду мусить
ПРАЦЮВАТИ, інакше виміряно було б лише те, що все заборонено.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
pytestmark = pytest.mark.postgres

_CONFIGURED = bool(APP_URL and ADMIN_URL and REVIEW_URL)
_REASON = "split PostgreSQL app/review/admin URLs are required"

#: Колонки, які виражають РІШЕННЯ рецензента, і те, чого в переліку немає навмисно.
DECISION_COLUMNS = (
    "review_state",
    "evidence_digest",
    "metadata_reviewed_by",
    "metadata_reviewer_credential_id",
    "content_reviewed_by",
    "content_reviewer_credential_id",
    "approved_at",
    "approved_by",
    "approver_credential_id",
    "is_current",
)
APPLICATION_COLUMNS = ("rescinded_at", "state_version", "source_uri")


def _can_update(url: str, table: str, column: str) -> bool:
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT has_column_privilege(current_user, :t, :c, 'UPDATE')"),
                    {"t": table, "c": column},
                ).scalar_one()
            )
    finally:
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
@pytest.mark.parametrize("column", DECISION_COLUMNS)
def test_the_application_login_cannot_write_a_reviewer_decision(column: str) -> None:
    assert APP_URL
    assert _can_update(APP_URL, "document_versions", column) is False


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
@pytest.mark.parametrize("column", DECISION_COLUMNS)
def test_the_review_login_can_write_exactly_those_columns(column: str) -> None:
    """Дуал: розділення, у якому не може ніхто, — це поломка, а не межа."""
    assert REVIEW_URL
    assert _can_update(REVIEW_URL, "document_versions", column) is True


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
@pytest.mark.parametrize("column", APPLICATION_COLUMNS)
def test_the_application_login_keeps_what_is_its_own(column: str) -> None:
    """Відкликання робить застосунок, і лічильник стану рухають обидва шляхи."""
    assert APP_URL
    assert _can_update(APP_URL, "document_versions", column) is True


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_the_document_tier_belongs_to_the_approver_not_to_the_submitter() -> None:
    assert APP_URL and REVIEW_URL
    assert _can_update(APP_URL, "documents", "access_tier") is False
    assert _can_update(REVIEW_URL, "documents", "access_tier") is True
    # І навпаки: рецензент не редагує назву документа.
    assert _can_update(APP_URL, "documents", "canonical_title") is True
    assert _can_update(REVIEW_URL, "documents", "canonical_title") is False


def _carrier_document(admin_url: str) -> str:
    document_id = str(uuid4())
    engine = create_engine(admin_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents(id, canonical_title, corpus_id, issuer, "
                    "jurisdiction, document_type, access_tier, classification, "
                    "created_at, compartments_json) VALUES (:id, 'Носій межі', 'public', "
                    "'ГШ', 'UA', 'order', 0, 'public', :now, '[]')"
                ),
                {"id": document_id, "now": datetime.now(UTC)},
            )
    finally:
        engine.dispose()
    return document_id


def _insert_version(url: str, document_id: str, **overrides: object) -> str | None:
    """None — вставка пройшла; інакше перший рядок відмови."""
    values = {
        "id": str(uuid4()),
        "document_id": document_id,
        "revision": "1",
        "source_hash": "a" * 64,
        "object_key": "boundary/1",
        "mime_type": "text/plain",
        "authority": "official_ua",
        "review_state": "quarantined",
        "state_version": 0,
        "is_current": False,
        "created_at": datetime.now(UTC),
        "publication_date": date(2020, 1, 1),
        "evidence_digest": None,
        **overrides,
    }
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_versions(id, document_id, revision, source_hash, "
                    "object_key, mime_type, authority, review_state, state_version, "
                    "is_current, created_at, publication_date, evidence_digest) VALUES "
                    "(:id,:document_id,:revision,:source_hash,:object_key,:mime_type,"
                    ":authority,:review_state,:state_version,:is_current,:created_at,"
                    ":publication_date,:evidence_digest)"
                ),
                values,
            )
        return None
    except Exception as error:  # noqa: BLE001
        return str(error).splitlines()[0]
    finally:
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
@pytest.mark.parametrize(
    "overrides",
    [
        {"review_state": "approved"},
        {"review_state": "content_reviewed"},
        {"evidence_digest": "f" * 64},
        {"is_current": True},
    ],
)
def test_the_application_login_cannot_give_birth_to_a_reviewed_version(
    overrides: dict[str, object],
) -> None:
    """Поколонковий розділ прав обходився б ОДНІЄЮ вставкою, якби не тригер."""
    assert APP_URL and ADMIN_URL
    refusal = _insert_version(APP_URL, _carrier_document(ADMIN_URL), **overrides)
    assert refusal is not None
    assert "cannot insert review-controlled state" in refusal, refusal


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_the_schema_owner_is_not_blocked_by_the_runtime_guard() -> None:
    """Тригер боронить РАНТАЙМ, не власника — інакше міграції й фікстури мертві.

    Перенесена версія питала `pg_has_role(session_user, ..., 'MEMBER')`, а для
    суперкористувача вона істинна для БУДЬ-ЯКОЇ ролі: власник схеми теж читався б
    як рантайм застосунку. Тут членство питається прямо в `pg_auth_members`.
    """
    assert ADMIN_URL
    refusal = _insert_version(
        ADMIN_URL,
        _carrier_document(ADMIN_URL),
        review_state="approved",
        evidence_digest="f" * 64,
        is_current=True,
    )
    assert refusal is None, refusal


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_the_marker_group_grants_nothing_by_itself() -> None:
    """Маркер існує, щоб тригер міг спитати «хто це», і не сміє нічого відмикати."""
    assert ADMIN_URL
    engine = create_engine(ADMIN_URL, future=True)
    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT rolcanlogin, rolsuper, rolinherit, rolbypassrls, rolcreaterole "
                    "FROM pg_catalog.pg_roles WHERE rolname = 'korpus_app_runtime'"
                )
            ).one()
            granted = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.table_privileges "
                    "WHERE grantee = 'korpus_app_runtime'"
                )
            ).scalar_one()
        assert role.rolcanlogin is False
        assert role.rolsuper is False
        assert role.rolinherit is False
        assert role.rolbypassrls is False
        assert role.rolcreaterole is False
        assert granted == 0
    finally:
        engine.dispose()
