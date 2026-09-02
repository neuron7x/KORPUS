# Зведення дерев КОРПУСа — 02.09.2026

Канон: `main` @`9a0dfc5`, `/home/neuro7/Desktop/Ядро основний проект Корпус`, **2808 файлів**
(без `var/`, `.git` і кешів), 2558 із них під git.

Питання було: «звести всі копії дерев в одну». Відповідь **виміряна**, не оголошена:
жодна копія не несе коду, якого канон не має. Нижче — як це виміряно, щоб наступного разу
не міряти вдруге.

## Метод

Історія тут не вирішує нічого: п'ять дерев мають окремий корінь, тобто «попереду на N
комітів» для них не рахується взагалі. Тому порівнювався **ВМІСТ** — множина шляхів і
sha256 кожного файлу проти канону. Копія несе роботу тоді й лише тоді, коли має файл,
якого в каноні немає за жодним шляхом.

## Результат

| дерево | файлів | коду поза каноном | вирок |
|---|---:|---:|---|
| `korpus-gate-liveness/tree` | — | 0 | SUBSUMED, HEAD = `9a0dfc5` |
| `korpus-canon` | 532 | **0** | знімок, поглинутий |
| `.korpus-worktrees/issue-3-ci-isolation` | 1938 | **0** | знімок, поглинутий |
| `KORPUS_v0.9.7_..._CANONICAL_2026-08-23` | 2384 | **0** | знімок, поглинутий |
| `KORPUS-development-agent-1` | 700 | **0** | знімок, поглинутий |
| `KORPUS_v0.1.1_GITHUB_CANONICAL_BASELINE` | 720 | **0** | знімок, поглинутий |
| `HANDOFF_v5.1.0/repository` | 330 | **1** | навмисно прибраний wrapper (див. нижче) |
| `HANDOFF_v5.1.0/act-01-worktree` | 330 | 18 | handoff-артефакти, не код |
| `.codex/tmp/korpus-import/repo` | 696 | 1 | лише `.zip` |
| `Data Software/KORPUS-development` | 764 | 44 | старі імена канонових спроможностей |
| `korpus-platform` | 103 | — | **інший продукт** (v6.3.0), не зводиться |

## Дві пастки, на яких я спіймався сам

**Хибне «зламане посилання».** Grep за `source_manifest.py` дав збіги в `Makefile`,
`.gitlab-ci.yml` і `full_ssot_packager.py` — виглядало як посилання на файл, якого в
каноні немає. Посилання насправді на `verify_source_manifest.py`, який є. Так само
`prepare_postgres_test_role.py` знайшовся лише в **коментарі** тесту, який каже, що це
був десятирядковий wrapper і його прибрано. Підрядок — не посилання; звіряти треба точний
рядок виклику.

**44 файли, що виглядають як втрачена робота.** Гілка GitHub тримає
`0016_temporal_corpus_snapshot` … `0019_rls_binding_backend_identity`,
`rls_identity.py`, `secure_repository.py`, `answer_composition.py`, `review_locking.py`
(жодного з цих імен у каноні НЕМАЄ — вони лишились на гілці GitHub),
пакувальні `assurance_snapshot_*`, `package_contracts`, `snapshot_mutants`. Кожне має
канонового відповідника під іншим іменем і номером: міграції `0016`–`0022`,
`rls_repository.py`, `application/composition.py`, `infrastructure/review_transitions.py`
(оптимістичний перехід із `ReviewTransitionConflict`), `snapshot_assurance.py`,
`verify_package.py`, `package_full_ssot.py`, `run_research_assurance.py`,
`manifest_lib/`. Різні номери міграцій — це і є те зіткнення трьох ліній, через яке
текстовий мердж не сходився; воно вже розв'язане перенумерацією в каноні.

## Чого зводити НЕ МОЖНА

`~/korpus-gate-liveness/{base-test,base-validate,run-lint2,run-t1..t5}` — вісім копій,
**навмисно зіпсованих** проби живучості гейтів: `T1-authorization-bypass`,
`T2-classification-bypass`, `T3-coverage-floor`, `V17-self-signed-verdict`,
`V18-self-signed-shadowed`. Це отрути, а не робота. Мердж будь-якої з них вніс би в
продукт обхід авторизації і самопідписаний вирок. Вони одноразові й видаляються разом із
прогоном, що їх створив.
