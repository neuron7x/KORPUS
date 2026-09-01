"""widen alembic_version so a descriptive revision id is not a schema error

Revision ID: 0021_alembic_version_width
Revises: 0020_rls_identity_boundary

`alembic_version.version_num` — `varchar(32)`, і це не діагностується як
обмеження, поки ідентифікатор ревізії коротший. Наступна міграція звалась
`0021_approval_provenance_boundary` — 33 символи — і впала на ЗАПИСІ власного
імені вже після того, як застосувала всю свою DDL:

    psycopg.errors.StringDataRightTruncation: value too long for type
    character varying(32)

Тобто схема була змінена, а версія не записана: наступний прогін застосував би
ту саму міграцію вдруге. Відмова діагностична (транзакційна DDL PostgreSQL
відкочує все разом), але ціна помилки — не в цьому, а в тому, що обмеження
живе в ІМЕНІ, і його не видно, поки імена короткі.

Портовано з GitHub-лінії (`0016a_alembic_version_width`), де його зустріли з
тієї ж причини. Власне ім'я цієї ревізії — 26 символів: міграція, яка розширює
поле, мусить вміститись у поле ДО розширення.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_alembic_version_width"
down_revision: str | None = "0020_rls_identity_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)")
