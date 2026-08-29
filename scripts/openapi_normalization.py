from __future__ import annotations


def normalize_openapi(value: object) -> object:
    """Canonicalize schema-generator encodings that are HTTP-equivalent."""
    if isinstance(value, list):
        return [normalize_openapi(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {key: normalize_openapi(item) for key, item in value.items()}
    if _is_binary_upload(normalized):
        normalized.pop("format", None)
        normalized["contentMediaType"] = "application/octet-stream"
    return normalized


def _is_binary_upload(value: dict) -> bool:
    return (
        value.get("title") == "File"
        and value.get("type") == "string"
        and value.get("format") == "binary"
    )
