from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from korpus.application.retrieval import normalize_text, tokenize

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "У": "Y", "Х": "X", "І": "I", "Ј": "J",
})
_ROLE_MARKER = re.compile(
    r"(?:^|\n)\s*(system|developer|assistant|tool|користувач|система)\s*[:>]", re.I
)
_OVERRIDE = re.compile(
    r"\b(ignore|disregard|override|forget|bypass|reveal|exfiltrate|execute|follow)\b|"
    r"\b(ігноруй|забудь|обійди|розкрий|виконай|дотримуйся|перезапиши)\b",
    re.I,
)
_CONTROL_TARGET = re.compile(
    r"\b(previous|prior|hidden|system|developer|policy|instruction|prompt|secret|token|credential)s?\b|"
    r"\b(попередн|прихован|системн|розробник|політик|інструкц|промпт|секрет|токен|парол)",
    re.I,
)
_ENCODING_EVASION = re.compile(r"(?:base64|rot13|unicode|hex|\\u[0-9a-f]{4}|&#x?[0-9a-f]+;)", re.I)
_TOOL_DIRECTIVE = re.compile(
    r"\b(call|invoke|run|open|download|upload|send|post|delete)\s+"
    r"(?:the\s+)?(?:tool|function|url|file|request)\b",
    re.I,
)

_ABBREVIATIONS = {
    "р.", "ст.", "п.", "пп.", "рис.", "табл.", "ім.", "напр.", "див.", "т.д.", "т.п.",
    "mr.", "mrs.", "dr.", "prof.", "etc.", "e.g.", "i.e.", "no.",
}
_SENTENCE_END = {".", "!", "?", "…"}
_NEGATIONS = {"не", "ні", "немає", "заборонено", "not", "no", "never", "prohibited", "forbidden"}
_NUMERAL = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_NUMBER_UNIT = re.compile(
    r"(?P<number>[+-]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>%|мм|см|км|мс|м|с|хв|год|днів?|грн|usd|uah|kg|кг|кпа|kpa|па|pa|°c)?",
    re.I,
)


@dataclass(frozen=True)
class InjectionAssessment:
    blocked: bool
    score: int
    reasons: tuple[str, ...]


def canonical_control_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.translate(_ZERO_WIDTH).translate(_HOMOGLYPHS).casefold()


def assess_control_injection(text: str) -> InjectionAssessment:
    normalized = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).casefold()
    mapped = normalized.translate(_HOMOGLYPHS)
    canonical = normalized + "\n" + mapped
    reasons: list[str] = []
    if _ROLE_MARKER.search(canonical):
        reasons.append("role_marker")
    override = bool(_OVERRIDE.search(canonical))
    target = bool(_CONTROL_TARGET.search(canonical))
    if override:
        reasons.append("override_verb")
    if target:
        reasons.append("control_target")
    if _ENCODING_EVASION.search(canonical):
        reasons.append("encoding_evasion")
    if _TOOL_DIRECTIVE.search(canonical):
        reasons.append("tool_directive")
    if canonical.count("```" ) >= 2 and (override or target):
        reasons.append("instruction_fence")
    score = len(set(reasons))
    blocked = (override and target) or "role_marker" in reasons or score >= 3
    return InjectionAssessment(blocked=blocked, score=score, reasons=tuple(sorted(set(reasons))))


def segment_sentences(text: str) -> list[tuple[str, int, int]]:
    """Deterministic segmentation for prose, numbered clauses, and bullets.

    It preserves exact character offsets and avoids splitting common legal/technical
    abbreviations and decimal numbers.
    """
    output: list[tuple[str, int, int]] = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        boundary = False
        if char in _SENTENCE_END:
            prefix = text[max(start, index - 12): index + 1].strip().casefold()
            token = prefix.split()[-1] if prefix.split() else ""
            decimal = (
                char == "."
                and index > 0
                and index + 1 < length
                and text[index - 1].isdigit()
                and text[index + 1].isdigit()
            )
            boundary = not decimal and token not in _ABBREVIATIONS
        elif char == "\n":
            next_chunk = text[index + 1:index + 12]
            boundary = (
                bool(re.match(r"\s*(?:[-•*]|\d+[.)]|[А-ЯA-Z][.)])\s+", next_chunk))
                or text[index:index + 2] == "\n\n"
            )
        if boundary:
            end = index + 1
            raw = text[start:end]
            stripped = raw.strip()
            if stripped:
                leading = len(raw) - len(raw.lstrip())
                trailing = len(raw.rstrip())
                output.append((stripped, start + leading, start + trailing))
            start = end
        index += 1
    raw = text[start:]
    stripped = raw.strip()
    if stripped:
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        output.append((stripped, start + leading, start + trailing))
    return output


@dataclass(frozen=True)
class PropositionSignature:
    content_tokens: frozenset[str]
    negated: bool
    quantities: frozenset[tuple[Decimal, str]]


