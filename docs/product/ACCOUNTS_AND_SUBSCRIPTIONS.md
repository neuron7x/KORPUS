# Акаунти, підписки та розмови (ACT-001)

Статус на `2026-08-07`. Реліз `KORPUS_SYSTEM_v6.1.0`.
`production_authorized = false` — цей документ не змінює цього.

Чотири поняття, які тут навмисно **не** зливаються в одне:

| поняття | що це | хто вирішує |
|---|---|---|
| **identity** | що каже провайдер входу | зовнішній IdP |
| **account** | хто це *тут*; створюється при першому вході | ця система |
| **entitlement** | що оплачено | платіжний провайдер + план |
| **authorization** | що дозволено читати | `PolicyEngine` + entitlement-профіль |

Найдорожче злиття — двох останніх. Підписка **ніколи** не розширює допуск:
`EntitlementProjection.authorize_corpora` бере **перетин** із тим, що вже дозволив
`PolicyEngine`, а не об'єднання (`apps/api/src/korpus/application/paid_access.py:118`).

Друге: **розмова — це контекст, не доказ.** Попередня відповідь системи зберігається з
роллю `assistant` і не повертається в шлях пошуку. Система, яка подавала б власні
відповіді як джерело, за три ходи процитувала б сама себе з повним на вигляд списком
посилань.

---

## IMPLEMENTED

Реалізовано і працює в цьому дереві.

