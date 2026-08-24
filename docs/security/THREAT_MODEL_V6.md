# Threat model v6 — evidence-bound controlled corpus

## Assets

1. corpus confidentiality and compartment boundaries;
2. current authoritative version identity;
3. review/approval provenance;
4. evidence spans and citation integrity;
5. tenant/account state;
6. audit chain and anchors;
7. package/release identity;
8. credentials and signing material;
9. model/provider egress boundary;
10. recovery data.

## Adversary capabilities assumed

- arbitrary unauthenticated HTTP input;
- authenticated low-privilege tenant behavior;
- malicious corpus content including prompt-like instructions;
- malformed/oversized uploaded files;
- replayed/stale metadata;
- concurrency designed to race review or state transitions;
- dependency failure and timeout;
- malicious or compromised package contents at distribution boundary;
- accidental operator misconfiguration.

Production signing-key compromise and malicious trusted administrator are treated as separate high-consequence scenarios requiring operational/key-governance controls beyond ordinary application authorization.

## Threat catalogue

### T01 — cross-tenant object discovery
Invariant: a subject can neither retrieve nor infer an object outside its tenant scope. Evidence: tenancy/noninterference negative controls, unique canaries.

### T02 — compartment bypass
Invariant: document visibility requires all applicable compartment/clearance predicates before candidate retrieval. Evidence: policy and retrieval tests plus noninterference matrix.

### T03 — request-body role forgery
Invariant: authorization attributes derive from server-validated identity, never arbitrary request fields.

### T04 — prompt injection from corpus text
Invariant: retrieved content is data/evidence, never system/tool instruction. Evidence: adversarial retrieval corpus.

### T05 — unsupported answer with plausible citation
Invariant: claim support and citation alignment are independently checked; unsupported output abstains/requires review.

### T06 — stale authority / superseded version
Invariant: current answers use the intended effective version and do not silently restamp historical data.

### T07 — approval race
Invariant: review-state transitions are transactional and preserve reviewer separation.

### T08 — audit truncation or anchor drift
Invariant: controlled mutation leaves durable, verifiable audit evidence and reconciliation state.

### T09 — parser/file confusion
Invariant: type/path/content constraints, sandbox limits and scanner policy are evaluated before trusted ingestion.

### T10 — decompression/resource exhaustion
Invariant: bounded bytes/pages/spans/timeouts prevent a single upload from unbounded resource consumption.

### T11 — candidate explosion
Invariant: retrieval candidate counts are bounded before expensive scoring/composition.

### T12 — cache authorization bleed
Invariant: cache identity includes every visibility-relevant scope dimension or is applied after safe authorization.

### T13 — semantic-provider data egress
Invariant: only policy-approved data leaves the process; provider failures cannot broaden data exposure.

### T14 — database identity confusion
Invariant: application/review identities cannot be forged by request data; controlled environments enforce the configured database trust boundary.

### T15 — migration privilege regression
Invariant: schema migrations preserve application-role semantics and required constraints.

### T16 — rollback to incompatible schema
Invariant: rollback policy distinguishes reversible application rollback from database recovery/forward-fix requirements.

### T17 — package path traversal
Invariant: distribution members have canonical relative paths and no ambiguous traversal/backslash/drive forms.

### T18 — duplicate ZIP member ambiguity
Invariant: the archive verifier rejects duplicate canonical member names.

### T19 — executable-mode loss
Invariant: expected executable modes are represented in the manifest and verified from archive metadata.

### T20 — stale source manifest
Invariant: embedded source manifest must match exact packaged source bytes and paths.

### T21 — report-after-snapshot mutation
Invariant: assurance snapshot binds exact report bytes; later edits invalidate verification.

### T22 — Git-history disclosure
Invariant: clean-source distribution contains no `.git`, refs or deleted historical blobs.

### T23 — SBOM overwrite / dependency ambiguity
Invariant: tracked dependency evidence cannot be silently replaced after source identity is sealed.

### T24 — self-attested external red-team
Invariant: gates requiring independence verify signer/attestation properties and reject author self-approval.

### T25 — high maturity score masking critical failure
Invariant: production authorization is conjunctive and independent of weighted readiness.

### T26 — evidence from another source tree
Invariant: cross-source evidence cannot be joined into the current candidate.

### T27 — evidence from another release tag
Invariant: release-bound gates must equal the exact candidate release.

### T28 — malformed evidence interpreted as empty PASS
Invariant: malformed/missing evidence fails closed rather than satisfying vacuous predicates.

### T29 — tool absence represented as success
Invariant: unavailable quality/security scanners are NOT_EXECUTED, never PASS.

### T30 — retry masking
Invariant: failing CI jobs are not automatically retried into an intermittent green verdict.

### T31 — queue poison job stops worker
Invariant: worker loop survives one job failure and preserves/reaps durable job state.

### T32 — orphaned object divergence
Invariant: reconciliation detects missing/orphaned content/quarantine objects.

### T33 — billing/event replay
Invariant: billing state changes are idempotent/ordered according to stored event identity.

### T34 — browser session/CSRF confusion
Invariant: browser-authenticated state-changing requests require the configured CSRF/session relationship.

### T35 — OIDC algorithm/issuer/audience confusion
Invariant: verifier configuration constrains issuer/audience/algorithms and required authentication properties.

### T36 — secret committed to source
Invariant: source/package boundary excludes production credentials and scanners/secret policy run as mandatory external evidence before production.

### T37 — telemetry cardinality/resource attack
Invariant: observability labels and payloads remain bounded and do not leak restricted content.

### T38 — backup exists but restore fails
Invariant: backup presence is insufficient; recovery evidence requires an executed restore/drill with provenance.

### T39 — cold-start behavior hidden by steady-state averages
Invariant: cold and steady-state performance are measured separately.

### T40 — aggregate metrics hide a zero-test or mostly-skipped run
Invariant: execution count, skip count and outcome are separate release predicates.

## Residual-risk rule

No threat is “closed” by this document. Closure status belongs in source-bound evidence. P0/P1 residual risk requires explicit, expiring acceptance by the designated risk owner and does not convert a failed mandatory production gate into PASS unless the production policy itself explicitly defines such an exception.