def proposition_signature(text: str) -> PropositionSignature:
    normalized = normalize_text(text)
    tokens = frozenset(tokenize(normalized))
    negated = bool(tokens.intersection(_NEGATIONS))
    quantities: set[tuple[Decimal, str]] = set()
    for match in _NUMBER_UNIT.finditer(normalized):
        raw = match.group("number").replace(",", ".")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        quantities.add((value, (match.group("unit") or "").casefold()))
    # Numerals are removed from the content set because they are already carried by
    # `quantities`, and leaving them in makes the similarity measure fight the check
    # that depends on it: two statements of one rule that differ *only* in the number
    # score as less alike precisely when the disagreement is sharpest ("строк … 24 год"
    # against "строк … 72 год" measured 0.50 against a 0.55 floor, so a numeric
    # conflict inside one span was never reached).
    content = {token for token in tokens.difference(_NEGATIONS) if not _NUMERAL.fullmatch(token)}
    return PropositionSignature(frozenset(content), negated, frozenset(quantities))


@dataclass(frozen=True)
class SupportVerdict:
    """How much of an answer is actually carried by the citations it ships with.

    `evidence_coverage` used to be `len(citations) / len(claims)`, which counts
    documents rather than statements: two citations on one claim produced 1.0 with a
    second claim standing on nothing, and the ratio could exceed 1.0 and trip the
    response model's `le=1` into a 500 — an unhandled crash where an abstention was
    required. The denominator here is claims, the numerator is claims whose every
    referenced span is present among the answer's own citations, and a claim that
    references a span the answer does not carry earns no partial credit.
    """

    coverage: float
    unsupported_claim_indexes: tuple[int, ...]
    reasons: tuple[str, ...]

    @property
    def aligned(self) -> bool:
        return not self.unsupported_claim_indexes


def verify_claim_support(
    claims: Sequence[tuple[int, Sequence[UUID]]], cited_span_ids: Collection[UUID]
) -> SupportVerdict:
    """Check every claim's span references against the spans the answer cites."""
    available = frozenset(cited_span_ids)
    unsupported: list[int] = []
    reasons: list[str] = []
    for index, span_ids in claims:
        referenced = frozenset(span_ids)
        if not referenced:
            unsupported.append(index)
            reasons.append(f"claim {index}: no evidence reference")
            continue
        missing = referenced.difference(available)
        if missing:
            unsupported.append(index)
            reasons.append(f"claim {index}: out_of_range span reference")
    total = len(claims)
    if total == 0:
        return SupportVerdict(0.0, (), ())
    coverage = (total - len(unsupported)) / total
    return SupportVerdict(coverage, tuple(unsupported), tuple(reasons))


def contradiction_reason(left: str, right: str, minimum_overlap: float = 0.55) -> str | None:
    a = proposition_signature(left)
    b = proposition_signature(right)
    union = a.content_tokens.union(b.content_tokens)
    overlap = len(a.content_tokens.intersection(b.content_tokens)) / max(len(union), 1)
    if overlap < minimum_overlap:
        return None
    if a.negated != b.negated:
        return "opposed_negation"
    by_unit_a: dict[str, set[Decimal]] = {}
    by_unit_b: dict[str, set[Decimal]] = {}
    for value, unit in a.quantities:
        by_unit_a.setdefault(unit, set()).add(value)
    for value, unit in b.quantities:
        by_unit_b.setdefault(unit, set()).add(value)
    for unit in set(by_unit_a).intersection(by_unit_b):
        if by_unit_a[unit].isdisjoint(by_unit_b[unit]):
            return f"numeric_conflict:{unit or 'unitless'}"
    return None


def extractive_support(claim: str, span_text: str) -> float:
    """How much of a claim its cited span actually carries, in [0, 1].

    `support_score` was the constant 1.0 and the thresholds are clamped to at most 1.0,
    so `support_score < minimum_support_score` was false for every configuration: the
    gate could not fail, `SupportState.UNSUPPORTED` was produced nowhere, and deleting
    the two lines changed no test (destruction stage, 2026-08-03). A predicate that
    cannot be false is not a safeguard; it is a claim about one.

    Measured as the share of the claim's content tokens present in the span. For a
    verbatim extract this is 1.0 by construction, which is the point: the number does
    not move while extraction is exact, and it falls the moment a claim carries
    anything its span does not — which is what the gate is for.
    """

    tokens = frozenset(tokenize(normalize_text(claim)))
    if not tokens:
        return 0.0
    available = frozenset(tokenize(normalize_text(span_text)))
    return len(tokens.intersection(available)) / len(tokens)


def refuting_sentence(claim: str, evidence_text: str) -> tuple[str, str] | None:
    """Find a sentence of `evidence_text` that contradicts `claim`.

    Contradiction used to be looked for only *between* the sentences an answer had
    already selected, so a span whose next sentence reversed the one quoted passed as
    `answered` (destruction stage B2, §2.0.1). The sentence a reader sees when they
    open the source is part of the evidence whether the extractor picked it or not.

    Identity is excluded rather than treated as agreement: the same sentence appearing
    twice is the extractor citing one passage, not the corpus saying two things.
    """

    reference = normalize_text(claim)
    for sentence, _start, _end in segment_sentences(evidence_text):
        if normalize_text(sentence) == reference:
            continue
        reason = contradiction_reason(claim, sentence)
        if reason is not None:
            return sentence, reason
    return None
