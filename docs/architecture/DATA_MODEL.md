# Canonical data model

## Principal entities

`Document` identifies a logical work. `DocumentVersion` is immutable and contains a
hash, source, dates, rights basis, authority, validity and access tier. `Artifact`
points to the original or derived object. `Chunk` identifies an immutable evidence
span. `Embedding` is replaceable and versioned independently.

`Corpus` groups approved versions under a policy. `Review` records a reviewer,
decision, rationale and signed timestamps. `Supersession` creates a directed graph
between versions.

`Query`, `RetrievalRun`, `EvidenceSet`, `Answer`, `Claim`, and `Citation` form a
traceable answer chain. `PromptVersion`, `ModelRun`, and `PolicyDecision` support
reproducibility without storing unnecessary personal data.

`Course`, `Competency`, `Lesson`, `Assessment`, `QuestionVersion`, `Attempt`, and
`ReviewerDecision` support learning. Passing an assessment is not certification.

An `OperationalRole` names required `OperationalTask` records. Each task states its
conditions and observable standard and requires a conjunction of competencies. Learning
objectives may reference those competency identities. Alignment means that every required
competency has a course objective; it never means that a learner is qualified or certified.

`Template`, `TemplateVersion`, `Draft`, and `ValidationResult` support documents.

## Validity boundaries

Three date fields decide whether a version governs an answer asked on a given day,
and each closes on a different side. Stating this here is not documentation for its
own sake: on 2026-08-03 a mutation flipping the `effective_until` comparison survived
the entire suite, because nothing in the tree said which side the boundary belonged to.

- `effective_from` — **inclusive**. A document takes effect on the day it names.
- `effective_until` — **inclusive**. Ukrainian normative practice reads «чинний до
  31 грудня» as valid through the 31st, so a version whose `effective_until` is today
  still governs today's answer and stops governing tomorrow.
- `rescinded_at` — **exclusive**, and it is a timestamp rather than a date. Rescission
  is an act, not a term: from the day it happens, the version no longer governs.

`is_valid_on` implements exactly this and `test_validity_boundaries.py` fails if any
of the three shifts by one day in either direction.

## Required invariants

- a chunk belongs to exactly one immutable document version;
- approved versions cannot be mutated, only superseded or revoked;
- an answer citation targets a chunk, never a mutable filename;
- a restricted chunk cannot appear in a lower-tier evidence set;
- deletion revokes retrieval immediately while preserving minimal audit proof;
- raw user identifiers are not sent to a model provider.


## Customers, and the wall between them and the corpus

`Account` is who somebody is *here* — created on first authenticated login, keyed on the
identity provider's subject, carrying a status and nothing else. It holds no roles, no
clearance, no corpora, no compartments. That absence is the design: what may be read is
decided by the entitlement profile and the policy engine, and an account with an
authorization field would be a second place that decision could be made.

`Plan`, `Subscription` and `BillingEvent` are commerce. A subscription pays for corpora and
can only ever be *intersected* with what the policy engine already permits — never unioned.
A plan naming `operational` gives `operational` to nobody who was not already cleared for
it, and there is no field through which it could.

`Conversation` and `Message` are a reader's own history. A message carries a role, and an
assistant message is a sentence the system emitted: it is context for a person, never a
source for an answer. Nothing returns history to a retriever, and the verdict is stored
beside the text so a refusal read back stays a refusal.

### Required invariants

- an account is created at most once per identity-provider subject, under concurrency;
- a billing event applies at most once, by database constraint rather than by a read;
- an event either moved the subscription and was recorded, or did neither;
- `CANCELED` and `EXPIRED` are terminal — a renewal is a new subscription;
- entitlement narrows and never widens what the policy engine permitted;
- every conversation read is scoped by owner inside the query, not filtered after it;
- a stored assistant turn never re-enters retrieval.

## Physical tables

Every table this system creates, named so that one added and never described here fails
`test_data_model_documents_every_table.py`. A table nobody wrote down is a table nobody
reviews, and the account layer arrived as six of them at once.

| table | what it holds |
|---|---|
| `documents` | the logical work |
| `document_versions` | an immutable revision with its validity window and review state |
| `document_compartments` | need-to-know labels, one row per compartment |
| `evidence_spans` | the sentence a citation points at |
| `span_embeddings` | replaceable vectors, versioned by model id |
| `audit_events` | the hash chain; append-only, one key id per event |
| `audit_heads` | the single head row the chain advances |
| `audit_anchor_outbox` | anchor deliveries still owed to the external witness |
| `ingestion_jobs` | durable work for the parser, leased by a worker |
| `accounts` | who somebody is here; status only |
| `plans` | what is sold, and which corpora it pays for |
| `subscriptions` | one account's commercial state with a provider |
| `billing_events` | one provider notification, recorded by hash before it is believed |
| `conversations` | a reader's own thread |
| `messages` | one turn, with the role that says who said it |

## Evidence-bound learning graph (ACT-LRN-002)

Learning is a projection over canonical corpus evidence, not another corpus. A course version
stores structure and exact references to `document_versions` and `evidence_spans`; it never
copies authoritative source text. Publication is a lifecycle record separate from immutable
course-version content. Every serving read revalidates source approval/effectivity, so passive
expiry fails closed even when no source row was updated at the expiry boundary.

Required learning invariants:

- each published lesson block has at least one source binding;
- every binding names one exact document version and one or more evidence spans from that version;
- source versions must be approved, effective on the serving date, and not rescinded;
- prerequisite references are internal to the course version and the graph is acyclic;
- published, invalidated, and retired course-version history cannot be rewritten or deleted;
- a retired publication cannot be resurrected; reviewer provenance is immutable after draft;
- source deapproval/rescission/effectivity changes invalidate dependent published versions;
- time-only source expiry is caught by the fail-closed serving lane and persists invalidation.
- role alignment is conjunctive: one covered competency cannot compensate for a missing one;
- unknown role, task, competency, or objective edges fail closed rather than widening scope;

| table | what it holds |
|---|---|
| `learning_courses` | stable course identity and specialty binding |
| `learning_course_versions` | immutable structural revision of one course |
| `learning_modules` | ordered modules inside one course version |
| `learning_lessons` | ordered lessons inside a module |
| `learning_objectives` | explicit learning objectives bound to a lesson |
| `learning_source_bindings` | exact document/version identities used by a lesson |
| `learning_source_binding_spans` | exact evidence spans proving a source binding |
| `learning_lesson_blocks` | ordered typed content blocks without copied source truth |
| `learning_block_sources` | block-to-source-binding edges |
| `learning_prerequisites` | directed lesson prerequisite edges |
| `learning_publications` | draft/published/invalidated/retired lifecycle and reviewer provenance |
| `learning_mastery` | per-learner objective mastery projection bound to the source-binding set that justified the latest state |
