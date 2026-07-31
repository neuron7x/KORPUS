#!/usr/bin/env python3
from __future__ import annotations

import os

from sqlalchemy import create_engine, text


ADMIN_URL = os.environ["KORPUS_POSTGRES_ADMIN_URL"]
APP_ROLE = os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app")
APP_PASSWORD = os.environ["KORPUS_POSTGRES_APP_PASSWORD"]

if not APP_ROLE.replace("_", "").isalnum():
    raise SystemExit("invalid PostgreSQL application role")

engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
with engine.connect() as connection:
    exists = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": APP_ROLE}
    ).scalar_one_or_none()
    escaped_password = APP_PASSWORD.replace("'", "''")
    if exists is None:
        connection.execute(text(f"CREATE ROLE \"{APP_ROLE}\" LOGIN PASSWORD '{escaped_password}'"))
    else:
        connection.execute(text(f"ALTER ROLE \"{APP_ROLE}\" PASSWORD '{escaped_password}'"))
    connection.execute(text(f'GRANT CONNECT ON DATABASE korpus_test TO "{APP_ROLE}"'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{APP_ROLE}"'))
    connection.execute(
        text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{APP_ROLE}"')
    )
    connection.execute(
        text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{APP_ROLE}"')
    )
engine.dispose()
print(f"prepared non-superuser PostgreSQL role: {APP_ROLE}")
