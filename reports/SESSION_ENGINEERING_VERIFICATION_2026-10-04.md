# КОРПУС — звіт інженерної верифікації робіт сесії

**Ідентифікатор документа:** KORPUS-EVR-2026-10-04  
**Версія документа:** 1.0  
**Дата оцінювання:** 2026-10-04, Europe/Kyiv  
**Продукт / реліз:** КОРПУС / `v0.9.7`  
**Клас документа:** внутрішній engineering assurance record  
**Статус:** `PASS_WITH_EXTERNAL_BLOCKERS` для контрольованого пілота; `NOT_AUTHORIZED` для повного production  
**Кандидат:** доказова поверхня `e1543cac6ccb090d47cc8737542cdd5aebc5b5b5b2cf82550c48f96a6879fbb0` (`evidence_paths`)  
**Повне відстежуване дерево:** `db678be328f1db88278a277413ad33325559115b11d04175d231f8febf2baf6c` (`tracked_tree`)  
**Базовий source-коміт документа:** `b111a168b5f09e7d93bf9ab64bd613098e5c3bcf`  
**Production authorization:** `false`  

> Цей документ є інженерним записом доказів, а не самостійним доказом. Машиночитні
> артефакти, команди, коди завершення та хеші мають пріоритет над описовим текстом.

## 1. Контроль документа

### 1.1. Призначення

Документ фіксує весь обсяг робіт цієї сесії: консолідацію гілок, зміни API та
вебінтерфейсу, публічний edge, inference-контур, контроль доказів, security,
deployment, CI/CD, нічні перевірки, негативні контроли, фактичні дефекти, виправлені
хибні припущення та залишкові умови допуску до пілота й production.

### 1.2. Джерела істини

Пріоритет доказів, від найсильнішого до найслабшого:

1. Відтворюваний виконуваний gate із ненульовим кодом при негативному контролі.
2. Артефакт, прив'язаний до source digest, release та визначеного класу середовища.
3. Clean-room відтворення з віддаленого GitLab SHA і свіжих залежностей.
4. Live-вимір публічного deployment із названою точкою спостереження.
5. Статичний аналіз конфігурації або вихідного коду.
6. Описове твердження в цьому документі.

### 1.3. Епістемічні статуси

| Статус | Значення |
|---|---|
| `VERIFIED` | Властивість виміряна виконуваним контролем на названій поверхні. |
| `ANCHORED` | Твердження прив'язане до зовнішнього першоджерела або криптографічної тотожності. |
| `DERIVED` | Значення обчислене з перевірених входів за явно визначеним правилом. |
| `UNKNOWN` | Доказ відсутній, не завершився або не відповідає потрібному класу середовища. |
| `REFUTED` | Контрприклад відтворено. |

`UNKNOWN` не зараховується як `PASS`; пропуск тесту не зараховується як виконана
перевірка; локальний доказ не підмінює незалежну зовнішню атестацію.

## 2. Виконавче рішення

### 2.1. Рішення для бізнесу

| Режим | Рішення | Обґрунтування |
|---|---|---|
| Контрольований приватний пілот | `GO WITH CONTROLS` | Read-only публічна поверхня, fail-closed admin/ingest, локально закрита software verification, спостережуваність і rollback-процедури. |
| Загальнодоступний production | `NO-GO` | Немає повного набору зовнішніх production-предикатів, trusted signing та owner authorization. |
| Твердження про фізичну якість дисплея | `OUT OF SCOPE` | CSS-сигнал не доводить нітність, чорний рівень панелі або умови сприйняття. |

Допустимий пілотний контур обмежений читанням і відповідями з цитуванням. Публічний
edge не допускає ingestion, admin-операції або operator console. Будь-яке розширення
цієї поверхні є новою зміною ризику й потребує окремого gate.

### 2.2. Формальна модель допуску

```text
pilot_admissible =
  software_gates_pass
  AND public_surface_fail_closed
  AND evidence_is_source_bound
  AND monitored_rollback_exists
  AND owner_accepts_named_external_blockers

production_authorized =
  all_required_production_predicates
  AND trusted_builder_provenance
  AND trusted_release_signature
  AND owner_authorization
```

Поточний стан: `pilot_admissible = conditional`; `production_authorized = false`.

## 3. Обсяг, межі та критерії істинності

### 3.1. Включено

