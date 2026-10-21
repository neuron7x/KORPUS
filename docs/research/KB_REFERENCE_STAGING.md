# KORPUS KB — metadata-only reference staging

**State:** source *leads*, not indexed knowledge. This is an isolated import of the
18 source **metadata records** from `KORPUS_KB_Foundation_v1.0.0.zip` (Foundation
SHA-256 `8e2a4d23feced6e81b90b3bb4557dbe0859b6a25e4f1f5abbb3a20db655b194a`).
No PDFs, course materials, extracted text, model claims, human approvals or production
permissions are included. No authenticated/permissioned source exports are attempted.

## Gate and boundary

Run `python scripts/kb_reference_admission.py` from any directory. The default
catalog is `config/kb/reference_sources.jsonl`. `structure_status=PASS` certifies
**local JSONL shape only**, never publisher identity, licensing, semantic validity or
network access. `candidate_status=BLOCKED` and `production_authorized=false` are
mandatory; no ingest/index/export operation is performed. Errors exit nonzero.

The staging catalog is not an import payload for `scripts/import_corpus.py` or the
runtime ingestion service. Before such an integration, independently verify each
source's true publisher, current document/version and exact reuse permissions;
retain immutable original hashes/source maps; complete authenticated rights/content
reviews and domain-specific audits; then use the existing `CorpusGovernanceProfile`
plus production ingestion and authorization checks. Source metadata is not evidence
of the document contents. In particular, `PUBLIC_LANDING` is not a reuse licence.

## Security scope

This stage contains only public reference URL metadata for instructor methods,
first-aid education, humanitarian law, civil preparedness, defensive digital hygiene,
engineering safety, accessibility/metadata provenance and agency reliability.
It has no network collector and does not grant access to NATO/Army+ content. Never
promote excluded weapon, targeting, explosive, offensive cyber or restricted materials
by changing the catalog's labels.

## JSONL framing and parser budget

Records are separated only by LF; CRLF and an optional final newline are supported.
Unicode line-separator characters inside JSON strings are data, not record boundaries.
For existing compatibility, ASCII JSON-whitespace-only blank lines are ignored; this
is an explicit extension, not strict JSON Lines conformance. Other whitespace-only
lines are malformed and must not disappear. `MAX_ROWS` bounds accepted **plus rejected**
nonblank rows, so malformed rows cannot evade the parse/diagnostic budget.
`source_records` still counts schema-valid metadata rows, never indexable records.
The separate 128-KiB descriptor-read bound and all production-denial fields are unchanged.

References: https://jsonlines.org/ and
https://docs.python.org/3.12/library/stdtypes.html#str.splitlines .

## URL component admission

Metadata reference URLs must have no query or fragment component, including an
empty component introduced by a literal `?` or `#`. The identity key deliberately
contains only hostname and canonical path; silently admitting and dropping those
delimiters would conflate distinct URI references. Percent-encoded `%3F` and `%23`
in a path remain path data and are not decoded into component separators.
This is a local syntax/identity policy, never DNS, egress or reuse authorization.

Reference: RFC 3986 sections 5.3 and 6.2.3,
https://www.rfc-editor.org/rfc/rfc3986.html .
