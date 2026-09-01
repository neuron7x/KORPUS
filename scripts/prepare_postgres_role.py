#!/usr/bin/env python3
"""Create the non-superuser application role with an explicit fail-closed grant set."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

# Every table the application touches has to appear in exactly one of these lists —
# the role starts from REVOKE ALL, so an omission is a runtime InsufficientPrivilege
# rather than a lax grant. Two tables added by later migrations were missing:
# document_compartments (0004) and ingestion_jobs (0005). Nothing caught it because
# the SQLite configuration has no roles at all, and the PostgreSQL job had never run
# past migration 0001. test_postgres_role_grants.py now fails when a table exists in
# the metadata and in none of these lists.
READ_WRITE_TABLES = (
    "documents",
    "document_versions",
    "document_compartments",
    "evidence_spans",
    "span_embeddings",
    "ingestion_jobs",
    # ACT-001. Read-write rather than append-only: an account is disabled and re-enabled,
    # a subscription moves between states, a conversation is archived. What must not be
    # rewritable is the audit trail of those changes, and that is `audit_events` below.
    "accounts",
    "plans",
    "subscriptions",
    "billing_events",
    "conversations",
    "messages",
    # ACT-LRN-002. Learning content is written only while draft; PostgreSQL triggers
    # make published content immutable and invalidate it when canonical source state changes.
    "learning_courses",
    "learning_course_versions",
    "learning_modules",
    "learning_lessons",
    "learning_objectives",
    "learning_objective_competencies",
    "learning_source_bindings",
    "learning_source_binding_spans",
    "learning_lesson_blocks",
    "learning_block_sources",
    "learning_prerequisites",
    "learning_publications",
    "learning_mastery",
    "competency_frameworks",
    "operational_roles",
    "operational_tasks",
    "operational_competencies",
    "operational_role_tasks",
    "operational_task_competencies",
)
AUDIT_APPEND_TABLES = ("audit_events",)
AUDIT_MUTABLE_TABLES = ("audit_anchor_outbox", "audit_heads", "corpus_state_epoch")
#: Епоха стану корпусу мутабельна за призначенням: тригер піднімає її на КОЖНІЙ
#: зміні складу доказів, і без права оновлювати її застосунок не міг би зафіксувати,
#: що корпус зрушив між двома читаннями однієї відповіді.


def read_secret(name: str, file_name: str) -> str:
    direct = os.getenv(name)
    path = os.getenv(file_name)
    value = Path(path).read_text(encoding="utf-8").strip() if path else (direct or "")
    if not value:
        raise SystemExit(f"{name} or {file_name} is required")
    return value


def quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


#: Кожна колонка `document_versions`, названа ЯВНО. Виведений із метаданих перелік
#: звірявся б сам із собою: нова колонка потрапила б і в перелік, і в грант, і ніхто
#: б не спитав, чиє це право.
VERSION_COLUMNS = (
    "id",
    "document_id",
    "revision",
    "publication_identifier",
    "source_uri",
    "source_hash",
    "evidence_digest",
    "object_key",
    "mime_type",
    "publication_date",
    "effective_from",
    "effective_until",
    "rescinded_at",
    "authority",
    "source_key_id",
    "source_signature_b64",
    "content_fingerprint",
    "near_duplicate_of_version_id",
    "near_duplicate_similarity",
    "near_duplicate_acknowledged_by",
    "extraction_text_chars",
    "extraction_alnum_ratio",
    "extraction_replacement_ratio",
    "extraction_quality_flags_json",
    "extraction_quality_acknowledged_by",
    "review_state",
    "supersedes_version_id",
    "state_version",
    "metadata_reviewed_by",
    "metadata_reviewer_credential_id",
    "content_reviewed_by",
    "content_reviewer_credential_id",
    "approved_at",
    "approved_by",
    "approver_credential_id",
    "is_current",
    "created_at",
)

#: Колонки `documents`, названі явно з тієї ж причини.
DOCUMENT_COLUMNS = (
    "id",
    "canonical_title",
    "corpus_id",
    "issuer",
    "jurisdiction",
    "document_type",
    "access_tier",
    "classification",
    "compartments_json",
    "created_at",
)

#: Гриф документа встановлює ЗАТВЕРДЖУВАЧ, а не той, хто подав.
REVIEW_CONTROLLED_DOCUMENT_COLUMNS = frozenset({"access_tier"})

#: Колонки, які виражають РІШЕННЯ рецензента. `rescinded_at` і `state_version` тут
#: НЕМАЄ навмисно: відкликання робить застосунок, а лічильник версії стану рухають
#: обидва шляхи, і забрати його означало б зламати оптимістичне блокування.
REVIEW_CONTROLLED_COLUMNS = frozenset(
    {
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
    }
)

admin_url = os.environ["KORPUS_DATABASE_URL"]
app_role = os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app")
app_password = read_secret("KORPUS_POSTGRES_APP_PASSWORD", "KORPUS_POSTGRES_APP_PASSWORD_FILE")
if not app_role.replace("_", "").isalnum() or not app_role[0].isalpha():
    raise SystemExit("invalid PostgreSQL application role")
parsed = urlparse(admin_url.replace("postgresql+psycopg", "postgresql", 1))
database = parsed.path.lstrip("/")
if not database or not database.replace("_", "").replace("-", "").isalnum():
    raise SystemExit("invalid PostgreSQL database name")

engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
role_sql = quoted_identifier(app_role)
database_sql = quoted_identifier(database)
escaped_password = app_password.replace("'", "''")
with engine.connect() as connection:
    exists = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": app_role}
    ).scalar_one_or_none()
    verb = "ALTER ROLE" if exists is not None else "CREATE ROLE"
    login = "" if exists is not None else "LOGIN "
    connection.execute(
        text(
            f"{verb} {role_sql} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOINHERIT NOBYPASSRLS CONNECTION LIMIT 64 PASSWORD '{escaped_password}'"
        )
    )
    connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    connection.execute(text(f"GRANT CONNECT ON DATABASE {database_sql} TO {role_sql}"))
    connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role_sql}"))
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role_sql}"))
    connection.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role_sql}"))
    for table_name in READ_WRITE_TABLES:
        connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                f"{quoted_identifier(table_name)} TO {role_sql}"
            )
        )
    for table_name in AUDIT_APPEND_TABLES:
        connection.execute(
            text(f"GRANT SELECT, INSERT ON TABLE {quoted_identifier(table_name)} TO {role_sql}")
        )
    for table_name in AUDIT_MUTABLE_TABLES:
        connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE ON TABLE "
                f"{quoted_identifier(table_name)} TO {role_sql}"
            )
        )
    connection.execute(text(f"GRANT SELECT ON TABLE alembic_version TO {role_sql}"))
    # ── Колонки рішення рецензента ─────────────────────────────────────────────
    # Затвердження — не дія застосунку. Табличний `GRANT UPDATE` віддавав ці
    # колонки застосунковому логінові разом з усіма іншими, і єдиним, що їх
    # боронило, була обіцянка коду ходити через шлях перегляду. Тепер межа —
    # ГРАНТ: `UPDATE` видається поколонково, а колонки рішення з переліку
    # ВИКЛЮЧЕНІ. Помилка тут падає закрито: забута колонка = відмова в записі,
    # а не тихо відкрите право.
    # ── Маркерна група ─────────────────────────────────────────────────────────
    # Група НІЧОГО не дає: NOLOGIN, NOINHERIT, без жодного гранта. Вона потрібна,
    # щоб тригер `korpus_guard_app_version_insert` міг спитати «чи це рантайм
    # застосунку», не тримаючи списку імен усередині бази. Членство знімається
    # й видається наново при кожній переприв'язці: застаріле членство — це право,
    # якого вже не давали, і жоден GRANT його не покаже.
    marker = quoted_identifier(f"{app_role}_runtime")
    if (
        connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
            {"role": f"{app_role}_runtime"},
        ).scalar_one_or_none()
        is None
    ):
        connection.execute(text(f"CREATE ROLE {marker} NOLOGIN"))
    connection.execute(
        text(
            f"ALTER ROLE {marker} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
    )
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {marker}"))
    connection.execute(text(f"REVOKE ALL ON SCHEMA public FROM {marker}"))
    for parent in (
        connection.execute(
            text(
                "SELECT parent.rolname FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles parent ON parent.oid = m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid = m.member "
                "WHERE member.rolname = :role"
            ),
            {"role": app_role},
        )
        .scalars()
        .all()
    ):
        connection.execute(text(f"REVOKE {quoted_identifier(str(parent))} FROM {role_sql}"))
    connection.execute(text(f"GRANT {marker} TO {role_sql}"))

    connection.execute(text(f"REVOKE UPDATE ON TABLE document_versions FROM {role_sql}"))
    # Те саме для грифа документа. `REVOKE UPDATE (col)` за наявності ТАБЛИЧНОГО
    # гранта — не помилка й не дія: PostgreSQL лишає табличне право, і поколонкова
    # відмова просто не має що знімати. Перша версія цього рядка була саме такою й
    # виглядала як межа, не будучи нею. Тому спершу табличне право знімається цілком.
    connection.execute(text(f"REVOKE UPDATE ON TABLE documents FROM {role_sql}"))
    document_columns = ", ".join(
        quoted_identifier(name)
        for name in DOCUMENT_COLUMNS
        if name not in REVIEW_CONTROLLED_DOCUMENT_COLUMNS
    )
    connection.execute(text(f"GRANT UPDATE ({document_columns}) ON TABLE documents TO {role_sql}"))
    application_columns = [
        name for name in VERSION_COLUMNS if name not in REVIEW_CONTROLLED_COLUMNS
    ]
    columns_sql = ", ".join(quoted_identifier(name) for name in application_columns)
    connection.execute(
        text(f"GRANT UPDATE ({columns_sql}) ON TABLE document_versions TO {role_sql}")
    )
    # No blanket/default privileges: a new migration remains inaccessible until reviewed here.
    connection.execute(text(f"ALTER ROLE {role_sql} SET statement_timeout = '60s'"))
    connection.execute(text(f"ALTER ROLE {role_sql} SET lock_timeout = '5s'"))
    connection.execute(
        text(f"ALTER ROLE {role_sql} SET idle_in_transaction_session_timeout = '60s'")
    )

# ── Логін переходів перегляду ────────────────────────────────────────────────────
# Третій логін, і його відмінність від застосункового рівно одна: він МАЄ право
# UPDATE на колонках рішення рецензента, а застосунковий — НЕ має. Затвердження
# перестає бути обіцянкою коду й стає грантом. Створюється лише за наявності пароля:
# мовчазний дефолт означав би третій логін із відомим паролем.
review_role = os.getenv("KORPUS_POSTGRES_REVIEW_ROLE", "korpus_review")
review_password = os.getenv("KORPUS_POSTGRES_REVIEW_PASSWORD")
if review_password is None:
    path = os.getenv("KORPUS_POSTGRES_REVIEW_PASSWORD_FILE")
    if path:
        review_password = Path(path).read_text(encoding="utf-8").strip()
if review_password:
    if not review_role.replace("_", "").isalnum() or not review_role[0].isalpha():
        raise SystemExit("invalid PostgreSQL review role")
    if review_role in {app_role, os.getenv("KORPUS_POSTGRES_AUTHZ_ROLE", "korpus_authz")}:
        raise SystemExit("review role must be distinct from the application and broker roles")
    review_sql = quoted_identifier(review_role)
    escaped_review = review_password.replace("'", "''")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": review_role}
        ).scalar_one_or_none()
        verb = "ALTER ROLE" if exists is not None else "CREATE ROLE"
        login = "" if exists is not None else "LOGIN "
        connection.execute(
            text(
                f"{verb} {review_sql} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE "
                f"NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 32 "
                f"PASSWORD '{escaped_review}'"
            )
        )
        connection.execute(text(f"GRANT CONNECT ON DATABASE {database_sql} TO {review_sql}"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {review_sql}"))
        connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {review_sql}"))
        # Перегляд читає документи й прольоти, щоб перевірити перехід, і пише лише
        # версії. Журнал він ДОПИСУЄ: перехід і його подія — одна транзакція.
        for table_name in ("documents", "document_compartments", "evidence_spans"):
            connection.execute(
                text(f"GRANT SELECT ON TABLE {quoted_identifier(table_name)} TO {review_sql}")
            )
        connection.execute(text(f"GRANT SELECT, UPDATE ON TABLE document_versions TO {review_sql}"))
        # Гриф документа — окреме рішення затверджувача, і живе воно в `documents`.
        connection.execute(text(f"GRANT UPDATE (access_tier) ON TABLE documents TO {review_sql}"))
        for table_name in AUDIT_APPEND_TABLES:
            connection.execute(
                text(
                    f"GRANT SELECT, INSERT ON TABLE {quoted_identifier(table_name)} TO {review_sql}"
                )
            )
        for table_name in AUDIT_MUTABLE_TABLES:
            connection.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE ON TABLE "
                    f"{quoted_identifier(table_name)} TO {review_sql}"
                )
            )
        connection.execute(text(f"GRANT SELECT ON TABLE alembic_version TO {review_sql}"))
        for claim in (
            "subject",
            "clearance",
            "corpora",
            "classifications",
            "compartments",
            "roles",
        ):
            connection.execute(
                text(f"GRANT EXECUTE ON FUNCTION public.korpus_rls_{claim}() TO {review_sql}")
            )
        connection.execute(text(f"ALTER ROLE {review_sql} SET statement_timeout = '60s'"))
        connection.execute(text(f"ALTER ROLE {review_sql} SET lock_timeout = '5s'"))
        connection.execute(
            text(f"ALTER ROLE {review_sql} SET idle_in_transaction_session_timeout = '60s'")
        )
    engine.dispose()
    print(f"prepared PostgreSQL review role: {review_role} on {database}")


# ── Брокер RLS ───────────────────────────────────────────────────────────────────
# Другий логін, і його єдина відмінність від застосункового — право ВИКЛИКАТИ
# `korpus_bind_rls_context`. Застосунковий логін цього права не має, а таблиці
# контексту не бачить зовсім, тож не може ні підняти собі гриф, ні прочитати
# чужий. Роль створюється лише тоді, коли є пароль: мовчазний дефолт означав би
# другий логін із відомим паролем, тобто гіршу межу, ніж узагалі без нього.
authz_role = os.getenv("KORPUS_POSTGRES_AUTHZ_ROLE", "korpus_authz")
authz_password = os.getenv("KORPUS_POSTGRES_AUTHZ_PASSWORD")
if authz_password is None:
    path = os.getenv("KORPUS_POSTGRES_AUTHZ_PASSWORD_FILE")
    if path:
        authz_password = Path(path).read_text(encoding="utf-8").strip()
if authz_password:
    if not authz_role.replace("_", "").isalnum() or not authz_role[0].isalpha():
        raise SystemExit("invalid PostgreSQL authz role")
    if authz_role == app_role:
        raise SystemExit("authz role must be distinct from the application role")
    authz_sql = quoted_identifier(authz_role)
    escaped_authz = authz_password.replace("'", "''")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": authz_role}
        ).scalar_one_or_none()
        verb = "ALTER ROLE" if exists is not None else "CREATE ROLE"
        login = "" if exists is not None else "LOGIN "
        connection.execute(
            text(
                f"{verb} {authz_sql} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE "
                f"NOINHERIT NOBYPASSRLS CONNECTION LIMIT 32 PASSWORD '{escaped_authz}'"
            )
        )
        connection.execute(text(f"GRANT CONNECT ON DATABASE {database_sql} TO {authz_sql}"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {authz_sql}"))
        connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {authz_sql}"))
        broker = (
            "public.korpus_bind_rls_context"
            "(integer,bigint,name,text,integer,jsonb,jsonb,jsonb,jsonb)"
        )
        present = connection.execute(
            text(
                "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.proname = 'korpus_bind_rls_context'"
            )
        ).scalar_one_or_none()
        if present is None:
            raise SystemExit(
                "korpus_bind_rls_context is absent: run the migrations before preparing roles"
            )
        connection.execute(text(f"REVOKE ALL ON FUNCTION {broker} FROM {role_sql}"))
        connection.execute(text(f"GRANT EXECUTE ON FUNCTION {broker} TO {authz_sql}"))
        # Читачі claim'ів — застосунковому логінові ТАК: вираз політики виконується
        # від імені того, хто робить запит, і без цього права жоден SELECT не пройде.
        # Писати вони не вміють, тож право їх викликати нічого не відмикає. Брокер —
        # окремо, і саме він лишається недосяжним.
        for claim in (
            "subject",
            "clearance",
            "corpora",
            "classifications",
            "compartments",
            "roles",
        ):
            reader_fn = f"public.korpus_rls_{claim}()"
            connection.execute(text(f"GRANT EXECUTE ON FUNCTION {reader_fn} TO {role_sql}"))
            connection.execute(text(f"REVOKE ALL ON FUNCTION {reader_fn} FROM {authz_sql}"))
        connection.execute(text(f"ALTER ROLE {authz_sql} SET statement_timeout = '10s'"))
        connection.execute(text(f"ALTER ROLE {authz_sql} SET lock_timeout = '5s'"))
        connection.execute(
            text(f"ALTER ROLE {authz_sql} SET idle_in_transaction_session_timeout = '30s'")
        )
    engine.dispose()
    print(f"prepared PostgreSQL RLS broker role: {authz_role} on {database}")

print(f"prepared least-privilege non-superuser PostgreSQL role: {app_role} on {database}")
