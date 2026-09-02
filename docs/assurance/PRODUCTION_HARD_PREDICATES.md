# KORPUS production hard predicates

The production boundary is conjunctive. Engineering score cannot compensate for a missing runtime or independent trust proof.

For each of the fourteen predicates KORPUS records two states:

- `software_ready`: the repository contains the executable validator, policy, trust boundary and negative-control tests needed to execute or admit that proof;
- `externally_satisfied`: the required runtime/independent evidence has actually been executed, source-bound, release-bound and admitted by the production gate.

`production_satisfied = software_ready AND externally_satisfied`.

Canonical machine profile: `config/assurance/production-hard-predicates-v1.json`.
Canonical verifier: `scripts/verify_production_hard_predicates.py`.
Canonical current report: `reports/PRODUCTION_HARD_PREDICATES.json`.

The fourteen non-compensable predicates are external independent red-team; current vulnerability/container/security scanning; real PostgreSQL/RLS execution; real-domain TEVV corpus; independent TEVV; production-like TEVV environment; production-like load; trusted load attestation; trusted recovery attestation; trusted hosted builder provenance; trusted release signing; the exact Python 3.12.13 locked environment; hosted human production authority for the
PEC cohort; and exact Cloud Run revision canary admission.

> ВИПРАВЛЕНО 2026-09-02. Документ казав «twelve» і називав дванадцять, тоді як
> `config/assurance/production-hard-predicates-v1.json` і `_REQUIREMENTS` у коді містять
> **чотирнадцять**: не названі були `pec_human_production_authority` і
> `pec_canary_revision_admission`. Обидва стоять у профілі й у `required_gates`, тобто
> зовнішній оцінювач, який читав цей перелік, недорахував би обсяг на дві позиції.

A local artifact may reach 100% `software_ready` while remaining 0% or partially complete on external proof. The verifier must not reinterpret that condition as production authorization.

## Final-release trust phase

`trusted_hosted_builder` and `trusted_release_signing` are evaluated only after the immutable artifact exists. They are intentionally not inferred from a workflow file or from the supply-chain scanner signature. `scripts/verify_final_release_authorization.py` verifies the completed artifact against the source manifest and an already-PASS production-assurance report, then requires: an in-toto/SLSA-format builder statement bound to the artifact digest; an Ed25519 attestation over that builder statement from a pre-admitted hosted-builder signer; a pre-admitted builder identity; a detached Ed25519 release signature over the release manifest; and signer separation between builder and release authority. This removes the circular pre-package claim that release signing had already happened.

## Independent TEVV trust phase

Production TEVV evidence must declare `evidence_class=EXTERNAL_INDEPENDENT`, a structured assessor identity with `independent_of_system_owner=true`, a production-like/production environment class, a case-level observation/null ledger, and a detached Ed25519 attestation from a pre-admitted TEVV assessor key. The environment label alone is not evidence of independent validation.