- FastAPI application, inference/adjudication та retrieval-контур.
- Static web frontend, claim-level rendering, дизайн-токени й accessibility-контракти.
- nginx public edge, Tailscale Funnel, runtime identity, audit key handling.
- Public watchdog, escalation ladder, deployment units і environment parity.
- CI/CD, release evidence, gate closure, liveness, mutation та clean-room reproduction.
- Security scanners, dependency locks, SBOM, container image й exact runtime profile.
- Doctrine catalogue, source accessibility, refusal ledger і publication mirrors.
- Git-історія, canonical branch, isolated worktree та merge discipline.
- Публічне live deployment і browser-facing smoke checks.

### 3.2. Не включено як доведений факт

- Незалежний зовнішній red-team.
- Атестація exact deployment host сторонньою довіреною стороною.
- Production-like PostgreSQL/RLS доказ, доки поточний прогін не завершився.
- Production-like load та disaster-recovery атестації на поточному source digest.
- Реальна ефективність для бойового користувача без польового TEVV.
- Фізичний black level, HDR peak luminance, tone mapping або калібрування дисплея.
- Право власника на остаточний production release signing.

### 3.3. Критерій незмішування кольору й фізики

```text
CSS color code
!= display luminance
!= HDR mastering level
!= material reflectance
```

Для вебінтерфейсу доводиться цифровий контракт `#000000` / alpha 1 та контраст
foreground. Фізична яскравість у `cd/m²` не виводиться з CSS-коду.

## 4. Вихідний стан і ризики

На початку робіт одночасно існували паралельні сесії, незведені гілки, stale evidence,
частково оголошені deployment-інваріанти та публічний контур, у якому конфігураційний
текст можна було помилково прийняти за фактичний стан процесу.

Критичні вихідні ризики:

- один корисний change-set міг залишитися поза канонічною гілкою;
- зелений aggregate verdict міг приховати падіння конкретного predicate;
- доказ міг описувати інше дерево або іншу digest-поверхню;
- nginx reload міг повернути `0`, не застосувавши новий listener;
- mutation probe міг змінити живе дерево й не відновити його після `SIGTERM`;
- public watcher міг повторювати ідемпотентну дію, яка не відновлює URL;
- frontend відкидав per-claim adjudication, хоча API її вже повертав;
- `#000000` порушувався ненульовим body background та gradient contamination;
- source-access refusal міг прострочитися без виміряного альтернативного маршруту;
- runtime container мав чотири виправні HIGH CVE;
- API Dockerfile та entrypoint не входили до evidence digest, тому зміна runtime могла
  успадкувати доказ попереднього образу.

## 5. Реалізовані зміни за підсистемами

### 5.1. Канонічна історія та паралельна робота

- Роботи ізольовано в окремому git worktree, без перезапису змін паралельного агента.
- Гілки оцінювались за змістом, чистотою, source-bound evidence та green gates, а не за
  назвою або давністю.
- Конфліктні згенеровані звіти не використовувались як джерело функціонального коду.
- Merge-послідовність визначена як: source commit -> source manifest -> evidence
  producers -> portable reports -> canonical integration -> live deployment smoke.

### 5.2. Публічний edge

Реалізовано й перевірено:

- nginx слухає loopback `127.0.0.1:8081`, а не wildcard interface;
- `/console*` та operator-only assets не публікуються;
- ingestion/admin/write routes відсікаються edge-рівнем до application body parsing;
- audit read route не маскується edge-правилом: application role повертає чесну відмову;
- runtime identity інжектується edge-контуром;
- model egress posture для unattended public path — `local_only`;
- audit HMAC key створюється поза git, перевіряється на непорожність і читається з файла;
- key id та verification key ring оголошені однаково в shell і systemd unit.

Ключові реалізації:

- `deploy/public/nginx.conf`
- `scripts/serve_public.sh`
- `deploy/public/korpus-public-api.service`
- `scripts/verify_public_surface.py`
- `scripts/public_operator_surface.py`
- `scripts/check_public_env_parity.py`

### 5.3. Public watchdog і відновлення

- Для кожного компонента введено окремий escalation ladder.
- Для публічного Funnel послідовність: `restore_funnel` -> `recycle_funnel`.
- Успішний health check скидає rung.
- Recovery ізольовано на dedicated binding `--https=8443`; default Funnel `443` не
  торкається.
- Одна action виконує всю послідовність команд, а не лише першу.

Ключова реалізація: `scripts/public_health_controller.py`.

### 5.4. Frontend і zero-black design contract

