# Semantic release identity v2

`CorpusReadToken.release_id` is the SHA-256 identity of the **visible source-of-truth corpus semantics that can change an answer**, not a database-row checksum and not an algorithm/configuration identifier.

Domain separator: `korpus-temporal-semantic-release-v2\0`.

## Directly committed member fields

| Field | Dependency |
|---|---|
| `document_id` | citation/member identity |
| `version_id` | citation/version identity |
| `source_hash` | source-byte provenance |
| `review_state` | answer eligibility |
| `evidence_digest` | exact sealed evidence set |
| `canonical_title` | outward citation title |
| `corpus_id` | authorization/scope |
| `access_tier` | authorization and model-egress ceiling |
| `classification` | authorization |
| canonical `documents.compartments_json` set | materialized `DocumentRecord` authorization re-check |
| canonical `document_compartments` relation set | SQL visibility predicate |
| `revision` | outward citation revision |
| nullable `source_uri` | outward citation provenance |
| nullable `publication_date` | currency and temporal ranking |
| nullable `effective_from` | currency and temporal ranking |
| nullable `effective_until` | currency |
| nullable `rescinded_at` | currency |
| `authority` | answer eligibility and authority ranking |
| nullable `supersedes_version_id` | supersession semantics |

Rows are set-normalized and sorted. Every scalar is length-framed. Nullable values use an explicit presence tag; set-valued compartments are sorted and length-framed before hashing. SQL join order, duplicate projection rows, JSON list order and set order therefore do not define release identity.

## Transitively committed evidence

`evidence_digest` commits the exact ordered persisted span set: span id, ordinal, nullable page, nullable section and verified text hash. The text hash is recomputed from stored text before sealing. Quote bytes, citation page/section and span identity are therefore transitively committed by the release member.

## Separate identities

`state_epoch` is deliberately not folded into `release_id`: it detects in-flight and ABA mutation and binds mutable **derived retrieval state**, including `span_embeddings`. Embedding vectors/model rows can alter semantic ranking but are not source-of-truth corpus metadata; every embedding INSERT/UPDATE/DELETE advances the epoch, the token/audit record carries that epoch, and the cache key commits it. Thus a derived-index rebuild changes the retrieval-state identity without pretending that source evidence or its semantic metadata changed.

`authorization_scope_id` separately commits subject, clearance, roles, assigned corpora, compartments and requested corpus scope. Retrieval/calibration/model configuration is separately bound by the configuration/cache/assurance identities. A release therefore means “same visible corpus semantics”, while `(release_id, state_epoch, authorization_scope_id, configuration_id)` is the execution identity needed for deterministic reuse.

## Deliberately not committed

Current answer execution does not consume the following source fields for eligibility, ranking, authorization, citation serialization or evidence bytes: issuer, jurisdiction, document type, document/version creation timestamps, publication identifier, object key, MIME type, source-signature storage fields, fingerprint/near-duplicate metadata, extraction-review metadata, reviewer identities, approval timestamp/identity, and `is_current`. A future code path that makes any of these answer-relevant must add it to this projection and a destruction control in the same change.

Derived `span_embeddings` are intentionally not hashed into `release_id`; they are bound by `state_epoch` as described above. This avoids an O(number-of-embeddings × vector-width) hash on every answer token while preserving fail-closed cache/audit identity for index mutation.

## Capture protocol

One short database transaction performs: epoch read → authorized visible membership projection → batched semantic projection → relational compartment projection → epoch read. Missing/mismatched semantic rows fail closed. Any mutation of documents, versions, compartments, spans or embeddings advances the epoch; a change during capture is rejected rather than mixed into one token.
