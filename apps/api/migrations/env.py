from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from korpus.infrastructure.migration_admission import (
    assert_online_admission,
    deny_offline_migration,
    migration_lock,
    preflight_source,
)
from korpus.infrastructure.migration_readonly import inspection_transaction
from korpus.infrastructure.repository import metadata
from sqlalchemy import Connection, engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option(
    "sqlalchemy.url",
    os.getenv("KORPUS_DATABASE_URL", config.get_main_option("sqlalchemy.url")),
)
target_metadata = metadata


def run_migrations_offline() -> None:
    deny_offline_migration()


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table_schema="public" if connection.dialect.name == "postgresql" else None,
    )


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        source_root = Path(context.script.dir).resolve().parents[2]
        preflight_source(source_root)
        _configure(connection)
        options = context.get_context().opts
        if "destination_rev" not in options:
            with inspection_transaction(connection, options.get("fn")):
                _configure(connection)
                context.run_migrations()
        else:
            with migration_lock(connection):
                assert_online_admission(
                    connection,
                    context.get_revision_argument(),
                    context.script.get_current_head(),
                    frozenset(revision.revision for revision in context.script.walk_revisions()),
                    source_root,
                )
                _configure(connection)
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
