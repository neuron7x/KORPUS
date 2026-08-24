# АКТ ФАКТИЧНО ВИКОНАНИХ РОБІТ — KORPUS v0.9.7

**Дата:** 2026-08-24  
**Об’єкт:** KORPUS v0.9.7 — recovered FULL SSOT repository  
**Статус акту:** repository-recovery evidence; не є production authorization.

## 1. Відновлення єдиного джерела істини

Виконано безвтратне відновлення з двох фактичних джерел, що збереглися в поточній сесії:

1. `KORPUS_v0.9.7_MATHEMATICAL_ASSURANCE_HARDENED_FULL_SSOT_2026-08-24.zip` — початковий uploaded FULL_SSOT.
2. Фізична робоча копія `korpus_work/KORPUS_v0.9.7_MATHEMATICAL_ASSURANCE_HARDENED_FULL_SSOT_2026-08-24`, у якій збереглися зміни та generated evidence цієї сесії.

Програмне порівняння по відносних шляхах і SHA-256 встановило:

- baseline files: **2151 [ANCHORED]**;
- baseline files missing from recovered worktree: **0 [ANCHORED]**;
- current recovered files: **3226 [ANCHORED]**;
- baseline unchanged: **2134 [ANCHORED]**;
- baseline modified in current worktree: **17 [ANCHORED]**;
- files added in current worktree: **1075 [ANCHORED]**.

Отже recovered repository є строгим superset початкового uploaded repository за файловою множиною: жоден baseline path не втрачений.

## 2. Ключові інженерні зміни, що фізично присутні у recovered repository

Серед baseline-файлів, байти яких змінено відносно uploaded FULL_SSOT:

- `scripts/bounded_process.py`;
- `scripts/process_group_control.py`;
- `scripts/run_mutation_tests.py`;
- `scripts/build_readiness_947_evidence.py`;
- `apps/api/tests/test_regression_shard_contract.py`;
- `apps/api/tests/test_readiness_evidence_builder.py`;
- `config/operations/module-budget.json`;
- current-truth / dependency-lock / evidence-index / hard-predicate / blocker / claim-ledger reports;
- `SOURCE_MANIFEST.json`;
- `PACKAGE_BUILD.json`.

Додаткові generated files включають regression/mutation shards, pytest/JUnit/log/evidence artifacts, bytecode/cache artifacts та інші session outputs. Вони збережені в recovery snapshot навмисно: recovery-first policy забороняє втрату даних заради «чистоти» distribution.

## 3. Верифікований executable evidence, присутній у recovered tree

### Full backend regression

`var/final-regression-v2/merge.json`:

- release: `v0.9.7`;
- source digest: `9544e268eba0435a6077be23e5d57a45b386b8357f63629ae90eee4c45e96449`;
- collection: **2422 [ANCHORED]**;
- shards: **32/32 [ANCHORED]**;
- failures: **0 [ANCHORED]**;
- errors: **0 [ANCHORED]**;
- skipped: **1 [ANCHORED]**;
- status: **PASS [ANCHORED]**.

### Mutation evidence

Repository містить historical full-catalogue mutation report `349/349 killed`, але його production mutation gate прив’язаний до попереднього source-tree digest `31b1d7bd…`; після подальшого source change це **не вважається current-source production authority**. Fresh post-change shard campaign у recovered worktree є частковим. Тому цей акт не заявляє current-source mutation = PASS.

### Current-truth evidence

`reports/CURRENT_TRUTH_VERIFICATION.json` має `PASS`, але прив’язаний до source-tree digest `31b1d7bd…`, тоді як пізніший full regression використовує `9544e268…`. Отже current-truth artifact у recovered tree збережений як історичне evidence, але потребує regeneration перед новим promotion decision.

## 4. Безвтратний canonical recovery ZIP

Створено:

`KORPUS_v0.9.7_RECOVERED_FULL_SSOT_CANONICAL_2026-08-24.zip`

Контроль:

- archive files: **3226 [ANCHORED]**;
- SHA-256 verification failures against recovery manifest: **0 [ANCHORED]**;
- ZIP SHA-256: `375db482291b159a483ea8e01499f092c3eea2dcbb49fb788676aa65adeb6f4a`;
- size: **122,933,178 bytes [ANCHORED]**.

Кожен файл ZIP після побудови повторно прочитаний із архіву та звірений із SHA-256 відповідного current-worktree файла.

## 5. Межа твердження

**Repository recovery integrity: PASS.**  
**No-baseline-file-loss predicate: PASS.**  
**Production promotion: NOT CLAIMED.**

Причина: recovery snapshot навмисно зберігає також stale/historical evidence; production authority потребує нового source freeze, regeneration source/current-truth manifests, fresh complete mutation rebinding, exact static/runtime gates та зовнішніх PostgreSQL/TEVV/load/signing predicates.
