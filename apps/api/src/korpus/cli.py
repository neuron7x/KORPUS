from __future__ import annotations

import argparse

from korpus.config import get_settings
from korpus.infrastructure.repository import SqlRepository


def main() -> None:
    parser = argparse.ArgumentParser(prog="korpus")
    parser.add_argument("command", choices=["init-db", "verify-audit", "release-id"])
    args = parser.parse_args()
    settings = get_settings()
    repository = SqlRepository(settings.database_url, settings.resolved_audit_hmac_key)
    repository.initialize()
    if args.command == "init-db":
        print("database initialized")
    elif args.command == "verify-audit":
        print(repository.verify_audit().model_dump_json(indent=2))
    else:
        print(repository.corpus_release_id())


if __name__ == "__main__":
    main()