- Канонічний substrate змінено з `#010101` на `#000000`.
- Видалено gradient над body та дубльований hardcoded background.
- Ієрархія будується near-black surfaces, borders, text і semantic accents, не
  освітленням global substrate.
- Primary data використовує світлі нейтральні токени; `#737373` не допускається як
  normal text на `#000000` через контраст приблизно `4.43:1`.
- Додано static contract і browser computed-style check.
- Screenshot pixel test не заявляється виконаним: `Page.captureScreenshot` зависав у
  наявному harness, обмеження назване, а не приховане.

Ключові реалізації:

- `apps/web/design/tokens.json`
- `apps/web/design/consumer.css`
- `apps/web/scripts/validate.mjs`
- `apps/web/scripts/browser_e2e.mjs`

### 5.5. Per-claim inference presentation

Frontend тепер рендерить кожну claim окремо з:

- presentation verdict;
- source title;
- adjudication reason;
- візуально окремим claim block.

Це усунуло semantic loss між API payload і користувацьким інтерфейсом.

Ключова реалізація: `apps/web/public/app.js`.

### 5.6. Gate architecture

Введено три явні entry points:

```text
make check              # tree/software lane
make check-deployment   # deployment/runtime lane
make check-nightly      # дорогі докази
```

`verify_gate_closure.py` вимірює не лише reachability Make-targetів, а фактичне
виконання scripts. Реєстр винятків fail-closed для:

- unregistered gaps;
- dead exemptions;
- ghost exemptions;
- exemptions без причини.

На момент завершення основного closure-етапу: 193 targets, 44 verification targets,
27 початково не виконувались жодним entry point; реєстр скорочено до 19 явно названих
винятків.

### 5.7. Nightly evidence lane

- Додано systemd service/timer для дорогих перевірок.
- Розклад: `05:10 Europe/Kyiv`, `Persistent=true`, timeout 90 хвилин.
- Порядок виправлено: спочатку виробляються свіжі evidence artifacts, потім
  вимірюється gate liveness, mutation probe, clean clone і coverage ratchet.
- Mutation є останнім producer у доказовому ланцюгу, бо його portable report
  прив'язаний до source digest.

Ключові реалізації:

- `scripts/install_nightly_gates.py`
- `deploy/agents/korpus-nightly-gates.service`
- `deploy/agents/korpus-nightly-gates.timer`
- `Makefile`

### 5.8. Mutation safety і negative controls

- Probe за замовчуванням працює в copy sandbox, не в живому checkout.
- `.git`, `var`, `reports`, `node_modules`, caches та build outputs виключені з копії.
- `SIGTERM`, `SIGINT`, `SIGHUP` переводяться у контрольований failure path.
- Lock містить PID; orphaned lock є подією, а не мовчазним станом.
- In-place mode окремий і відмовляє на dirty tree.
- Workspace передається параметром, не global mutable state.

Фактичний destructive negative control: probe вбито `SIGTERM` посеред виконання;
до й після — `0` dirty source files, lock видалено, sandbox не залишився.

### 5.9. Module budget і accepted debt

- Module ceilings є ratchet: дозволене зменшення, підняття потребує названої причини.
- Перевірка підняття прив'язана до `(ceiling_key, numeric_value)`, а не лише path.
- Для deployment debt введено правило: гірше за ceiling — `FAIL`; дорівнює — `PASS`;
  краще — `PASS` із вимогою знизити ceiling.
- `span-hygiene` зафіксовано як accepted red із ceiling `89`, а не замасковано green.

### 5.10. Doctrine catalogue й доступ до джерел

- Vantage gap закривається лише одним із двох доказів:
  - reciprocal relation до captured copy тієї самої publication;
  - недавній structured external-vantage fetch із exact title/issuer, HTTPS,
    підтримуваним MIME, позитивною кількістю сторінок і явним limitation.
- Максимальний вік external route — 30 днів.
- External vantage не підмінює deployment-host reachability.
- Route не пригнічує extractor/source failures; він застосовується лише до `VANTAGE`.

Закриті прострочені gaps:

- `T1A-TRADOC-UAS-TACTICS` — офіційний Army PDF, 5 сторінок, observed 2026-10-04;
- `T3A-FM-3-09` — reciprocal captured peer `ARTY-FM-3-09-2024`.

Ключові реалізації:

