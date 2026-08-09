# KORPUS — локальна передача роботи

Цей каталог є точкою входу для подальшої роботи на Linux через Claude Code або Codex.

## Що є джерелом істини

1. Git commit/tag і `SOURCE_MANIFEST.json`.
2. Виконуваний код, міграції, конфігурація та `reports/*.json`.
3. `docs/audit/closure/*.json` — статус усіх 99 findings і залишковий борг.
4. `handoff/machine/*.json` — машинна передача стану, ваг і наступних задач.
5. Markdown-документи пояснюють дані, але не можуть скасувати машинний FAIL.

Чат або LLM не є джерелом істини. Агент може запропонувати зміну, але істинність зміни встановлюють тільки новий commit, тести, eval, mutation, migration та release evidence.

## Перші команди

```bash
cd repository
cp .env.example .env
make api-install
make bootstrap
make api-test
python3 scripts/verify_handoff_contract.py
```

Для повної Git-історії клонуй bundle з каталогу `git/`, а не виконуй `git init` у розпакованому snapshot.

## Перед початком роботи

Прочитай послідовно:

1. `AGENTS.md`
2. `handoff/acts/00_CURRENT_STATE_ACT.md`
3. `handoff/acts/06_CALIBRATION_WEIGHTS_ACT.md`
4. `handoff/plans/NEXT_10_ITERATIONS.md`
5. `handoff/plans/NEXT_7_INTEGRATIONS.md`
6. `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json`
7. відповідний master prompt у `handoff/prompts/`

## Заборона

Не вмикати `production_authorized=true`, semantic weight, restricted corpus або зовнішній egress без окремого доказового профілю та закриття відповідних acceptance predicates.
