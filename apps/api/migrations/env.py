from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Column, MetaData, String, Table, engine_from_config, pool

from korpus.infrastructure import ingestion_jobs as _ingestion_jobs  # noqa: F401
from korpus.infrastructure.repository import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option(
    "sqlalchemy.url", os.getenv("KORPUS_DATABASE_URL", config.get_main_option("sqlalchemy.url"))
)
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.begin() as connection:
        # Alembic's default VARCHAR(32) cannot hold this repository's revision IDs.
        # Provision the bookkeeping table before Alembic creates its narrower default.
        Table(
            "alembic_version",
            MetaData(),
            Column("version_num", String(255), primary_key=True, nullable=False),
        ).create(connection, checkfirst=True)
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