- `scripts/evidence_access_route.py`
- `scripts/validate_evidence_refusal.py`
- `config/corpus/doctrine_catalog_2026.json`
- `apps/api/tests/test_evidence_access_route.py`

### 5.11. Supply chain і runtime image

GitLab container scan на source-коміті `1f3d0122…` відмовив через чотири fixable HIGH
CVE в `libpcre2-8-0` версії `10.42-1`:

- `CVE-2026-103111`
- `CVE-2026-86145`
- `CVE-2026-89157`
- `CVE-2026-89161`

До API Dockerfile додано явне встановлення `libpcre2-8-0`; Debian security repository
встановив `10.42-1+deb12u2`. Локальний Trivy scan виправленого image:

```text
severity: HIGH,CRITICAL
ignore-unfixed: true
fixable findings: 0
exit code: 0
```

Цей дефект не перетворено на ignore-list або waiver.

### 5.12. Provenance boundary runtime-образу

Після зміни Dockerfile виявлено, що `compute_source_digest` не змінювався. Причина:
`EVIDENCE_SOURCE_PATHS` перелічував окремі API subpaths, але не `apps/api/Dockerfile`
та `apps/api/docker-entrypoint.sh`.

Виправлення:

- сім гранулярних API paths замінено єдиною поверхнею `apps/api`;
- caches, `.venv`, `var`, `dist` і untracked content далі виключені;
- додано behavioral test для Dockerfile та entrypoint;
- додано mutant `M726_API_RUNTIME_DEFINITION_OUTSIDE_EVIDENCE_DIGEST`.

Негативний контроль M726: заміна `apps/api` на `apps/api/src` вбивається тестом.

## 6. Дефекти, причинні механізми та коригувальні дії

| ID | Дефект / хибне припущення | Причинний механізм | Коригувальна дія | Статус |
|---|---|---|---|---|
| D-01 | `nginx -s reload` повернув `0`, але listener не змінився | Код завершення описував signal delivery, не effect; bind на `127.0.0.1:8081` конфліктував | Повний restart; live binding перевіряється окремо | `CLOSED` |
| D-02 | mypy помилково названо cache problem | `mypy_path` у `mypy-scripts.ini` розв'язувався від каталогу config; `ignore_missing_imports` перетворював `korpus` на `Any` | Диференційний cold-cache test із/без `MYPYPATH=apps/api/src`; початкове твердження відкликано | `CLOSED` |
| D-03 | Gradient guard не міг почервоніти | Неправильна destructuring group у `matchAll` | Виправлено індекс групи; negative control | `CLOSED` |
| D-04 | Poison test проходив на чистому tree | Async edit викликано без `await` | Додано очікування mutation writes | `CLOSED` |
| D-05 | Три mutants вижили під aggregate verdict | Один failure маскував видалення іншого predicate | Тести перевіряють конкретний finding id | `CLOSED` |
| D-06 | Dead defense stripping comments | Parser і так матчав лише `^export`; захист не захищав жодної поведінки | Dead code/test/mutant видалено; закрито реальну прогалину indented export | `CLOSED` |
| D-07 | `env $(...)` ламав path із пробілами | Shell word splitting | `--exec` передає environment через process API | `CLOSED` |
| D-08 | Runtime export містив `@KORPUS_ROOT@` | Друга неповна substitution logic | Використано єдиний `install_public_runtime.render()` | `CLOSED` |
| D-09 | Unit env parser обрізав JSON key ring | Regex завершував quoted Environment на першій quote | Escape-aware parser + `values_are_usable` | `CLOSED` |
| D-10 | Mutation probe залишив живий weakened validator | `SIGTERM` не є Python exception; `finally` не виконався | Copy sandbox, signal handlers, live-lock check | `CLOSED` |
| D-11 | Handoff failure хибно пояснено відсутністю `.git` | Припущення не підтверджено; списки файлів були 1677=1677 | Вимір показав stale evidence після commits; нічний порядок змінено | `CLOSED` |
| D-12 | `max(mine,theirs)` для budget merge скасував lowering | `max` зберігає слабшу, більшу стелю | Стеля встановлюється за measured merged tree | `CLOSED` |
| D-13 | `make check PY="path with spaces"` -> 127 | `$(PY)` не quoted у Makefile | Використано project venv без space-path; ризик задокументовано | `CONTAINED` |
| D-14 | Evidence chain чотири рази ставав stale | Неправильний producer order | Commit -> add -> manifest -> desired state -> mutation last | `CLOSED` |
| D-15 | `EnvironmentFile` суперечив unit invariant | Існуючий contract забороняв зовнішній mutable env source | Повернуто self-declaring unit; directive-level test | `CLOSED` |
| D-16 | Owner packet успадковував чужі load/recovery metrics | Producer копіював stale artifacts без current-source binding | Packet не успадковує невідповідні виміри | `CLOSED` |
| D-17 | PostgreSQL readiness race | Один успішний probe вважався стабільністю | Потрібні три послідовні successes | `CLOSED` |
| D-18 | Sharded regression видаляв tracked receipts | Cleanup не розрізняв generated й tracked evidence | Tracked receipts зберігаються | `CLOSED` |
| D-19 | Scanner evidence міг пройти за filename | Consumer не перевіряв payload class/current commit | Payload schema, scanner set, exit codes і accepted source commits | `CLOSED` |
| D-20 | Watchdog міг зачепити default Funnel | Recovery command не мав dedicated bind | Binding `--https=8443`; M722 negative control | `CLOSED` |
| D-21 | Два source refusals прострочились до 35 днів | Не було формального alternative-route predicate | `evidence_access_route.py`, 30-day age bound, 3 mutants | `CLOSED` |
| D-22 | M723 спочатку вижив | Тест одночасно ламав relation і capture, тому один дефект маскував інший | Контроль змінює лише relation; capture лишається валідним | `CLOSED` |
| D-23 | PostgreSQL gate завершився timeout через 600 с | Host load 15–17, 9.3 GiB swap, сторонні pbt-crm pytest processes | Результат класифіковано `UNKNOWN`, container прибрано; rerun лише в quiet window | `OPEN/UNKNOWN` |
| D-24 | Runtime image мав 4 fixable HIGH CVE | Digest-pinned base містив старий PCRE2; звичайний apt install не оновлював уже встановлену бібліотеку | Explicit `libpcre2-8-0` install; patched `10.42-1+deb12u2`; Trivy 0 | `CLOSED` |
| D-25 | Dockerfile change не змінював evidence digest | API surface була переліком subpaths без runtime definition files | Surface узагальнено до `apps/api`; test + M726 | `CLOSED` |

