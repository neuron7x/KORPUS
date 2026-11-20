"""Assertions and neutral source bytes for the live pilot acceptance probe."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

ABSTENTION_TEXT = "У чинному перевіреному корпусі недостатньо доказів для надійної відповіді."
POSITIVE_LIMITATIONS = (
    "Відповідь екстрактивна: система не додає фактів поза точними цитованими реченнями.",
    "Retrieval score є ranking utility, а не ймовірністю істинності.",
)
REPEATED_SOURCE_LIMITATION = (
    "1 версій цитовано більше ніж один раз:"
    " кілька цитат з однієї версії — це одне джерело, а не кілька."
)
COMPOSITION_LIMITATION = (
    "Перший рядок написала система з наведених цитат: без "
    "цифр, без заперечень, лише словами, що є в цитатах."
)


class ProbeFailure(RuntimeError):
    """A bounded, credential-free diagnostic suitable for the probe report."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise ProbeFailure(message)


def object_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProbeFailure("response must be a JSON object")
    return dict(value)


def sha256(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def identifier(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise ProbeFailure("response identifier is not a UUID") from exc


@dataclass(frozen=True)
class Fixture:
    corpus_id: str
    marker: str = field(default_factory=lambda: f"PILOT{uuid4().hex}")
    as_of: date = field(default_factory=lambda: datetime.now(UTC).date())

    @property
    def content(self) -> bytes:
        return (
            "Розділ 1. Синтетичний навчальний каталог\n\n"
            f"Колір папки каталогу {self.marker} — бірюзовий.\n"
        ).encode()

    @property
    def question(self) -> str:
        return f"Який колір папки каталогу {self.marker}?"

    @property
    def before(self) -> str:
        return (self.as_of - timedelta(days=1)).isoformat()

    def query(self, *, before: bool = False) -> dict[str, object]:
        return {
            "text": self.question,
            "corpus_ids": [self.corpus_id],
            "as_of": self.before if before else self.as_of.isoformat(),
        }

    def metadata(self) -> dict[str, object]:
        return {
            "canonical_title": f"Synthetic acceptance catalog {self.marker}",
            "corpus_id": self.corpus_id,
            "issuer": "KORPUS synthetic acceptance fixture",
            "jurisdiction": "UA",
            "document_type": "acceptance_fixture",
            "classification": "public",
            "access_tier": 0,
        }

    def version(self) -> dict[str, object]:
        return {
            "revision": "acceptance-1",
            "publication_identifier": self.marker,
            "authority": "analytical",
            "publication_date": self.as_of.isoformat(),
            "effective_from": self.as_of.isoformat(),
        }


@dataclass(frozen=True)
class Credentials:
    owner: str = field(repr=False)
    readers: tuple[str, ...] = field(repr=False)
    reviewers: tuple[str, str, str] = field(repr=False)
    outsider: str | None = field(default=None, repr=False)


def validate_scope(corpus_id: str, reader_count: int) -> None:
    require(
        bool(re.fullmatch(r"pilot-smoke-[a-z0-9][a-z0-9._-]{0,50}", corpus_id)),
        "use a dedicated corpus named pilot-smoke-<name>",
    )
    require(3 <= reader_count <= 5, "provide between three and five distinct readers")


def bootstrap_identity(payload: object, corpus_id: str) -> tuple[str, set[str]]:
    bootstrap = object_payload(payload)
    identity = object_payload(bootstrap.get("identity"))
    subject = identity.get("subject")
    corpora = identity.get("corpora")
    permissions = bootstrap.get("effective_permissions")
    require(isinstance(subject, str) and bool(subject), "bootstrap omitted subject")
    require(isinstance(corpora, list) and corpus_id in corpora, "identity lacks smoke corpus")
    if not isinstance(permissions, list):
        raise ProbeFailure("bootstrap omitted effective permissions")
    require(all(isinstance(item, str) for item in permissions), "invalid permissions")
    return str(subject), set(permissions)


def require_reader(permissions: set[str]) -> None:
    require(
        permissions == {"answer:read", "document:list"},
        "reader must have only answer and document read permissions",
    )


def runtime_facts(payload: dict[str, Any]) -> dict[str, object]:
    release = payload.get("release")
    require(
        isinstance(release, str)
        and bool(re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", release)),
        "bootstrap release is invalid",
    )
    admission = object_payload(payload.get("admission"))
    thresholds: dict[str, float] = {}
    for name in ("min_retrieval_score", "min_query_coverage", "min_support_score"):
        value = admission.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProbeFailure("bootstrap threshold is not numeric")
        require(0 <= value <= 1, "bootstrap threshold is outside its range")
        thresholds[name] = float(value)
    return {"server_release": release, "admission_thresholds": thresholds}


def validate_upload(payload: object, fixture: Fixture) -> tuple[str, str]:
    result = object_payload(payload)
    document = object_payload(result.get("document"))
    version = object_payload(result.get("version"))
    require(result.get("duplicate") is False, "fixture upload unexpectedly deduplicated")
    require(
        isinstance(result.get("span_count"), int) and result["span_count"] > 0,
        "fixture upload produced no spans",
    )
    require(document.get("corpus_id") == fixture.corpus_id, "upload changed corpus")
    document_id = identifier(document.get("id"))
    version_id = identifier(version.get("id"))
    require(version.get("document_id") == document_id, "upload version belongs to another document")
    require(version.get("source_hash") == sha256(fixture.content), "upload source hash differs")
    require(version.get("review_state") == "quarantined", "upload bypassed quarantine")
    require(version.get("state_version") == 0, "upload has an unexpected state version")
    require(version.get("is_current") is False, "quarantined upload is current")
    return document_id, version_id


def require_abstention(payload: object) -> None:
    answer = object_payload(payload)
    require(answer.get("status") == "insufficient_evidence", "expected evidence abstention")
    require(answer.get("citations") == [], "abstention disclosed citations")
    require(answer.get("claims") == [], "abstention contains claims")
    require(answer.get("text") == ABSTENTION_TEXT, "abstention rendered unexpected answer text")
    require(answer.get("opening") == "", "abstention rendered an opening")
    require(
        answer.get("decision_reason") == "retrieval_gate_failed", "unexpected abstention reason"
    )
    require(
        answer.get("limitations") == ["Генерацію зупинено fail-closed."],
        "abstention rendered unexpected limitations",
    )
    verify_release(answer)


def verify_release(answer: dict[str, Any]) -> None:
    release = answer.get("corpus_release")
    require(
        isinstance(release, str) and re.fullmatch(r"[a-f0-9]{64}", release),
        "answer corpus release is not a content hash",
    )


def answer_citations(payload: object, fixture: Fixture) -> list[dict[str, Any]]:
    answer = object_payload(payload)
    require(answer.get("status") == "answered", "approved fixture was not answered")
    claims = answer.get("claims")
    citations = answer.get("citations")
    if not isinstance(claims, list) or not claims:
        raise ProbeFailure("answer has no claims")
    if not isinstance(citations, list) or not citations:
        raise ProbeFailure("answer has no citations")
    require(len(citations) <= 20, "answer returned too many citations for one tiny fixture")
    text = " ".join(str(object_payload(claim).get("text", "")) for claim in claims)
    require(fixture.marker in text and "бірюзовий" in text, "answer omitted the fixture fact")
    checked = [object_payload(citation) for citation in citations]
    verify_claim_links(claims, checked)
    verify_answer_text(answer, claims, checked, fixture)
    return checked


def verify_answer_text(
    answer: dict[str, Any],
    claims: list[Any],
    citations: list[dict[str, Any]],
    fixture: Fixture,
) -> None:
    texts = [str(object_payload(claim).get("text", "")) for claim in claims]
    require(
        answer.get("text") == "\n\n".join(texts),
        "answer text differs from the verified extractive claims",
    )
    opening = answer.get("opening")
    if not isinstance(opening, str):
        raise ProbeFailure("answer opening is not text")
    require(
        not opening or opening in fixture.content.decode("utf-8"),
        "answer opening is not contained in the independently known upload",
    )
    require(
        answer.get("decision_reason") == "extractive_claims_passed_calibrated_gates",
        "positive answer rendered an unexpected decision reason",
    )
    # The probe knows one dated fixture version. A caveat about another source or
    # arbitrary prose is not justified by this deliberately narrow acceptance case.
    limitations = list(POSITIVE_LIMITATIONS)
    if len(citations) > 1:
        limitations.append(REPEATED_SOURCE_LIMITATION)
    permitted = [[*limitations, COMPOSITION_LIMITATION]]
    if not opening:
        permitted.append(limitations)
    require(
        answer.get("limitations") in permitted,
        "positive answer rendered unexpected limitations",
    )
    verify_release(answer)


def verify_claim_links(claims: list[Any], citations: list[dict[str, Any]]) -> None:
    for value in claims:
        claim = object_payload(value)
        text = claim.get("text")
        evidence = claim.get("evidence_span_ids")
        require(isinstance(text, str) and bool(text), "claim text is missing")
        if not isinstance(evidence, list) or not evidence:
            raise ProbeFailure("claim has no evidence links")
        supporting = [citation for citation in citations if citation.get("span_id") in evidence]
        require(
            any(text == citation.get("quote") for citation in supporting),
            "claim is not bound to its cited quotation",
        )


def verify_citation(
    citation: dict[str, Any],
    span_payload: object,
    fixture: Fixture,
    document_id: str,
    version_id: str,
) -> None:
    span = object_payload(span_payload)
    require(citation.get("document_id") == document_id, "citation has wrong document")
    require(citation.get("version_id") == version_id, "citation has wrong version")
    require(span.get("id") == citation.get("span_id"), "span identity mismatch")
    require(span.get("document_id") == document_id, "span has wrong document")
    require(span.get("version_id") == version_id, "span has wrong version")
    source_hash = sha256(fixture.content)
    require(citation.get("source_hash") == source_hash, "citation source hash mismatch")
    require(span.get("source_hash") == source_hash, "span source hash mismatch")
    text, quote = span.get("text"), citation.get("quote")
    if not isinstance(text, str) or not isinstance(quote, str) or not quote:
        raise ProbeFailure("invalid quote text")
    require(
        text in fixture.content.decode("utf-8"),
        "disclosed span is not contained in the independently known upload",
    )
    require(span.get("text_hash") == sha256(text), "disclosed span hash mismatch")
    require(citation.get("span_hash") == sha256(text), "citation span hash mismatch")
    verify_quote(citation, text, quote)
    verify_source_metadata(citation, span, fixture)


def verify_source_metadata(
    citation: dict[str, Any], span: dict[str, Any], fixture: Fixture
) -> None:
    shared = {
        "revision": fixture.version()["revision"],
        "section": fixture.content.decode("utf-8").splitlines()[0],
        "page": None,
        "source_uri": None,
    }
    citation_fields = {
        **shared,
        "title": fixture.metadata()["canonical_title"],
        "presentation": "supported",
        "adjudication_reason": "тип питання не впізнано",
        "quote_starts_mid_sentence": False,
    }
    span_fields = {
        **shared,
        "document_title": fixture.metadata()["canonical_title"],
        "authority": "analytical",
        "publication_date": fixture.as_of.isoformat(),
        "effective_from": fixture.as_of.isoformat(),
        "effective_until": None,
        "rescinded_at": None,
    }
    for payload, expected in ((citation, citation_fields), (span, span_fields)):
        require(
            all(key in payload and payload[key] == value for key, value in expected.items()),
            "rendered source metadata differs from the independently known fixture",
        )
    require(type(span.get("ordinal")) is int and span["ordinal"] == 0, "unexpected fixture ordinal")


def verify_quote(citation: dict[str, Any], text: str, quote: str) -> None:
    start, end = citation.get("quote_start"), citation.get("quote_end")
    if not isinstance(start, int) or not isinstance(end, int):
        raise ProbeFailure("quote offsets must be integers")
    require(
        not isinstance(start, bool) and not isinstance(end, bool),
        "quote offsets cannot be booleans",
    )
    require(0 <= start < end <= len(text), "quote offsets exceed disclosed span")
    require(text[start:end] == quote, "quote is not the disclosed substring")
    require(citation.get("quote_hash") == sha256(quote), "quote hash mismatch")


def validate_transition(payload: object, version_id: str, target: str, sequence: int) -> None:
    version = object_payload(payload)
    require(version.get("id") == version_id, "review returned another version")
    require(version.get("review_state") == target, "review did not reach requested state")
    require(version.get("state_version") == sequence, "review state version did not advance")
    require(version.get("is_current") is (target == "approved"), "review currency mismatch")
