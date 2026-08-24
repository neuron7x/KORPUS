# KORPUS v0.9.7 — Verification Entry Point

Behavioral source digest: `15f1630f4327babeba37802d64b195d43cae256b55042b7f44517a24784a78aa`.

## Current verified local state

- Regression: **2345/2345 PASS**, 64/64 shards, 0 failures/errors, 1 real-PostgreSQL skip.
- Mutation: **349/349 KILLED**.
- Web Node: **146/146 PASS**.
- Browser E2E: **5/5 PASS**.
- Determinism: **4 seeds × 66 tests PASS**.
- Current truth: PASS.
- Production authorization: **false**.

## Verify extracted repository

```bash
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_source_manifest.py
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_current_truth.py --root .
PYTHONPATH=apps/api/src:scripts python3 scripts/check_release_identity.py
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_package_build_identity.py --root .
PYTHONPATH=apps/api/src:scripts python3 scripts/validate_repository.py --context FULL_SSOT_DISTRIBUTION
```

## Evidence

Current portable raw receipts are under `handoff/evidence/current/` and hash-bound by its `MANIFEST.json`.

Production-only evidence is intentionally not fabricated; see `handoff/operations/NEXT_STAGE_EXTERNAL_EVIDENCE_v0.9.7.md`.