## 7. Верифікація, валідація і негативні контроли

### 7.1. Повний software evidence run до фінальної supply-chain корекції

На source digest `a1a5d4f14fed3efdcb97adb5e92bac56b06b9c453fea61d23a645d3a225e67b9`
було виконано:

| Контроль | Результат |
|---|---|
| Backend collection | 4,932 tests |
| Backend verdict | 4,886 passed; 46 skipped; 0 failed/errors |
| Sharded regression | 24/24 shards PASS |
| Web suite | 158/158 PASS; lint/build PASS |
| Inference security | 78/78; 7 attack families; 0 failures/skips |
| Full mutation | 658/658 valid mutants killed; survived/invalid/errors = 0 |
| Release microcampaign | 8/8 mutants killed |
| Clean-room GitLab clone | 4,884 passed; 48 skipped; 0 failed/errors |
| Eval | 30/30 PASS; synthetic limitation retained |
| Migration | 36 expected = 36 actual tables; FTS5; seeded audit head |
| Scale | 5,000 synthetic spans; 80 iterations; p50 10.376 ms; p95 12.716 ms; max 72.182 ms; top-1 recall 1.0 |
| Security scan | gitleaks, pip-audit runtime/dev, Trivy filesystem: exit 0 |

Ці числа не автоматично переносяться на нову runtime/provenance поверхню. Після D-24
і D-25 потрібен новий source-bound evidence set; документ не називає попередній set
фінальним доказом нового кандидата.

### 7.2. Нові targeted proofs на поточній поверхні

| Контроль | Результат |
|---|---|
| Fixed API image build | PASS |
| Trivy HIGH/CRITICAL, fixable only | 0 findings; exit 0 |
| Provenance behavioral tests | Dockerfile та entrypoint змінюють digest |
| Mutant M726 | 1/1 killed |
| Ruff | PASS |
| mypy | PASS |
| Source manifest | 2,085 files; root `418be220c446a15ef49e39a1a980e84d3d4d2201da973164bc7124d2ebc0d59a` |
| Module budget | 660 modules; 0 unbudgeted; 0 violations |

### 7.3. Негативні контроли, які змінили реалізацію

- Public edge: leakage, masquerade, wrong bind, wrong egress, absent identity, write route,
  unauthenticated role refusal та UNKNOWN paths.
