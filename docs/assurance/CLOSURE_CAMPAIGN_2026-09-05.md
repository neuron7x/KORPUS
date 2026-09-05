# Кампанія закриття 2026-09-05 — протокол KORPUS-CLOSE-2026-09-05

**Кандидат:** `fcc46104` · **дайджест джерела:** `b9096028` (`evidence_paths`)
**Дзеркала:** `local = origin = gitlab = fcc46104`
**Клас документа:** `MEASURED_CAMPAIGN_RECORD`. Кожне число нижче має артефакт у дереві;
чого немає — назване `NOT_EXECUTED`, а не пропущене.

---

## 0. Вирок

```
INTERNAL_CLOSURE       TRUE   (у межах названого нижче знаменника)
PRODUCTION_AUTHORIZED  FALSE  (8 EXTERNAL_REQUIRED; жоден локальний доказ їх не задовольняє)
```

Ці два рядки не суперечать один одному і не є компромісом. Внутрішній контур замкнено;
зовнішні повноваження не вигадано. Локально зелений репозиторій не виробляє зовнішньої
авторизації — і саме тому обидві претензії `CLM-PRODUCTION-AUTH` та `CLM-INDEPENDENT`
стоять у реєстрі як `REFUTED_BY_EVIDENCE`, а не відсутні.

---

## 1. Що показав вимір, з якого почалась кампанія

`current-truth-verify` червонів на `BLOCKER_REGISTRY.internal_executable_unresolved_zero`:
**сім** внутрішніх блокерів із чотирнадцяти. Кожен читався як «бракує зовнішньої сторони».

Вимір сказав інше. Усі сім мали **одну** причину:

```json
"failed_external_checks": ["gate_source_bound"],
"software_ready": true,
"missing_software_artifacts": []
```

Докази **існували**. Вони описували дерево до шести комітів тієї доби. `release_truth.py`
формулює це дослівно у власному коментарі: прив'язка закривається **перезняттям** гейта на
цьому коміті, і називати таке зовнішньою дією означає обіцяти, що людина зробить те, що
зробить лан.

**Наслідок методологічний.** «Блокер» — не властивість предмета, а стан пари
(доказ, дерево). Той самий предикат є зовнішнім або машинним залежно від того, чому саме
він не задоволений. Перелік блокерів без поля причини не піддається цій різниці й
систематично завищує зовнішній борг.

---

## 2. Що зроблено — і чого не зроблено

Закрито **без жодного рядка зміни джерела**. Дайджест `b9096028` до і після — той самий:

| предикат | стан до | стан після | чим закрито |
|---|---|---|---|
| `live_postgres_rls` | `INTERNAL_STALE` | `CLOSED_ANCHORED` | `external-gate-campaign` |
| `production_like_load` | `INTERNAL_STALE` | `CLOSED_ANCHORED` | навантаження на чистій топології |
| `trusted_load_attestation` | `INTERNAL_STALE` | `CLOSED_ANCHORED` | те саме навантаження |
| `trusted_recovery_attestation` | `INTERNAL_STALE` | `CLOSED_ANCHORED` | навчання відновлення на PostgreSQL |
| `exact_python_3_12_13_environment` | `INTERNAL_STALE` | `CLOSED_ANCHORED` | гейт **усередині образу** |
| `external_independent_redteam` | `INTERNAL_STALE` | `CLOSED_ANCHORED` | `production-redteam-internal` |
| `live_vulnerability_scanners` | `INTERNAL_STALE` | `EXTERNAL_REQUIRED` | **винесено назовні чесно** |

Останній рядок — не поразка, а виправлення класифікації: контейнерний SBOM
(`api-sbom.cdx.json`) виробляє **лише** джоб `container:sbom` у GitLab CI, локального
виробника не існує. Предикат, який не має машинної дороги в цьому дереві, не сміє
називатись внутрішнім.

---

## 3. Числа кандидата

```
internal_executable_unresolved   0
CLOSED_ANCHORED                  6        EXTERNAL_REQUIRED  8
software_ready                   14 / 14
current-truth                    PASS     failures: []
handoff release_evidence         BOUND    production_authorized: false
лан make check                   rc=0     (13 цілей)
курована мутація                 624 вбито / 0 вижило
clean-room (origin, свіжий venv) 4159 тестів / 0 падінь / 0 помилок / 48 пропущено
claims                           SUPPORTED 5 · REFUTED_BY_EVIDENCE 2 · UNRESOLVED 0
```

