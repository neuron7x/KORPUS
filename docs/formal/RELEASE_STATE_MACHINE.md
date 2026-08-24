# Release promotion state machine v1

States are strictly ordered for normal promotion:

`DRAFT → INTEGRATED → VERIFIED → RELEASE_CANDIDATE → PRODUCTION_AUTHORIZED`.

`WITHDRAWN` is a terminal safety state reachable from any non-withdrawn state.

## Identity invariant

A release identity is the tuple `(release tag, source SHA-256, evidence SHA-256)` and has a domain-separated canonical digest. Promotion changes state, not identity. If source bytes or evidence bytes change, the object is a different release candidate and must be re-evaluated.

## Transition predicates

### DRAFT → INTEGRATED

Requires the source tree to have been integrated into one candidate tree. It does not imply verification.

### INTEGRATED → VERIFIED

Requires configured verification gates for the exact source/release and a verifier identity.

### VERIFIED → RELEASE_CANDIDATE

Adds candidate gates such as mutation, package integrity, migration, reproducibility and other repository-defined evidence.

### RELEASE_CANDIDATE → PRODUCTION_AUTHORIZED

Requires all production gates and, when policy demands it, an independent verifier distinct from the author. This transition must not be inferred from engineering readiness.

## Prohibited transitions

Skipping a stage, moving backwards, or converting a withdrawn release back into an authorized release is refused. A post-release defect produces WITHDRAWN, after which remediation creates a new release identity.

## Executable reference

`korpus.application.release_state_machine` implements the transition function without I/O. `test_release_state_machine.py` covers sequentiality, source mismatch, mutation negative-control requirements, independent verifier separation and withdrawal behavior.
