# Архітектурні межі — issue #46

Дата: 2026-09-08. База: `4353ea3c`. Реалізація: `28c5fa2c` + `e74d9cb8`.
Це локальна перевірка змін, не дозвіл релізу чи production.

Сім задач за результатами перевірки коду:

- A1. Винести складання answer pipeline з HTTP у `korpus.answer_composition`.
- A2. Зв'язати answer-policy, ranking і cache identity одним читанням calibration profile.
- A3. Зберігати ін'єктовані planner/composer незалежно від їхнього `bool()`.
- A4. Закрити relative/parent-import обходи перевірки шарів; класифікувати MCP як transport;
  включити Retriever у перевірку реалізацій портів.
- A5. Атестувати повернене resource-policy рішення до резервування ефекту та dispatch.
- A6. Відхиляти будь-який не-`None` результат ін'єктованого schema validator для input/output.
- A7. Відхиляти HTTP-результати після монотонного total deadline, враховуючи план,
  заголовки, chunks, EOF і декодування.

## Відтворені дефекти на базі

- Калібрування: 2 читання; `answer_profile=first-profile`, `cache_profile=second-profile`.
- Falsy planner/composer: `injected_adapter_preserved=False`, по одному виклику replacement factory.
- `test_capability_gateway_return_decisions.py` із початковим `korpus`:
  **23 failed, 1 passed**, exit 1. Це навмисні негативні контролі, не результат кандидата.

## Виконані перевірки кандидата

Python: канонічний `apps/api/.venv/bin/python` (Python 3.12); `PYTHONPATH=apps/api/src`
із ізольованого worktree; pytest з `-p no:cacheprovider`.

- Об'єднаний прогін: **622 passed, 1 warning**, 11.81 s, exit 0.
  `test_answer_composition_boundary.py`, `test_architecture.py`,
  `test_architecture_import_boundaries.py`, `test_calibration.py`,
  `test_query_planner_boundary.py`, `test_model_executor_lifecycle.py`,
  `test_openai_model_adapter.py`, `test_quote_provenance.py`, `test_support_gate.py`,
  `test_citation_alignment.py`, `test_authority_ranking.py`, `test_retriever_scope.py`,
  `test_mcp_server.py`, `test_capability_gateway_*.py`.
- M43 після перенесення цілі в composition root: **1 valid / 1 killed**, exit 0;
  `scripts/run_mutation_tests.py --only M43_WIRED_PER_VERSION_CAP_WIDENED`.
- Mypy шести змінених source-модулів: exit 0.
- Module budget: **646 modules, 0 violations, 0 unbudgeted**, exit 0.
- Import cycles: **0**, exit 0. `git diff --check`: exit 0.

## Межі результату

Незалежний verifier, окремий worktree `a6bfa47f828f624eb3c2356ba475608edf62803c`
(ті самі два source-коміти): **PASS_WITH_CAVEATS**, блокувальних дефектів не виявлено.
Власний прогін: **82 composition/architecture + 511 gateway passed**, exit 0.
Чотири baseline/current порівняння policy/retriever та дві перевірки порядку
calibration-before-factories пройшли. Мутації в пам'яті: M43 убито;
schema/policy/deadline дали відповідно **14/9/8 очікуваних падінь**, exit 1.
Мутантів не збережено у source. Ruff/mypy/module-budget: exit 0.

Незалежний HTTP probe: deadline **20 ms**, блокування **80 ms** → відмова через
**81.16 / 80.61 ms** для headers/chunk. Це підтверджує межу нижче.

GitHub PR: https://github.com/neuron7x/KORPUS/pull/47 (draft).
Hosted CI на `bbe97dec`: jobs не стартували через **account billing lock**;
це повідомлення annotations для `repository-contract`, `research-assurance` і
`dependency-review`, не висновок із відсутніх логів.

A7 забороняє приймати прострочений результат, але **не перериває заблокований
синхронний transport**. Жорстка верхня межа wall-clock зайнятості worker лишається
незакритою; для неї потрібен transport із підтримкою скасування.

Попередження pytest: застаріла назва Starlette `HTTP_422_UNPROCESSABLE_ENTITY`.
Повний release lane, повний mutation catalogue і hosted CI тут не виконувалися.
Pre-commit не запускав перевірки через відсутність venv усередині worktree;
перевірки вище виконано вручну канонічним інтерпретатором.
Незакомічені звіти канонічного checkout не змінювалися. Production authorization
не надається; гілка потребує review перед merge.
