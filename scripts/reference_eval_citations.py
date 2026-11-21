"""Independent byte/identity checks over reader-authorized source disclosures."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from evaluation_http import InvalidEvidence, MeasurementUnavailable, canonical_uuid
from evaluation_json import is_digest

SpanReader = Callable[[str], dict[str, Any]]
MAX_CITATIONS = 64


def _hash(text: str) -> str:
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise InvalidEvidence("source text is not valid UTF-8") from exc


def _metadata_shape(payload: dict[str, Any], title: str) -> None:
    fields = {title, "revision", "page", "section", "source_uri"}
    if not fields.issubset(payload):
        raise InvalidEvidence("required source metadata is missing")
    for key, maximum in ((title, 500), ("revision", 120)):
        value = payload[key]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise InvalidEvidence("invalid required source metadata")
    page = payload["page"]
    if page is not None and (type(page) is not int or page < 1):
        raise InvalidEvidence("invalid source page")
    for key, maximum in (("section", 500), ("source_uri", 2000)):
        value = payload[key]
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            raise InvalidEvidence("invalid optional source metadata")


def _citation_shape(citation: dict[str, Any]) -> None:
    _metadata_shape(citation, "title")
    for key in ("document_id", "version_id", "span_id"):
        canonical_uuid(citation.get(key))
    for key in ("source_hash", "span_hash", "quote_hash"):
        if not is_digest(citation.get(key)):
            raise InvalidEvidence("invalid citation hash")
    quote = citation.get("quote")
    if not isinstance(quote, str) or not 1 <= len(quote) <= 1600:
        raise InvalidEvidence("invalid quotation text")
    if citation["quote_hash"] != _hash(quote):
        raise InvalidEvidence("quotation hash mismatch")
    start, end = citation.get("quote_start"), citation.get("quote_end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise InvalidEvidence("invalid quotation offsets")
    if end - start != len(quote):
        raise InvalidEvidence("quotation length differs from offsets")


def validate_citation(citation: dict[str, Any], span: dict[str, Any]) -> None:
    _citation_shape(citation)
    _metadata_shape(span, "document_title")
    for citation_key, span_key in (
        ("document_id", "document_id"),
        ("version_id", "version_id"),
        ("span_id", "id"),
    ):
        identifier = canonical_uuid(citation.get(citation_key))
        if identifier != span.get(span_key):
            raise InvalidEvidence("citation/source identity mismatch")
    source_hash = citation.get("source_hash")
    if not is_digest(source_hash) or source_hash != span.get("source_hash"):
        raise InvalidEvidence("citation/source hash mismatch")
    for citation_key, span_key in (
        ("title", "document_title"),
        ("revision", "revision"),
        ("page", "page"),
        ("section", "section"),
        ("source_uri", "source_uri"),
    ):
        if citation.get(citation_key) != span.get(span_key):
            raise InvalidEvidence("citation/source metadata mismatch")
    text, quote = span.get("text"), citation.get("quote")
    if not isinstance(text, str) or not isinstance(quote, str) or not 1 <= len(quote) <= 1600:
        raise InvalidEvidence("invalid source or quotation text")
    if span.get("text_hash") != _hash(text) or citation.get("span_hash") != _hash(text):
        raise InvalidEvidence("disclosed span hash mismatch")
    start, end = citation.get("quote_start"), citation.get("quote_end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise InvalidEvidence("invalid quotation offsets")
    if text[start:end] != quote:
        raise InvalidEvidence("quotation is not the disclosed source substring")
    if citation.get("quote_hash") != _hash(quote):
        raise InvalidEvidence("quotation hash mismatch")


def citation_problems(citations: object, reader: SpanReader | None) -> tuple[list[str], list[str]]:
    if not isinstance(citations, list) or len(citations) > MAX_CITATIONS:
        return ["invalid or excessive citation collection"], []
    if citations and reader is None:
        return ["citation source verification was not performed"], []
    problems: list[str] = []
    unavailable: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            problems.append("citation is not an object")
            continue
        try:
            _citation_shape(citation)
            span_id = canonical_uuid(citation.get("span_id"))
            if reader is None:
                raise InvalidEvidence("citation source verification was not performed")
            span = reader(span_id)
            if not isinstance(span, dict):
                raise InvalidEvidence("source disclosure is not an object")
            validate_citation(citation, span)
        except InvalidEvidence as exc:
            problems.append(str(exc))
        except MeasurementUnavailable as exc:
            unavailable.append(str(exc))
    return problems, unavailable
