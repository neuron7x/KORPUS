# Phase 01 acceptance: snapshot, semantic identity and visibility

Primary issue: [#98](https://github.com/neuron7x/KORPUS/issues/98).
Original acceptance: [#23](https://github.com/neuron7x/KORPUS/issues/23),
[#26](https://github.com/neuron7x/KORPUS/issues/26),
[#27](https://github.com/neuron7x/KORPUS/issues/27).

This record distinguishes the verified merged baseline, configuration/contextual
evidence follow-ups, and the subsequent intermediate cache/ranking repair. It
grants no production authority.
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

## Follow-up: literal storage, ranking and native-actor boundaries

Parent of this repair is PR138 head `33aaa5aeec97a9874649a6309ac1297e6815d919`,
tree `7873c45ceabe92861eee8d20dc20a426dbcb41d7`. Its successful hosted run is
predecessor evidence. It cannot qualify the changed runtime described here.

The complete independent review of the original
[#23 A–L contract](https://github.com/neuron7x/KORPUS/issues/23#issuecomment-5285256888)
found two actual intermediate failures. A result from state B could be inserted
under a key captured in A before the outer request refused. A nonempty semantic
backfill from B could join lexical candidates from A and reach the real ranking
function before the same outer refusal. Neither experiment observed a mismatched
`ANSWERED` response. Later rejection and a new epoch's different cache key did not
satisfy the separate prohibition on these intermediate actions.

### Repair and preserved boundaries

`corpus_read_context.py` retains the originally captured token together with the
exact reader authority, repository, identity, corpus scope and date. Both
`RequestBoundRetriever` and legacy `SnapshotBoundRetriever` enter this scope and
restore its predecessor in `finally`. Nested explicit requests can carry their
own tokens; an implicit nested cache cannot borrow a different repository's
authority. A replaced reader is refused even if its token fields look identical.

`query_cache_read.py` supplies one read-through path for baseline and all PEC
modes. A standalone cached retriever establishes its scope before computing the
key; a cache within an existing request reuses its original token. The actual
`EvidenceQueryCache.put` boundary validates that scope before inserting anything.
The ordinary scope-free bounded cache data API remains available. The hybrid
retrieval path validates the same active token after semantic backfill and before
scoring, materialization or diversification. These changes do not hold a database
transaction across delegate, semantic-provider or model work.

Existing module/function ceilings remain unchanged. Shared helpers reduce
duplication in both cache adapters and keep all changed modules within those
ceilings. One test snapshot-reader fixture now supplies its real authorization
scope digest instead of a constant; it is still explicitly a protocol double.
The old synchronous approval test now observes the earlier refusal before ranked
results return, then independently verifies that B is visible under a fresh read.
The two new modules are explicitly registered at their measured initial ceilings:
127/31 module lines, 6/3 maximum complexity, 20/15 maximum function lines,
4/5 parameters and 1/2 nesting depth, respectively. Every existing budget row is
unchanged; both the size ratchet and the separate complete-registry test apply.

### Exact new witnesses

| Original clause | New executable observation | Measured scope / remaining boundary |
| --- | --- | --- |
| A / B / D | `test_snapshot_native_actors::test_native_writer_commits_while_answer_reader_is_paused` pauses an actual HTTP reader after capture while a separate writer commits approval, rescission or A→B→A metadata transitions. The final refusal has no claims/citations, names the original release, and matches the persisted five-field audit token. ABA restores the same release but advances the epoch. A stable answer is obtained first. | Three local SQLite cases pass. PostgreSQL execution of the same nodes remains required. |
| C | `test_read_scope_boundaries` covers standalone, request-bound and legacy entries × baseline/PEC default/lexical/semantic. It observes actual cache-map insertions, including any later cleanup, and requires zero after drift. Stable controls require a real miss then hit and exactly one token capture per standalone request, with no recapture of bound tokens. `test_native_approved_b_is_never_inserted_under_captured_cache_a` additionally reads actual newly approved B rows through the native repository. | Protocol and four local SQLite actor cases pass. No B-under-A entry is inserted. PostgreSQL remains unexecuted locally. |
| E | A nonempty semantic hit produces an actual repository backfill. A spy delegates to the real scoring implementation for healthy controls and observes zero calls after drift. Direct request/legacy retrieval and cached entries are covered. The native actor case preserves a fresh, nonempty two-candidate hybrid positive after the refused stale request. | Protocol and local SQLite actor controls pass. They do not simulate a PostgreSQL dialect. |
| F / H | `test_approved_text_only_or_reordering_update_is_denied_and_rolled_back` separately changes text with its old hash preserved, or changes only an ordinal to a nonconflicting value that genuinely reorders at least two rows. Each exact operation succeeds on a draft, is restored before approval, then is denied after sealing. Full persisted version/span rows remain equal after rollback. | Two native SQLite cases pass using the labelled database-owner fixture. The existing combined text/hash, insert/delete and seal immutability controls remain. |
| I | `test_same_raw_source_and_ids_with_new_derived_layout_change_seal_and_release` applies real `make_spans` with two chunk windows to the same raw bytes. It writes two legal draft layouts with identical document/version/span IDs and source hash, reads both seals through `seal_evidence_digest`, and requires different digests. Repeated-input and row-order normalization positives remain equal. One actual semantic member is then compared with only that measured seal replaced. | Native SQLite derivation/seal control passes. IDs or a new raw hash cannot explain the observed release difference. |
| J | `test_historical_http_answer_binds_exact_old_citations_release_and_audit_token` compares historical and current answered HTTP responses with explicitly captured tokens, exact eligible span/version IDs, source/span/quote hashes, quote offsets and their persisted audit tokens. | Local SQLite whole-path positive passes; the current-version positive is retained. PostgreSQL runs the same node. |
| L | Native missing-epoch and malformed nonhex stored-seal states reach real capture and HTTP refusal with no retrieval, claims, citations or fabricated token. A NULL seal is read-refused in the metadata-created SQLite fixture. Migrated PostgreSQL's `ck_approved_version_evidence_digest` instead rejects approved+NULL at the write boundary; that branch asserts rollback and does not pretend a corrupt row was read. | Local SQLite cases pass. PostgreSQL CHECK denial, nonhex-seal read refusal and missing-epoch read refusal require native execution. No constraint or trigger is disabled to construct a fixture. |

All native actors use finite `Barrier`/`Event` waits, propagate worker failures and
close their actor connections. Four separate harness controls preserve the original
writer exception with zero checked-out actor connections, exclude an actual unrelated
background connection held across the handoff, still refuse an actual reader-held
connection, and account for an actual invalidated connection returned through
`checkin(None)`. An instance-bound `ContextVar` is set/reset inside both workers;
the real HTTP tests must still observe reader SQL, principals and physical identities
through TestClient/AnyIO. Pool records identify checkouts/checkins while retained
DB-API references preserve physical-identity observations. Unscoped background
checkouts are counted separately. The writer keeps a distinct physical connection reserved
until the reader finishes, with no transaction open after its commit. Pool
observations require zero open reader connections at the handoff. JUnit properties
record the actual dialect and connection identities. On PostgreSQL they additionally
record real backend PIDs, `current_user`, `session_user` and restricted-role checks.
Approval uses the configured review-role connection and existing transition/sealing
implementation; metadata writes use the application role. Local properties state
`postgresql_observed:false` rather than assigning PostgreSQL credit to SQLite.

The first 32 new protocol controls, before the runtime repair, produced 21 failures
and 11 passes with no collection errors/skips. Their observers demonstrated the
cache/ranking defects, legacy recapture and authority borrowing. The repaired
combined targeted run has 108 passes and zero skips, including 38 new protocol
controls, eight native SQLite actor cases, four separate actor-harness controls,
seven literal F/H/I/J/L controls, and the existing request/cache/temporal/
contextual/audit positives. It also includes six catalogue/budget checks and two
existing PEC cache controls. Exact final-tree receipts carry the final commands
and any subsequent validation; these counts are local scope.

The first frozen 105-case replay at tree `5dffcad98c33ea379512882c830aebf0e72b1c58`
produced 104 passes and one failure in writer-exception cleanup. Its engine-wide
observer classified every non-writer checkout as a reader. A separate event-stack
trace observed unrelated startup audit-reconciler/readiness checkouts on `asyncio_0`;
it established the attribution confound, but did not capture the exact remaining
handle from the failing run. Deterministic background-held and invalidated-connection
controls then both failed with the old observer, while the actor-held negative
passed. All three pass with instance-bound actor attribution and pool-record
accounting. The original failure and both causal before/after runs are retained
in the local handoff receipts; no actor-connection assertion was removed.

M852–M860 preserve causal faults for pre-storage and pre-ranking validation,
unwanted token recapture, missing legacy scope, borrowed repository authority,
failed nested restoration, omitted derived-evidence identity, malformed stored
seal admission and a missing epoch treated as zero. All nine isolated direct
pytest diagnostics produce intended test failures, with zero errors or skips.
Eight fail assertions or expected-exception assertions; M857 instead exposes the
leaked inner scope as `CorpusConsistencyError` at the post-nested outer-token
check. It is a semantic restoration failure, not a collection/import error.
Their selected target/test bytes are compared with the final frozen source.
Those diagnostics are separate from the unsupported bounded campaign; a fresh
native complete campaign is still required.

The follow-up remains **HOLD** until independently reviewed and qualified by its
own exact-source hosted run. The original #23 requirement for a submitted
nonauthor GitHub review is an additional unfulfilled administrative predicate;
this implementation, local tests and agent review do not create that review event.

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
