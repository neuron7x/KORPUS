#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

url = os.environ.get("KORPUS_DATABASE_URL")
if not url:
    raise SystemExit("KORPUS_DATABASE_URL is required")
engine = create_engine(url, pool_pre_ping=True)
deadline = time.monotonic() + 60
last_error: Exception | None = None
while time.monotonic() < deadline:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("database ready")
        raise SystemExit(0)
    except SQLAlchemyError as exc:
        last_error = exc
        time.sleep(1)
print(f"database unavailable: {last_error}", file=sys.stderr)
raise SystemExit(1)
