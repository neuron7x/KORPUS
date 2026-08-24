"""Boolean adapters for fail-closed destination parsers used in requirement registries."""
from __future__ import annotations

from korpus.security.external_destination import parse_external_https_url


def is_external_https_url(value: object, *, allow_query: bool = True) -> bool:
    try:
        parse_external_https_url(str(value), allow_query=allow_query)
    except (TypeError, ValueError):
        return False
    return True
