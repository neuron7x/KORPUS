# Phase 01 acceptance: snapshot, semantic identity and visibility

Primary issue: [#98](https://github.com/neuron7x/KORPUS/issues/98).
Original acceptance: [#23](https://github.com/neuron7x/KORPUS/issues/23),
[#26](https://github.com/neuron7x/KORPUS/issues/26),
[#27](https://github.com/neuron7x/KORPUS/issues/27).

This record distinguishes the verified merged baseline from the follow-up that
strengthens configuration isolation and contextual metadata evidence. It grants
no production authority.
The follow-up requires its own exact-candidate hosted checks and independent
review; the baseline's successful reports are not new-candidate results.

## Verified baseline and original producer bytes

| Subject | Exact identity |
| --- | --- |
| PR #137 head | `ed8c75877524fa0384aa01e18067339788aa93a0` |
| Actual CI merge checkout | `fc6d1b0d54bad87b6e07895ebe6bb0a50d004d28` |
| Merged main | `921ac8b9f2c71aa366c7d2b8c73206b696e9903c` |
| Identical Git tree of all three | `00562c890a73492b88a1234ed526fad7825acca3` |
| CI run / attempt | [44874776733 / 1](https://github.com/neuron7x/KORPUS/actions/runs/44874776733) |
| Evidence-path digest | `e9c13e1a2ee66e531fd23c16ad58e6e6eb4094caf23e6a36f7fbaf7b10b5a822` |

The literal execution subject in the receipts is the CI merge checkout. Git
parent/tree reads and byte comparisons establish the relationship above; the
receipts have not been rewritten to name the PR head or later main.

Downloaded original archives were independently hashed against GitHub metadata:

| Artifact | ID | ZIP SHA-256 |
| --- | --- | --- |
| PostgreSQL diagnostics | `14695996419` | `9147b1f162700aac2569865cb02086f8fef7ae2fc310ba319d1e6a0a5408ff09` |
| Source assurance | `14695228077` | `48f23156a5ae2d2f6adfc282204cf4e3706a9f9d38c8ed4e1787a50f472a9038` |

The PostgreSQL JUnit contains 7,472 cases: 7,465 passed, seven explicitly skipped,
zero failures and zero errors. All 1,939 file hashes in its source receipt match
the reviewed source bytes. The mutation report contains 701 valid mutants, all
killed, with no survivor, invalid target or execution error. Its evidence-path
digest was independently recomputed from source. The frozen evaluation has 30/30
passing synthetic safeguard cases; it is not a real-corpus quality measurement.
All 12 protected checks, Compose pilot and canonical-package passed for this
baseline. Deployment was skipped and `production_authorized` remains false.

## #23: one state across the complete answer path

| Acceptance obligation | Current mechanism and executable witness |
| --- | --- |
| One state for answer, retrieval and cache | `CorpusReadToken`, request-bound retrieval and `cache_release_token`; `test_answer_request_snapshot_gate` checks token reuse, scope spoofing, ABA/cache poisoning and context cleanup. Runtime AST checks reject legacy independent release restamping. |
| Approval and rescission races | `test_temporal_corpus_snapshot` places deterministic call-boundary mutations before/after retrieval. `test_answer_snapshot_race_api` mutates during composition and before audit; a mismatched answer refuses. |
| ABA and mixed lexical/semantic state | Monotonic `state_epoch` rejects transient changes even when release membership returns to the same digest. Dedicated ABA, lexical-to-semantic mutation and embedding-backfill cases pass. |
| Exact eligible evidence | Approval seals the ordered span set. Empty/duplicate spans and inconsistent hashes fail; approved evidence and its seal are immutable. |
| Date and authorization scope | The token binds `as_of`, requested corpora and `authorization_scope_id`. History/scope relabelling tests refuse; original visibility filtering remains active. |
| No weaker consistency fallback | Missing/competing snapshot readers, initial capture failure and post-retrieval changes abstain. Context cleanup and nested-request restoration are exercised. |
| Actual audit identity | `test_answer_snapshot_audit` and the API race controls compare the emitted/audited token and release. |
| Bounded work | Capture and validation use short database transactions; model/network work does not retain those transaction scopes. Global epoch invalidation is conservative and may refuse after unrelated writes; no production latency guarantee is inferred. |

Hosted PostgreSQL individually passed the request-token suite (9), temporal suite
(8), composition-race suite (6), authority suite (6), audit suite (1) and integrity
suite (5). The snapshot-contract suite passed 85 cases and skipped its one
SQLite-only trigger-definition case; that case passed in the local SQLite run.

## #26: explicit semantic dependency classification

The graph is persisted document/version/span state -> `release_projection` and
`semantic_release_members` -> eligibility/ranking -> `Citation` and `Answer`.
The versioned projection uses `korpus-temporal-semantic-release-v3` and explicit
length framing rather than hashing arbitrary database rows.

| Classification | Fields or inputs | Binding |
| --- | --- | --- |
| Direct | `document_id`, `version_id`, `source_hash`, `review_state`, `evidence_digest` | The canonical 22-field `SemanticReleaseMember` and `release_identity_digest`. |
| Direct | `canonical_title`, `corpus_id`, `issuer`, `jurisdiction`, `document_type` | Same projection; the three contextual-ranking fields also have persisted approved-document mutation controls. |
| Direct | `access_tier`, `classification`, `document_compartments`, `visibility_compartments` | Same projection; JSON and relational compartment representations are both included. |
| Direct | `revision`, `source_uri`, `publication_date`, `effective_from`, `effective_until`, `rescinded_at`, `authority`, `supersedes_version_id` | Same projection, with canonical optional values. |
| Transitive | Span ID, ordinal, page, section, exact text/hash and complete approved span membership | `evidence_digest`; inconsistent stored text/hash is rejected before hashing. Original document bytes are represented by `source_hash`. |
| Separate request identity | Subject, clearance, roles, granted/requested corpora and compartments; historical query date | `authorization_scope_id` plus the token's `corpus_ids` and `as_of`. |
| Separate index/configuration state | Embedding updates, pinned calibration/ranking profile and answer-obligation algorithm | Embedding writes invalidate `state_epoch`; one loaded calibration profile and cache `configuration_id` bind ranking. The explicit `:obligations-v1` suffix is documented in `docs/protocols/QUESTION_OBLIGATIONS.md`. |
| Irrelevant to corpus identity | Generated answer ID, request/response timestamps and cache hit/miss counters | These describe a particular execution, not the eligible corpus/provenance projection. |

Thus `corpus_release` identifies the corpus evidence and provenance state. It does
not purport to be the sole identity for every request, execution configuration or
deployed source artifact. The separate bindings above are part of the contract.
No additional uncovered corpus-metadata field was reproduced in this review.

All 22 field-sensitivity controls pass, together with order/join multiplicity,
set framing, absent-versus-empty distinctions and actual issuer/jurisdiction/type
database mutations. Independent review found two incomplete acceptance witnesses:
the former cache test named configuration without varying it, and the original
persisted metadata test used a database-owner connection and checked only release
inequality. It did not execute the contextual candidate/cache/audit path requested
in [the #26 acceptance comment](https://github.com/neuron7x/KORPUS/issues/26#issuecomment-6496166482).
The two follow-ups below address those distinct evidence gaps.

## #27: candidate admission precedes the result budget

The candidate query checks same-document supersession, effective/rescission
currency and compartments before `LIMIT`. The subject-title path has matching
controls. Exact hosted outcomes are three SQLite lexical cases, four PostgreSQL
lexical/vector cases, three SQLite subject-title cases and three PostgreSQL
subject-title cases, all passing. The PostgreSQL vector case rejects stale/future
rows consuming top-K capacity. Positive controls preserve admitted evidence.

The seven PostgreSQL visibility cases previously missing from the acceptance
record now individually pass. Query-plan/cost controls preserve noncorrelated
supersession evaluation and the existing bounded search budget. They do not
establish a measured production SLA.

Independently inspected mutation rows M06, M195, M196, M579, M580 and M581 each
have one literal target, return code 1 and an assertion failure on their intended
release/currency/cost/visibility property. No import or syntax failure is used
as evidence that those semantic mutants were killed.

## Follow-up: configuration isolation has an actual falsifier

An isolated fault replaced only `CachedRetriever._key`'s `configuration_id` with
a constant. Before the new controls, all four existing cache tests still passed
(exit 0): the old test name overstated its exercised scope.

`test_shared_cache_recomputes_only_for_a_different_configuration` now shares a
cache among retrievers with the same corpus, user, date and query. A changed
configuration must invoke retrieval again; returning to the original configuration
must hit its cache. Four modes cover the baseline adapter, PEC default, PEC lexical
and PEC semantic paths. This simultaneously rejects configuration aliasing and
disabling the cache to obtain a green negative control.

With the constant-configuration fault, all four new cases fail at the expected
`delegate.calls == 2` assertion (exit 1). With unchanged production code they
pass. M833 preserves this causal mutation in the ordinary hosted campaign.
No runtime behavior, threshold, dependency, visibility policy or budget is changed.

## Follow-up: contextual metadata has an end-to-end witness

`test_contextual_release_binding.py` runs six cases: each of `issuer`,
`jurisdiction` and `document_type` changed through the application connection or
the separately labelled database-owner connection. On PostgreSQL the application
case asserts `current_user == session_user ==` the configured application login,
no superuser/BYPASSRLS status and no membership in the table-owner role. The
database-owner case separately verifies its configured owner login. A domain-admin
identity is bound before its SQL update; the target is visible and exactly one
approved document row changes. Public retrieval and answers use a separate reader.

Both the real HTTP answer-service configuration and the direct candidate probe
enable contextual retrieval. A neutral marker absent from the evidence changes
the candidate set from empty to the exact persisted span set. The complete stored
version and span rows, including the sealed evidence digest, remain identical.
Contextual projection bytes change while evidence text and its hash do not.

Two identical-before/after HTTP questions each run twice on each side of the
metadata update: the ordinary body question and the metadata-only marker. Each
has a miss then a hit before mutation and a new miss then a hit afterward. The
marker path's persisted retrieved count changes from zero to one, while its
answer honestly abstains because metadata alone supplies no textual support.
The body question remains answered. Final cache counts are four misses/four hits.
The release changes and the epoch increases. All eight independently read
persisted `answer.completed` events match their responses and all five expected
snapshot fields. Body citation document/version/span IDs, revision and quote hash
match the original persisted evidence; metadata is not inserted into quotations.
No mock database or stub audit supplies these observations.

Local SQLite execution: six cases pass, exit 0. Independent API-source-overlay
probes replace each of the three digest frames with a constant, one at a time.
All three exit 1 at `after.release_id != before.release_id`, with exactly one
replacement target; no collection/import failure is counted. M834, M835 and M836
preserve these omitted-field faults in the hosted mutation catalogue, now 705
entries including M833. The canonical local bounded mutation runner refuses with
`unsupported_child_ownership:cleanup_unproven`; its local status remains
NOT_EXECUTED. The direct pytest probes are explicitly narrower evidence.

These observations do not relabel the earlier 20c6b6c candidate's successful native
run as execution of the six new cases. Their exact new-candidate PostgreSQL nodes,
all 705 native mutation outcomes and the complete required checks must pass before
acceptance. The existing v3 runtime mechanism required no change.

## Skips, local boundary and acceptance handoff

The seven baseline PostgreSQL skips are load-probe data, local branch registry,
detached canonical-branch declaration, the SQLite-only epoch trigger, missing
other-producer assurance artifacts, undeclared local forge remotes, and the
separate evaluation report. None is a skipped PostgreSQL candidate-visibility
case. They retain SKIP status. The SQLite trigger case has its separate positive
execution; other producer-specific results retain their own producer scope.

Local baseline runs produced 46 passes and a supplemental 93 passes/four
PostgreSQL-only skips. Every locally skipped PostgreSQL node passes in the
downloaded native PostgreSQL JUnit. The local Python is 3.12.14 with the hash-locked
dependency set; the native runner uses 3.12.13. Local Git ownership does not meet
the unchanged trusted-system-tool predicate. Four Git-dependent parity checks
therefore refuse in the worktree; they are not represented as local PASS.
Supported metadata-free archive validation can check derived byte identities,
but it cannot establish trusted local Git or substitute for native CI.

The phase owner must read the follow-up's actual head, exact hosted run/attempt,
per-node PostgreSQL outcomes, complete mutation result, package result and
independent verdict before closing the phase. Existing standing owner merge
authorization applies after those gates; this record does not create deployment
authority or close external corpus/recovery/signing requirements.
