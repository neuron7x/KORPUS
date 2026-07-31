from __future__ import annotations

import argparse
from datetime import date

from korpus.domain.models import AccessTier, Identity

from korpus.config import get_settings
from korpus.infrastructure.runtime import create_repository


def main() -> None:
    parser = argparse.ArgumentParser(prog="korpus")
    parser.add_argument("command", choices=["init-db", "verify-audit", "release-id"])
    args = parser.parse_args()
    settings = get_settings()
    repository = create_repository(settings)
    repository.initialize()
    if args.command == "init-db":
        print("database initialized")
    elif args.command == "verify-audit":
        print(repository.verify_audit().model_dump_json(indent=2))
    else:
        identity = Identity(
            subject=settings.dev_subject,
            roles=frozenset(role.strip() for role in settings.dev_roles.split(",") if role.strip()),
            clearance=AccessTier.parse(settings.dev_clearance),
            corpora=frozenset(corpus.strip() for corpus in settings.dev_corpora.split(",") if corpus.strip()),
        )
        print(repository.corpus_release_id(identity, identity.corpora, date.today()))


if __name__ == "__main__":
    main()