| що | де |
|---|---|
| Акаунт: створення при першому вході, ідемпотентно під конкурентністю | `application/accounts.py`, `infrastructure/tenancy_repository.py` |
| Вимкнення/увімкнення акаунта з причиною та подією аудиту | `AccountService.disable/enable` |
| Плани, підписки, стани `incomplete/active/past_due/canceled/expired` | `domain/tenancy.py` |
| Таблиця дозволених переходів; `canceled` і `expired` — термінальні | `ALLOWED_SUBSCRIPTION_TRANSITIONS` |
| Ідемпотентність подій білінгу за `(provider, provider_event_id)` — обмеженням БД | `migrations/versions/0012_tenancy.py` |
| Подія + зміна стану + запис аудиту **в одній транзакції** | `infrastructure/billing_repository.py:record_billing_event` |
| Стійкість до повтору: подія, старша за поточний стан, відхиляється | `application/subscriptions.py` |
| HMAC-верифікація вебхука над **сирими байтами** | `infrastructure/deterministic_billing.py` |
| Проєкція entitlement (перетин, не об'єднання) | `application/paid_access.py` |
| Розмови та повідомлення; власність — у самому SQL-запиті | `infrastructure/conversation_repository.py` |
| Відмова за неактивною підпискою **до** пошуку | `api/routes_tenancy.py::ask_within_conversation` |
| `ModelEgressPolicy`: `external_allowed` / `local_only` / `model_disabled` | `application/egress.py` |
| API: `/v1/account`, `/v1/plans`, `/v1/subscription`, `/v1/conversations*`, `/v1/billing/webhook` | `api/routes_tenancy.py`, `api/routes_billing.py` |
| Міграція `0012_tenancy` — тільки додає таблиці, корпус не чіпає | `migrations/versions/0012_tenancy.py` |

## TESTED

Виконано, не задекларовано. Числа — з прогону `2026-08-07`.

| властивість | тест |
|---|---|
| Перший вхід створює рівно один акаунт (6 паралельних входів) | `test_account_domain.py::test_concurrent_first_logins_converge_on_one_account` |
| Claims IdP із `corpora`/`clearance`/`roles` **відхиляються**, не фільтруються | `test_account_domain.py::test_identity_claims_carrying_authorization_are_refused_not_filtered` |
| Вимкнений акаунт не проходить нікуди | `test_tenancy_api.py::test_a_disabled_account_is_refused_everywhere` |
| Повторна доставка події не змінює нічого; 4 паралельні — застосовується одна | `test_billing_events.py` |
| Непідписана / підроблена / зіпсована подія — відмова, стан не рухається | `test_billing_events.py`, `test_tenancy_threats.py::test_t01_*` |
| `canceled → active` неможливо | `test_billing_events.py::test_a_canceled_subscription_cannot_be_reactivated` |
| Збій запису лишає нуль напів-застосованих подій; повтор потім спрацьовує | `test_billing_events.py::test_a_storage_failure_leaves_no_half_applied_event` |
| План не може дати корпус, якого немає в identity | `test_entitlement_gate.py::test_a_plan_cannot_grant_a_corpus_the_identity_does_not_hold` |
| `past_due` не платить ні за що (без неявного grace-періоду) | `test_entitlement_gate.py::test_a_past_due_subscription_pays_for_nothing` |
| Прострочений період перестає платити без жодної події | `test_entitlement_gate.py::test_an_expired_period_stops_paying_*` |
| Чужа розмова недосяжна за id; 404 однаковий для чужої та неіснуючої | `test_conversations.py`, `test_tenancy_threats.py::test_t06_*`, `t07` |
| Відмова за оплатою настає **до** `execute` (лічильник викликів = 0) | `test_tenancy_api.py::test_an_inactive_subscription_is_refused_before_retrieval_runs` |
| `model_disabled` не пускає навіть на `127.0.0.1` | `test_model_egress.py::test_model_disabled_refuses_even_a_local_endpoint` |
| Міграція з `0011` зберігає корпус; downgrade працює | `test_tenancy_migration.py` |
| Аудит не містить тіла вебхука, e-mail, секрету | `test_tenancy_audit_events.py::test_no_audit_payload_carries_a_secret_*` |
| 12 названих класів загроз — кожен зі своїм тестом | `test_tenancy_threats.py` |

Мутаційний каталог: **221 мутант, 221 вбито** (`var/mutation-report.json`), з них 14 —
ACT-001 (`M130`–`M143`). Два з них пережили перший прогін і показали справжні прогалини:
`past_due` тестувався лише через `incomplete`, а `model_disabled` — лише проти
вендорського URL. Обидві прогалини закриті тестами, а не переписуванням мутанта.

## EXTERNAL_DEPENDENCY

Зроблено все, що можна зробити кодом. Решта — поза цим репозиторієм.

| id | що лишається | чому не тут |
|---|---|---|
| `SUP-BILLING-001` | Адаптер справжнього платіжного провайдера: його схема підпису, його словник подій, його облікові дані | Немає акаунта провайдера. Вигадати ключі означало б закомітити те, чого не існує, і схему підпису, яку ніхто не перевіряв проти реального вендора. `BillingProvider` — це шов, у який такий адаптер стає без змін решти |
| `SUP-BILLING-002` | Юридичне: оферта, повернення коштів, податки, ПДВ | Не інженерне питання |
| `INF-003` … `SUP-007` | Дев'ять зовнішніх боргів релізу v6.0.0 | Не змінені цим актом; див. `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json` |

`DeterministicBillingProvider` — не заглушка: він автентифікує вебхук HMAC над сирими
байтами і відхиляє все зіпсоване, тобто ті самі шляхи коду (переходи, ідемпотентність,
аудит), якими піде вендорський адаптер. Він **не знімає грошей**.

## NOT_IMPLEMENTED

Свідомо не зроблено.

* **Checkout / платіжна форма.** Немає провайдера — немає сторінки оплати.
  `POST /v1/subscription` створює `incomplete` і не може створити `active` жодним тілом
  запиту.
* **Проксі-роль для команди.** Один акаунт = один `auth_subject`. Спільних акаунтів,
  організацій і місць у команді немає.
* **Автоматичне повторне виставлення рахунку.** Продовження приходить подією провайдера;
  нічого тут не планує списань.
* **Видалення акаунта на вимогу.** `purge_account` стирає історію розмов і викликається
  зі шляху зберігання, але кнопки «видалити мене» в API немає — акаунт із подіями аудиту
  не можна просто прибрати, і хто це вирішує, ще не визначено.
* **Кеш entitlement.** Проєкція рахується щоразу. Кешоване право — це рішення, ухвалене в
  момент, який минув.

---

## Налаштування

| змінна | усталено | що робить |
|---|---|---|
| `KORPUS_SUBSCRIPTION_REQUIRED` | `false` | Вмикає перетин із оплаченим. **Вимкнено**: розгортання, яке нічого не продавало, має відповідати рівно як у v6.0.0 |
| `KORPUS_FREE_CORPORA` | порожньо | Корпуси, які не потребують підписки, через кому |
| `KORPUS_BILLING_WEBHOOK_SECRET` | порожньо | Без нього вебхук не обслуговується взагалі. Ендпоінт, що приймає непідписані події, гірший за відсутній |
| `KORPUS_MODEL_EGRESS_POSTURE` | `external_allowed` | `local_only` — модель лише на приватній адресі; `model_disabled` — жодної моделі |

Усталені значення повністю зберігають поведінку v6.0.0. Це перевірено тестом
`test_with_the_gate_off_the_answer_is_the_policy_engines_own`, а не заявлено коментарем.
