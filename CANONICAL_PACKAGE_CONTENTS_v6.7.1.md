# KORPUS v6.7.1 Canonical Assurance-Hardened Package

> ## ⛔ ІСТОРИЧНИЙ ДОКУМЕНТ. Не описує це дерево. Позначено 02.09.2026.
>
> Чинна тотожність релізу — **`0.9.7`** (`apps/api/src/korpus/release.json`), а не `v6.7.1`.
> Це єдиний документ кореня, якого `scripts/check_release_identity.py` не читає взагалі,
> тож розбіжність могла жити скільки завгодно.
>
> Числа тут — з іншої лінії й невідтворювані: «1318 total tests» при 3814, «259/259 valid
> mutants» при 574, покриття 0.9171/0.7902 при 0.9593/0.9236.
>
> Кожне посилання на доказ у цьому файлі МЕРТВЕ: немає ні
> `KORPUS_SYSTEM_v6.7.1.bundle`, ні `reports/ASSURANCE_REVERSE_CYCLES_2026-08-10.*`, ні
> теки `reports/assurance-v6.7.1/`. Рядок «See … for evidence» не веде нікуди.
>
> Документ лишається як запис лінії v6.7.x. Поточний стан — `README_FIRST.md` і
> `make release-verify`.

This ZIP is one canonical repository tree plus distribution evidence.

- Release: `v6.7.1`
- Canonical Git bundle: `KORPUS_SYSTEM_v6.7.1.bundle` (`git bundle create --all`, complete history)
- Source preservation: 604/604 baseline source paths retained; 27 source paths added
- Fresh tests: 1318 total, 0 failures, 0 errors, 1 skipped
- Coverage: line 0.9171, branch 0.7902
- Mutation: 259/259 valid mutants killed; full-catalogue score 1.0
- Engineering operational gate: PASS, production_authorized=false
- Production assurance: FAIL (fail-closed on missing external/live evidence)

See `reports/ASSURANCE_REVERSE_CYCLES_2026-08-10.*` and `reports/assurance-v6.7.1/` for evidence.
