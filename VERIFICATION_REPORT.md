# KORPUS v0.9.7 — Verification Entry Point

## Як перевірити поточний стан

```
make release-verify
```

Вона й тільки вона дає ці числа про ОДНЕ дерево: спиняється на першій відмові, бо далі
числа були б про інше дерево, і звіряє дайджест джерела ДО і ПІСЛЯ прогону.

- Regression, Mutation, Web, Determinism — у її звіті
- Current truth: `make current-truth-verify` (значення рухоме — тут воно НЕ вкарбоване;
  02.09.2026 цей рядок казав `PASS`, тоді як верифікатор давав `FAIL` із шістьма
  відмовами `.source_bound`)
- Production authorization: **false**
> **ВИПРАВЛЕНО 02.09.2026.** Числа в цьому блоці були заморожені 23.08.2026 і подавались
> як поточний стан. Виміряно: тестів **3814**, не 2345; мутантів **574**, не 349; шардів
> регресії **24**, не 64; дайджест джерела за одну годину прийняв три різні значення.
> Тому числа, що рухаються, тут більше не вкарбовані — названі ЛИШЕ джерела, бо друге
> оголошення рухомого числа розходиться мовчки, і саме так воно й розійшлось.


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
