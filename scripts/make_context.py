"""Preserve source/distribution subjects when reading Make's declared contexts."""

from __future__ import annotations

import re


def expand_context_defaults(text: str, overrides: dict[str, str] | None = None) -> str:
    """Expand named scalar context defaults; runtime artifact paths stay opaque."""
    values = dict(
        re.findall(r"^([A-Z][A-Z0-9_]*_CONTEXT)\s*\?=\s*([A-Z][A-Z0-9_]*)\s*$", text, re.M)
    )
    values.update(overrides or {})
    return re.sub(
        r"\$\(([A-Z][A-Z0-9_]*_CONTEXT)\)",
        lambda match: values.get(match.group(1), match.group(0)),
        text,
    )


def invocation_contexts(command: str) -> dict[str, str]:
    """Only assignments in this shell command apply to this make invocation."""
    command = re.split(r"&&|\|\||[;|]", command, maxsplit=1)[0]
    return dict(re.findall(r"\b([A-Z][A-Z0-9_]*_CONTEXT)=([A-Z][A-Z0-9_]*)\b", command))