**Навантаження** (`PRODUCTION_LIKE`, 4 різні суб'єкти):

| фаза | паралелізм | запитів | p50 | p95 | статуси |
|---|---|---|---|---|---|
| холодний перший | 1 | 1 | — | — | 200 за 1,458 с |
| навантаження | 4 | 75 | 1,862 | 2,546 | 75×200 |
| soak | 4 | 187 | 1,678 | 2,459 | 187×200 |
| сплеск | 12 | 952 | 0,060 | 2,613 | 145×200 · 53×429 · 754×503 |

**Відновлення:** RTO 10,430 с · RPO 13,442 с · втрачено подій 0 · клас `ci-fixture`.

---

## 4. Межі, які не можна прочитати як досягнення

1. **`clean_room` не є незалежною валідацією (L9).** Незалежні лише вхід (клон з
   `origin` на точний SHA) і інтерпретатор (venv з нуля за локами). Виконавець той самий.
   Клас доказу названо в артефакті: `REMOTE_SOURCE_FRESH_DEPENDENCIES`.

2. **`mutation_score_over_catalogue: 1.0` — це число ПРО КАТАЛОГ.** Виміряно 29.08.2026:
   162 модулі й 15 853 рядки — **42 % джерела** — не мають жодного мутанта. Оцінка над
   каталогом істинна і про них не говорить нічого.

3. **Клас масштабу відновлення — `ci-fixture`.** Обсяг на два порядки нижчий за підлогу
   претензії (100 000 рядків або 1 ГБ). Час 10,4 с не переноситься на операційний корпус.

4. **GitHub Actions не виконують кроків узагалі.** Сто прогонів: `success = 0`,
   `failure = 99`, `cancelled = 1`; `runner_name: ""`, `steps: 0`. Дослівна причина з
   GitHub API: *"The job was not started because your account is locked due to a billing
   issue."* Отже єдиний trusted CI — GitLab; GitHub у цій екосистемі є **архівом і
   нічого не стверджує**.

   **Наслідок другого порядку:** захист гілки на GitHub **не сміє** вимагати статусів
   Actions, доки це триває — required checks, які не можуть виконатись, зробили б `main`
   назавжди незлитним.

---

## 5. Три вади, знайдені самою кампанією

**5.1. Порада у тексті відмови називала не ту ціль.** `handoff-verify-bound` радить
`make assurance operational-gate`. Порада виконана **тричі**, обидві цілі `rc=0`, вирок не
рухався: `assurance` виконує `run_research_assurance.py` і не торкається
`reports/RESEARCH_ASSURANCE_REPORT.json`, який гейт читає. Той файл пише
`assemble-assurance`. Ознака хибної поради: **виконав — вирок не зрушив**.

**5.2. Кампанія гейтів кликала гейт без обов'язкового аргументу.**
`run_external_gate_campaign.py` викликав `run_exact_environment_gate.py` без
`--profile {development,runtime}`, який не має дефолту **навмисно** — щоб доказ робочої
машини не задовольнив мовчки твердження про продакшен. Гейт падав з usage-помилкою, отже
предикат `exact_python_3_12_13_environment` **не мав жодної машинної дороги до рішення**:
вічне `STALE`, яке читалося як очікування на людину (L5).

**5.3. Вимір проти живої системи міряв чужу ревізію.** Перший прогін навантаження дав
`environment_class: LOCAL_DEV` із підставою «процеси, старші за код». Пілотний API на 8030
було перезапущено, а `korpus-public-api` на 8000 лишався з 15:54 — старший за три коміти
тієї доби. **Гейт `topology_environment_class` спіймав це сам.** Після рестарту обох:
«оголошені юніти активні, несуть поточний код і є предметом виміру» → `PRODUCTION_LIKE`.

---

## 6. Що лишається зовнішнім

Вісім предикатів класу `EXTERNAL_REQUIRED`: `live_vulnerability_scanners`,
`real_domain_corpus_tevv`, `independent_tevv`, `production_like_tevv_environment`,
`trusted_hosted_builder`, `trusted_release_signing`, `pec_human_production_authority`,
`pec_canary_revision_admission`.

`trusted_builder_ids` у `config/assurance/trusted-builders.v1.json` — **порожній список**,
і це не недогляд: локальний провенанс може бути структурно дійсним і не задовольняти
довіри до збирача, доки не з'явиться незалежно керована платформа збірки.

**Найменша наступна дія власника — одна:** розблокувати білінг облікового запису GitHub
або визнати GitHub archive-only письмово. Усе інше в цьому переліку потребує третьої
сторони, а не рішення.
