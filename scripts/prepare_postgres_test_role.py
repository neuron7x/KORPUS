#!/usr/bin/env python3
"""Compatibility wrapper for the generic PostgreSQL role provisioner."""
from __future__ import annotations

import os
import runpy
from pathlib import Path

os.environ.setdefault("KORPUS_DATABASE_URL", os.environ["KORPUS_POSTGRES_ADMIN_URL"])
runpy.run_path(str(Path(__file__).with_name("prepare_postgres_role.py")), run_name="__main__")