- Environment parity: missing, extra, unusable, secret-by-value, wrong safety value.
- Gate closure: unregistered, dead, ghost і unreasoned exemptions.
- Deployment debt: worse/equal/better than ceiling.
- Evidence routes: one-way relation, stale external observation, route that must not lift
  non-vantage failure.
- Runtime provenance: API root replaced by `apps/api/src`.
- Mutation safety: forced `SIGTERM` during live probe.
- Public recovery: mutation from dedicated port `8443` to default `443`.

### 7.4. Чесні межі вимірів

- Scale report — SQLite synthetic benchmark, не production SLA.
- Eval — synthetic fixture, не real-domain human TEVV.
- Clean-room — fresh clone/dependencies, але не organizational independence.
- Local Trivy — технічний доказ current image, але CI marker має бути отриманий із
  pinned GitLab scanner job.
- Browser computed-style test доводить CSS value, не rendered pixel і не фізичний black.
- Timeout PostgreSQL gate є `UNKNOWN`; логи adversarial refusals не дорівнюють
  завершеному gate verdict.

## 8. Конфігураційне управління та канонічна історія

### 8.1. Виміряні фази сесії

| Фаза | Межа | Коміти | First-parent | Diff |
|---|---|---:|---:|---:|
| I | `8659cda^..eac3fe9` | 65 | 50 | 110 files; +16,647 / -5,005 |
| II | `eac3fe9..9c913d2` | 35 | 21 | 96 files; +12,814 / -1,360 |
| III | `f37b6e64..b111a168` | 11 | 11 | 38 files; +1,464 / -246 |

Фази I–III разом: 111 reachable commits у названих ranges; сума diff-статистик не є
кількістю унікальних рядків, бо той самий рядок міг змінюватися в кількох фазах.

### 8.2. Окремий Pages deployment

Публічний web artifact мав окрему deployment-історію:

```text
a06b57e5
d88d8351
7ac71410
43d8da6d
b42f024c
22294c8
```

GitLab Pages pipeline `2910074273`: `success`.

### 8.3. Канонічна дисципліна

- Source зміни комітяться до генерації final evidence.
- `SOURCE_MANIFEST.json` генерується після включення всіх source paths у index.
- `config/operations/desired-state.json` регенерується після Dockerfile/CI changes.
- Reports не використовуються для маскування зміни source digest.
- Dirty user-owned reports у canonical checkout не перезаписуються автоматично.
- Повне злиття допустиме лише після green current-source gates і live smoke.

## 9. Стан пілотної та production-готовності

### 9.1. Пілот

Пілотний контур є допустимим лише за таких операційних умов:

- read-only user journey;
- admin/ingest закриті edge-рівнем;
- human-visible citations та adjudication reasons;
- аудит увімкнений і key material не зберігається в git;
- local-only model egress для public runtime;
- monitoring і escalation ladder активні;
- owner приймає перелік зовнішніх blocker'ів;
- будь-який current-source gate failure зупиняє rollout.

### 9.2. Production

Повний production release не дозволено. Мінімальні незакриті класи доказів:

| Предикат | Поточний статус | Що закриває |
|---|---|---|
| Independent external red-team | `UNKNOWN` | Signed report від незалежної сторони з structured findings і closure |
| Real PostgreSQL/RLS | `UNKNOWN` | Завершений source-bound adversarial suite у quiet window / production-like environment |
| Production-like load | `UNKNOWN` | Current-source load/soak із declared environment та SLO checks |
| Recovery drill | `UNKNOWN` | Current-source recovery report у production-like environment |
| Trusted hosted builder | `UNKNOWN` | Hosted CI provenance, source-bound і trusted signer |
| Trusted release signing | `OWNER_ACTION` | Owner-approved release manifest та trusted signature |
| Real-domain TEVV | `NOT_IN_RELEASE_PATH` | Preregistered observation/null-control ledgers, admissible corpus, human judgments |
| PEC production authority/canary | `NOT_IN_RELEASE_PATH` | Exact hosted cohort/revision attestations |

### 9.3. Rollback

Rollback unit:

- source: останній відомий green canonical commit;
- web: попередній successful Pages artifact;
- public API: systemd unit + edge image/config pair;
- Funnel: dedicated `8443` binding;
- evidence: не переноситься назад автоматично; для rollback source потрібен його власний
  source-bound evidence set.

