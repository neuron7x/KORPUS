# Integration Workpackages

## WP-00 — Repository and protocol baseline

**Goal:** establish exact KORPUS/OpenClaw subjects before implementation.

Outputs:
- exact KORPUS SHA/source digest;
- current KORPUS MCP tool inventory;
- OpenClaw version/Gateway/MCP capability snapshot;
- integration config schema draft;
- scope declaration.

Exit:
- no unknown baseline state;
- PR #44 relationship explicitly out-of-scope/read-only.

## WP-01 — OpenClaw MCP consumer configuration

**Goal:** connect OpenClaw runtime to KORPUS MCP read tools.

Outputs:
- runtime MCP server definition;
- secret-ref/token wiring;
- URL/timeout configuration;
- allowlist limited to `korpus_grounds`, `korpus_ask`, `korpus_quote`, `korpus_verify`.

Tests:
- discovery PASS;
- invalid token FAIL;
- unknown tool FAIL;
- no write tools visible.

Dependency: WP-00.

## WP-02 — Identity binding

**Goal:** map a channel/session actor to a KORPUS subject without trusting channel metadata as authority.

Outputs:
- binding schema;
- enrollment/revocation mechanism;
- audit representation;
- re-auth policy for sensitive actions.

Tests:
- sender spoof/mismatch FAIL;
- cross-account reuse FAIL;
- revoked binding FAIL.

Dependency: WP-01.

## WP-03 — Evidence-response loop

**Goal:** prove one full factual workflow.

Sequence:

```text
message -> grounds -> ask -> compose -> verify -> response
```

Outputs:
- correlation id across OpenClaw and KORPUS;
- explicit no-grounds behavior;
- citation/hash preservation;
- unsupported-draft refusal.

Tests:
- KORPUS down -> unavailable, no fabrication;
- unsupported sentence -> verification FAIL;
- stale/rescinded evidence remains inadmissible.

Dependency: WP-02.

## WP-04 — Channel delivery policy

**Goal:** constrain where governed results may be delivered.

Outputs:
- direct/group/public channel classes;
- material ceilings;
- originating-route binding;
- route/account/thread verification.

Tests:
- route substitution FAIL;
- restricted-to-group delivery FAIL where prohibited.

Dependency: WP-03.

## WP-05 — OpenClaw status/control read adapter

**Goal:** ingest OpenClaw operational status without making it KORPUS authority.

Capabilities:
- Gateway status;
- channel status;
- session status;
- node status.

Outputs:
- local capability registry entries;
- output schemas;
- provider/version/schema digests;
- canonical audit envelope.

Tests:
- provider schema drift -> quarantine;
- malicious metadata -> no authority change.

Dependency: WP-00.

## WP-06 — Effect ledger substrate

**Goal:** establish reusable side-effect correctness before any OpenClaw write.

Outputs:
- effect record/state model;
- canonical input digest;
- idempotency binding;
- `OUTCOME_UNKNOWN` state;
- reconciliation interface.

Tests:
- duplicate logical effect -> one dispatch;
- timeout after commit -> no blind retry;
- illegal state transition FAIL.

Dependency: none on OpenClaw write; can be implemented/tested with fake provider.

## WP-07 — First bounded OpenClaw write

**Goal:** send a reply only to the exact originating authorized route.

Outputs:
- `openclaw.channel.reply.v1` capability;
- bound route resource;
- provider request/receipt digest;
- audit/effect record.

Tests:
- arbitrary destination FAIL;
- replay produces no duplicate logical delivery where provider/idempotency semantics permit;
- ambiguous outcome reconciled.

Dependencies: WP-04 + WP-06.

## WP-08 — Node/device read pilot

**Goal:** observe paired node status/capabilities without exporting protected data.

Outputs:
- node identity observation;
- capability list normalization;
- revocation behavior;
- no-data egress policy.

Tests:
- stale/unpaired node FAIL;
- node metadata cannot grant KORPUS role.

Dependency: WP-05.

## WP-09 — Bounded node action pilot

**Goal:** prove one low-risk typed device action.

Selection criteria:
- narrow resource;
- observable post-condition;
- no secret/corpus dump;
- reversible or harmless effect;
- explicit Owner/user consent if needed.

Dependencies: WP-06 + WP-08.

## WP-10 — Automation

**Goal:** allow scheduled/event-triggered execution of already approved capabilities.

Outputs:
- automation owner/subject binding;
- capability allowlist;
- schedule/trigger definition;
- expiration/disable semantics;
- bounded notification route.

Invariant:

```text
AutomationCapabilitySet(t+1) ⊆ OwnerApprovedCapabilitySet
```

The automation cannot self-expand.

Dependencies: completed capability-specific workpackages.

## WP-11 — Observability and incident controls

Outputs:
- structured counters/events;
- auth deny rate;
- drift quarantine events;
- egress denies;
- effect unknown/reconciliation metrics;
- integration kill switch;
- credential revocation runbook.

Dependency: cross-cutting; mandatory before production pilot.

## WP-12 — Clean-room verification

A verifier in a fresh/isolated context must reproduce the declared exact candidate and run the negative controls applicable to its scope.

Must distinguish:

```text
producer test result
!=
structurally separated verification result
```

Dependency: all current-scope implementation workpackages.

## WP-13 — Release handoff

Outputs:
- exact integration candidate SHA;
- KORPUS source digest;
- OpenClaw compatibility subject;
- acceptance matrix;
- known non-blocking debt;
- rollback command/procedure;
- Owner decision packet where required.

## Dependency graph

```text
WP-00
  ├─ WP-01 -> WP-02 -> WP-03 -> WP-04 -> WP-07
  └─ WP-05 -> WP-08 -> WP-09

WP-06 ---------------------------> WP-07 / WP-09 / later writes

All current scope -> WP-11 -> WP-12 -> WP-13
```

## Tactical priority

1. WP-00
2. WP-01
3. WP-02
4. WP-03
5. WP-04
6. stop and verify read-only value before adding writes
7. WP-06
8. WP-07
9. nodes/automation only if a concrete workflow justifies them

This ordering maximizes useful integration while minimizing new authority/effect surface.
