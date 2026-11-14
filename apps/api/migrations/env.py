from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.script.revision import RevisionMap
from korpus.infrastructure.migration_admission import (
    BOOTSTRAP_HEAD,
    assert_online_admission,
    deny_offline_migration,
    migration_lock,
    preflight_source,
    resolve_proven_target,
)
from korpus.infrastructure.migration_baseline_proof import load_proven_revisions
from korpus.infrastructure.migration_readonly import (
    assert_migration_callback,
    inspection_transaction,
)
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
        proof = preflight_source(source_root)
        _configure(connection)
        options = context.get_context().opts
        if "destination_rev" not in options:
            with inspection_transaction(connection, options.get("fn")):
                context.script.revision_map = RevisionMap(
                    lambda: load_proven_revisions(source_root, proof.sources)
                )
                _configure(connection)
                context.run_migrations()
        else:
            destination = resolve_proven_target(options.get("destination_rev"), proof)
            assert_migration_callback(options.get("fn"))
            with migration_lock(connection):
                assert_online_admission(
                    connection,
                    destination,
                    BOOTSTRAP_HEAD,
                    frozenset((*proof.chain, BOOTSTRAP_HEAD)),
                    proof,
                )
                context.script.revision_map = RevisionMap(
                    lambda: load_proven_revisions(source_root, proof.sources)
                )
                _configure(connection)
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