## 10. Відкриті ризики, зовнішні залежності та обмеження тверджень

| ID | Ризик | Вплив | Власник / умова закриття |
|---|---|---|---|
| R-01 | 19 named gate-closure exemptions | Частина verification targets не є автоматичною в entry points | Інженерний backlog; кожне видалення повинно робити gap executable |
| R-02 | `span-hygiene=89` accepted red | Markup-bearing spans можуть погіршити citation quality | Re-extraction або exclusion from citation; ratchet ceiling не піднімати |
| R-03 | Trusted signer registries порожні | Production assurance verify структурно не може авторизувати release | Owner/governance додає Ed25519 identities |
| R-04 | Другий PostgreSQL evidence DB не вимірюється axis consistency | Різні corpus states можуть давати різні відповіді | Додати inventory+consistency gate після стабілізації паралельного rebuild |
| R-05 | Semantic retrieval decision не затверджено | Allied English source може outrank Ukrainian authority intent | Owner policy decision; не вмикати як суто технічний default |
| R-06 | 27/35 database tables раніше були порожні; learning subsystem має код і тести без production observations | Архітектурна поверхня більша за фактично активну | Product decision: activate, quarantine або remove; не називати learned behavior |
| R-07 | Screenshot pixel integrity не автоматизовано в чинному harness | Computed CSS не ловить compositing contamination | Окремий stable pixel-regression runner |
| R-08 | Host contention від паралельних projects | Long-running PostgreSQL gates можуть давати timeout UNKNOWN | Reserved quiet window / isolated runner |
| R-09 | Make `PY` path із пробілами | Manual custom interpreter path може завершитися 127 | Quote contract або заборонений path shape; project venv є operational workaround |

## 11. Матриця трасування «вимога → реалізація → доказ»

| Вимога | Реалізація | Доказ / негативний контроль | Статус |
|---|---|---|---|
| Один канонічний source state | Isolated worktree, reviewed ranges, explicit merge order | git SHAs, source digest, clean-room | `VERIFIED` |
| Public UI доступний, operator UI недоступний | nginx denial + derived operator asset closure | `verify_public_surface.py`; console 404 | `VERIFIED` |
| Public write operations fail closed | Edge route denial | live POST ingest -> 404; route mutants | `VERIFIED` |
| Public model не має зовнішнього egress | `KORPUS_MODEL_EGRESS_POSTURE=local_only` | env parity + public surface gate | `VERIFIED` |
| Audit key не в git | generated secret file, mode 0600, nonempty check | secret scan + unit/shell parity | `VERIFIED` |
| Claim semantics доходять до користувача | `claimBlocks(answer)` | web tests + payload rendering | `VERIFIED` |
| Global substrate точно `#000000` | token + body/root CSS contract | web static validator + browser computed style | `VERIFIED` |
| Фізична luminance не приписується CSS | Explicit claim boundary | document and test scope | `VERIFIED` як відсутність category error |
| Gate graph має замкнену дорогу | `verify_gate_closure.py` + registry | 4 negative classes | `VERIFIED` |
| Mutation probe не змінює live source | copy sandbox + signal handling | forced termination experiment | `VERIFIED` |
| Evidence routes current and reciprocal | route predicate + 30-day bound | M723–M725; 17 tests | `VERIFIED` |
| Runtime image не містить відомих fixable HIGH/CRITICAL | explicit PCRE2 security update | Trivy current local image, CI confirmation pending | `VERIFIED_LOCAL` |
| Runtime definition змінює evidence identity | `apps/api` digest surface | behavioral tests + M726 | `VERIFIED` |
| Production authorization не самопроголошується | hard predicates + trusted signer controls | `production_authorized=false` | `VERIFIED` |

## 12. Реєстр комітів сесії

### 12.1. Phase III — поточна production/pilot readiness робота

