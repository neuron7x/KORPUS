# Product specification — current convergence target

Status: current product SSOT · Release: derived from `apps/api/src/korpus/release.json`

## Mission

Turn a curated, governed knowledge corpus into a reliable conversational interface where
users ask natural-language questions and receive only evidence-supported answers they are
authorized to see. Unsupported questions abstain instead of being completed by generation.

## Primary user path

```text
register/authenticate
-> account
-> choose/pay subscription
-> active entitlement
-> open/create conversation
-> ask question
-> authorized evidence retrieval
-> answer with citations OR abstention
-> conversation history and account controls
```

## Current MVP acceptance scope

- responsive consumer web/PWA for phone and desktop;
- authentication and persistent application account;
- plan discovery and subscription state;
- payment-provider integration through provider-independent billing boundaries;
- persistent conversations owned by the account;
- evidence-bound Q&A with explicit abstention;
- citations that expose the exact supporting source passage;
- curated corpus ingestion/review/governance through operator surfaces;
- auditability of access, evidence, answer and subscription decisions;
- policy-gated external model egress;
- Ukrainian-first UX with source-language preservation where required.

## Current personas

| Persona | Job | Non-negotiable guardrail |
|---|---|---|
| Subscriber | Ask and verify a question quickly | Paid access never widens security access |
| Specialist | Resolve a narrow source question | Applicable source/version must be explicit |
| Corpus operator | Ingest and govern sources | Ingestion does not imply approval |
| Reviewer | Approve/reject/supersede sources | Review authority is scoped and auditable |
| Auditor | Reconstruct why output was shown/withheld | Evidence and decision chain is immutable/verifiable |

## Product invariants

1. The LLM is not an authority or source of facts.
2. Factual answer content requires authorized corpus evidence.
3. No evidence or contradictory evidence produces abstention.
4. Conversation history cannot become evidence merely because the system previously said it.
5. Subscription entitlement is server-side and intersects with corpus authorization.
6. Account A cannot enumerate, read or mutate account B conversations.
7. Restricted material cannot egress to an external model unless policy explicitly permits it.
8. Operator capabilities are distinct from consumer capabilities.

## Deferred capability backlog — not MVP acceptance

These are retained product hypotheses, not current acceptance criteria:

- instructor workspace, curriculum and quiz generation;
- administrative document drafting;
- voice/photo input;
- native iOS/Android applications;
- organization analytics beyond what is required for operations/audit;
- autonomous workflow or operational decision execution.

No deferred capability may block consumer SaaS convergence.

## Success gates

Current success is evaluated by executable predicates rather than marketing targets:

- zero cross-tier/cross-account leakage in adversarial tests;
- evidence/citation binding gates pass on the frozen evaluation corpus;
- unsupported questions are explicitly refused;
- billing event replay is idempotent;
- inactive subscription cannot obtain paid entitlement;
- external egress policy negative controls pass;
- mobile/desktop functional and accessibility gates pass;
- exact release/source/package manifests verify.

Performance and quality thresholds belong to signed calibration/release profiles. Values not
measured on the production-equivalent workload are not represented here as achieved facts.
