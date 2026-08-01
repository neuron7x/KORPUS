# KORPUS determinism and reproducibility standard

KORPUS claims determinism only for a named function, frozen inputs and a recorded environment.
Semantic determinism, test stability and bit-reproducible packaging are separate predicates.
Latency, timestamps, random identifiers and host paths are not silently removed from an artifact;
the producer must instead publish a documented canonical semantic projection when they are expected
to vary. A fixed seed makes a randomized experiment replayable, not exhaustive.

The local gate repeats the complete frozen evaluation report and source system manifest with
`PYTHONHASHSEED=0`, `TZ=UTC` and `LC_ALL=C.UTF-8`, then requires exact SHA-256 equality. Missing
runs, producer failures, changed bytes, malformed evidence and `production_authorized=true` fail
closed. CI retains the report. The existing mutation, adversarial, migration, PostgreSQL/RLS,
backup/restore, browser and scale gates remain separate proof surfaces.

Supply-chain limitations are explicit: SBOM generation exists, but image/base inputs are not all
digest-pinned, Python locks are not fully artifact-hashed, signing needs a protected GitLab OIDC or
key boundary, and independent container rebuild equality is not yet demonstrated. Therefore this
gate does not close `SUP-001`, `SUP-002`, `SUP-003` or `OPS-001`, and it is not SLSA certification.
