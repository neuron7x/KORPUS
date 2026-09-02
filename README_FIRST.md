# KORPUS v0.9.7 — START HERE

Canonical engineering-closure repository snapshot — **23 August 2026**.

Поточний стан читається ОДНІЄЮ командою — `make release-verify`. Вона відмовляється
міряти брудне дерево (`REFUSED`, rc 2) і дерево, що зрушило під час прогону
(`INVALID`, rc 3), тож її вихід не може описувати щось інше, ніж він виміряв.

- Behavioral source · Regression · Mutation · Web · Determinism — усе в її звіті
- Software hard predicates: **14** (`config/assurance/production-hard-predicates-v1.json`)
- External hard predicates: **0 із 14**, і це ЧЕСНИЙ нуль, а не невиміряний стан:
  реєстри підписантів порожні за побудовою, тож жодна атестація не перевіряється і жодна
  підстава не знімається. Внесення ключа — акт приймальника, не правка розробника
- Production authorization: **FALSE**
> **ВИПРАВЛЕНО 02.09.2026.** Числа в цьому блоці були заморожені 23.08.2026 і подавались
> як поточний стан. Виміряно: тестів **3814**, не 2345; мутантів **574**, не 349; шардів
> регресії **24**, не 64; дайджест джерела за одну годину прийняв три різні значення.
> Тому числа, що рухаються, тут більше не вкарбовані — названі ЛИШЕ джерела, бо друге
> оголошення рухомого числа розходиться мовчки, і саме так воно й розійшлось.


Read: `reports/ENGINEERING_CLOSURE_CURRENT.md` → `handoff/architecture/ARCHITECTURE_REFERENCE_v0.9.7.md` → `handoff/operations/OPERATOR_RUNBOOK_v0.9.7.md` → `handoff/operations/NEXT_STAGE_EXTERNAL_EVIDENCE_v0.9.7.md`.

Raw current evidence is portable under `handoff/evidence/current/`.
