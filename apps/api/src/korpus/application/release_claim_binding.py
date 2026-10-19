from typing import Any

from korpus.application.provenance import PROVENANCE_KEY

Binding = tuple[str | None, bool]


def _present(mapping: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    return [mapping[key] for key in keys if key in mapping]


def _declared(payload: dict[str, Any], keys: tuple[str, ...], inner: str) -> Binding:
    envelope = payload.get(PROVENANCE_KEY, {})
    if not isinstance(envelope, dict):
        return None, True
    raw = _present(payload, keys) + _present(envelope, (inner,))
    if any(not isinstance(value, str) for value in raw) or len(set(raw)) > 1:
        return None, True
    return (raw[0] if raw else None), False


def binding(payload: dict[str, Any]) -> tuple[str | None, bool]:
    return _declared(payload, ("source_tree_sha256", "source_digest"), "source_digest")


def binding_scope(payload: dict[str, Any]) -> tuple[str | None, bool]:
    return _declared(payload, ("digest_scope",), "digest_scope")
