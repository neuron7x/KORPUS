# KORPUS v0.9.7 — START HERE

Canonical release identity is defined by `apps/api/src/korpus/release.json`.

Primary verification sequence:

```bash
python3 scripts/check_release_identity.py
python3 scripts/verify_source_manifest.py
python3 scripts/verify_current_truth.py
python3 scripts/verify_final_release_authorization.py
```

Canonical artifact for this stage: `KORPUS_v0.9.7_PRODUCTION_ASSURANCE_HARDENED_FULL_SSOT_CANONICAL_2026-08-23.zip`.

`production_authorized=false` until all external production-evidence predicates are satisfied.