| SHA | Зміст |
|---|---|
| `0e5459bb94f8448afff60941cb2fb4bf5b488d15` | Замкнути чистий check і локальне security evidence |
| `d476a25c8321fe1779cf562b60604f021fdb9f78` | Усунути гонку реконсиляції audit anchor |
| `cebcab81f09614ce88bdd96ff4a2460cc74c53df` | Назвати сильніші CI-форми локальних gates |
| `268602d6f50ad1eb12d70139c594f0d31a0b7020` | Не успадковувати чужі виміри в пакет власника |
| `18b950d5bb97254b3c61f94c5755bb6a4010e297` | Дочекатися стабільного PostgreSQL перед coverage |
| `d653054818aa56e1c18e6c3c6eb62e5234643309` | Зберігати tracked receipts під час sharded regression |
| `49f79654631afdc1a1e2d3f2336f2578df486499` | Прив'язати scanner evidence до поточного дерева |
| `087dae13726efcd98a8b4d1f720837b50c7d486b` | Ізолювати відновлення public Funnel на 8443 |
| `1f3d0122ad6d10cae12937fb73ff71ca488d933b` | Закрити прострочені прогалини доступу до джерел |
| `f36a8e92e158b2745639a4139e1088bc2d07bef9` | Закрити fixable HIGH CVE у runtime image |
| `b111a168b5f09e7d93bf9ab64bd613098e5c3bcf` | Прив'язати runtime definition API до evidence digest |

### 12.2. Попередні фази

Повний machine-readable перелік відтворюється командами:

```bash
git log --format='%H%x09%s' 8659cda^..eac3fe9
git log --format='%H%x09%s' eac3fe9..9c913d2
git log --format='%H%x09%s' f37b6e64..b111a168
```

## 13. Остаточна диспозиція

### 13.1. Підтверджено

- Software architecture, public edge і web UI мають виконувані fail-closed controls.
- Zero-black substrate реалізовано як цифровий CSS-контракт без фізичних перебільшень.
- Персональні/операторські функції відокремлені від публічного user surface.
- Evidence chain розрізняє source scope, full tracked tree, environment class та
  external attestation.
- Негативні результати збережені: вони не перетворені на PASS через timeout, skip,
  aggregate verdict або manual waiver.
- Виявлені fixable container CVE усунені; provenance boundary розширено до runtime files.

### 13.2. Не підтверджено

- Повна production authorization.
- Незалежність red-team/TEVV.
- Production-like PostgreSQL, load і recovery на поточному кандидатові.
- Trusted hosted builder та owner release signature.
- Фізичні характеристики дисплея.

### 13.3. Управлінський запис

Рекомендація: допустити обмежений supervised read-only pilot після current-source
verification, canonical merge, deployment smoke і явного прийняття owner'ом зовнішніх
blocker'ів. Не називати цей стан повним production release.

Поле погодження власника:

```text
Рішення: PENDING
Особа:   PENDING
Дата:    PENDING
Підпис:  PENDING
```

## Додаток A. Машиночитні докази

| Артефакт | Предмет |
|---|---|
| `SOURCE_MANIFEST.json` | Повний source package manifest |
| `reports/CURRENT_TRUTH_VERIFICATION.json` | Current-truth admission |
| `reports/EXECUTABLE_EVIDENCE_INDEX_CURRENT.json` | Index виконуваних evidence artifacts |
| `reports/MUTATION_FULL_CATALOGUE_CURRENT.json` | Повний mutation verdict |
| `reports/PRODUCTION_HARD_PREDICATES.json` | Software/external production predicates |
| `reports/closure/CLEAN_ROOM_REPRODUCTION.json` | Remote-source clean-room reproduction |
| `reports/regression/FULL_REGRESSION_CURRENT.json` | Full sharded regression |
| `reports/release/v0.9.7/final/BLOCKER_REGISTRY.json` | Blocker registry |
| `reports/release/v0.9.7/final/CLAIM_LEDGER.json` | Claim-to-evidence ledger |
| `var/production/*-gate.json` | Production gate outputs |
| `var/security/*` | Scanner outputs та markers |

## Додаток B. Негативні результати та виправлені хибні припущення

1. Код завершення reload не доводить застосований network state.
2. Cache не був причиною mypy failure; початкове пояснення відкликано після
   differential test.
3. Тест, що змінює два незалежні дефекти, не локалізує жоден із них.
4. Aggregate verdict не доводить кожен predicate.
5. `finally` не є гарантією відновлення після process signal.
6. Idempotent command success не доводить відновлення endpoint.
7. Stale evidence є коректною відмовою, а не flake.
8. `max` не є правильним merge operator для decreasing ratchet.
9. Наявність environment variable не доводить usability її serialized value.
10. Successful security scan попереднього source digest не переноситься на змінений
    runtime image.
11. Timeout під resource contention — `UNKNOWN`, не `FAIL` і не `PASS`.
12. Зміна Dockerfile без зміни evidence digest була refutation provenance boundary;
    boundary виправлено й захищено behavioral negative control.
