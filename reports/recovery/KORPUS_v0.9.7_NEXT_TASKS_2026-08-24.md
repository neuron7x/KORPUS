# KORPUS v0.9.7 — НАСТУПНІ ЗАДАЧІ ПІСЛЯ RECOVERY FREEZE

Цей список не є роботою, делегованою користувачу. Це черга наступного verification cycle поверх відновленого canonical repository.

## P0 — authority rebinding

1. Заморозити новий source tree і обчислити єдиний current source/evidence identity відповідно до визначених scope semantics.
2. Регенерувати `SOURCE_MANIFEST.json` після freeze та незалежно перевірити кожен path/hash/mode.
3. Регенерувати `PACKAGE_BUILD.json` і всі current-truth views на тому самому frozen tree.
4. Повторно виконати full mutation catalogue **349/349** на final digest; `survived`, `invalid`, `error`, `timeout` лишаються окремими fail-closed станами.
5. Перегенерувати `MUTATION_FULL_CATALOGUE_CURRENT.json` і production mutation gate лише з fresh source-bound receipts.
6. Повторно виконати exact full backend regression після останньої source mutation; zero carry-forward із іншого digest.
7. Регенерувати `CURRENT_TRUTH_VERIFICATION.json`; будь-який stale evidence binding -> FAIL.

## P0 — runtime/security external gates

8. Виконати exact Python `3.12.13` environment closure.
9. Виконати pinned `ruff`/`mypy` із locked artifact provenance.
10. Виконати real PostgreSQL/RLS adversarial suite: cross-tenant read/write, forged tenancy, pool-context leakage, service-role bypass, transaction rollback/failure paths.
11. Виконати pinned supply-chain scanners (`gitleaks`, `pip-audit`, `trivy` та contract-required scanners) із machine receipts; tool-unavailable не переводити в PASS.
12. Побудувати container SBOM, vulnerability evidence та trusted attestation.
13. Виконати production-like load/soak/recovery campaign із preregistered thresholds.
14. Отримати незалежний TEVV artifact із assessor/source/release/signature binding.
15. Hosted reproducible build + signer separation + trusted release provenance.

## P1 — evidence architecture

16. Зробити evidence DAG машинно перевірюваним: source → environment → static → regression → mutation → security → DB → load → TEVV → signing → promotion.
17. Унеможливити dimension-level false green: будь-який агрегований PASS повинен бути функцією явних локальних predicates, а не константою/default.
18. Додати freshness invariant до всіх generated evidence artifacts: artifact source digest == frozen current source digest.
19. Розділити historical evidence і current-authority evidence фізично/схемно, щоб stale artifacts не могли бути випадково промотовані.
20. Зберегти recovery snapshot immutable; подальша інженерія виконується тільки в новій working copy, щоб recovered SSOT лишався forensic checkpoint.

## EVAL GATE

Recovery checkpoint: **PASS**.  
Production promotion checkpoint: **FAIL / intentionally blocked until P0 evidence chain is fresh and complete**.
