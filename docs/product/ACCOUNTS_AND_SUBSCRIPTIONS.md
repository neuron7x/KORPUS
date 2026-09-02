# Акаунти, підписки та розмови (ACT-001)

Статус на `2026-08-09`. Candidate `KORPUS_SYSTEM_v6.7.0`.
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
| Provider-neutral event boundary + deterministic HMAC verifier для тестів | `infrastructure/deterministic_billing.py`, `application/subscriptions.py` |
| LiqPay client-server checkout: server-owned amount/currency, signed `data`, callback verification | `application/checkout.py`, `infrastructure/liqpay.py`, `api/routes_billing.py` |
| Deployment-owned sellable plan bootstrap; browser не задає ціну/валюту/corpora | `config.py`, `tenancy_composition.py` |
| Проєкція entitlement (перетин, не об'єднання) | `application/paid_access.py` |
| Розмови та повідомлення; власність — у самому SQL-запиті | `infrastructure/conversation_repository.py` |
| Вердикт зберігається з відповіддю (`answer_status`) — відмова, прочитана з історії, лишається відмовою | `migrations/versions/0013_message_verdict.py` |
| Веб-інтерфейс розмов: список, відновлення, архів, нова розмова | `apps/web/public/conversations.js`, `app.js` |
| Пагінація зі `has_more`: жоден список не обривається мовчки | `conversation_repository.py`, `ConversationPageView` |
| Обидва шляхи до відповіді — під однією межею одночасності | `api/answering.py` |
| Відмова за неактивною підпискою **до** пошуку | `api/routes_tenancy.py::ask_within_conversation` |
| `ModelEgressPolicy`: `external_allowed` / `local_only` / `model_disabled` | `application/egress.py` |
| API: `/v1/account`, `/v1/plans`, `/v1/subscription`, `/v1/billing/checkout`, `/v1/conversations*`; provider callbacks hidden from OpenAPI | `api/routes_tenancy.py`, `api/routes_billing.py` |
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
| Збережений вердикт повертається клієнту й рендериться як вердикт | `test_conversations.py`, `test_tenancy_api.py`, `apps/web/tests/validate_gate.test.mjs` |
| Заголовок, вік і екранування в списку розмов | `apps/web/tests/conversations.test.mjs` |
| Обрізаний список називає обрив; повний — мовчить | `test_conversations.py::test_a_truncated_list_says_it_was_truncated`, `test_an_exact_page_does_not_claim_there_is_more` |
| Перевірка ліміту читає 1 рядок, а не 500 | `test_conversations.py::test_the_message_limit_is_checked_without_reading_the_whole_conversation` |

Мутаційний каталог: **усі мутанти вбито** — гейт вимагає
`killed == valid_mutants == len(MUTANTS)` (`var/mutation-report.json`). Число тут
навмисно не вкарбоване: 02.09.2026 стояло «226 мутантів, 226 вбито», тоді як у
названому файлі було 574/574. З них 14 —
ACT-001 (`M130`–`M143`). Два з них пережили перший прогін і показали справжні прогалини:
`past_due` тестувався лише через `incomplete`, а `model_disabled` — лише проти
вендорського URL. Обидві прогалини закриті тестами, а не переписуванням мутанта.

## EXTERNAL_DEPENDENCY

Кодова межа реального платежу реалізована. Зовні репозиторію лишаються:

| id | що лишається | чому не тут |
|---|---|---|
| `SUP-BILLING-001` | Production LiqPay merchant account/keys + live callback drill | Реальні credentials та мережевий callback не можуть бути доведені локальним тестом |
| `SUP-BILLING-002` | Оферта, повернення коштів, податки/ПДВ | Юридична/операційна площина |
| `SUP-IDP-001` | Self-service sign-up policy selected OIDC provider | Реєстраційний UX/verification є властивістю зовнішнього IdP deployment |
| `INF-003` … `SUP-007` | Інші зовнішні production debts | Див. current closure/debt registers |

`DeterministicBillingProvider` лишається negative-control/test provider. Production checkout
використовує `LiqPayBillingProvider`; відсутні merchant keys означають відсутній checkout service,
а не симульовану оплату.

## NOT_IMPLEMENTED

Свідомо не зроблено.

* **Production-verified checkout.** Код LiqPay checkout/callback реалізований, але без реального merchant account та live callback drill production payment не оголошується перевіреним.
* **Проксі-роль для команди.** Один акаунт = один `auth_subject`. Спільних акаунтів,
  організацій і місць у команді немає.
* **Автоматичне повторне виставлення рахунку.** Продовження приходить подією провайдера;
  нічого тут не планує списань.
* **Видалення акаунта на вимогу.** `purge_account` стирає історію розмов і викликається
  зі шляху зберігання, але кнопки «видалити мене» в API немає — акаунт із подіями аудиту
  не можна просто прибрати, і хто це вирішує, ще не визначено.
* **Кеш entitlement.** Проєкція рахується щоразу. Кешоване право — це рішення, ухвалене в
  момент, який минув.
* **Картки цитат в історії.** Збережений хід несе текст відповіді дослівно й вердикт, але
  не картки цитат із хешами: вони належать тій відповіді й лишаються в журналі аудиту.
  Інтерфейс каже це прямо, а не лишає читача здогадуватися з їхньої відсутності.
* **Розмови на публічному краї.** Вимкнені: там одна read-only особа на всіх відвідувачів,
  тож розмова була б спільним зошитом.

---

## Налаштування

| змінна | усталено | що робить |
|---|---|---|
| `KORPUS_SUBSCRIPTION_REQUIRED` | `false` | Вмикає перетин із оплаченим. **Вимкнено**: розгортання, яке нічого не продавало, має відповідати рівно як у v6.0.0 |
| `KORPUS_FREE_CORPORA` | порожньо | Корпуси, які не потребують підписки, через кому |
| `KORPUS_BILLING_WEBHOOK_SECRET` | порожньо | Без нього вебхук не обслуговується взагалі. Ендпоінт, що приймає непідписані події, гірший за відсутній |
| `KORPUS_LIQPAY_PUBLIC_KEY` / private key | порожньо | Вмикають production LiqPay adapter тільки парою |
| `KORPUS_BILLING_PUBLIC_BASE_URL` | порожньо | HTTPS origin для callback/return URL |
| `KORPUS_BILLING_PLAN_CODE` + price/currency/interval/corpora | порожньо | Ідемпотентно матеріалізують server-owned sellable plan на startup |
| `KORPUS_MODEL_EGRESS_POSTURE` | `external_allowed` | `local_only` — модель лише на приватній адресі; `model_disabled` — жодної моделі |

Усталені значення повністю зберігають поведінку v6.0.0. Це перевірено тестом
`test_with_the_gate_off_the_answer_is_the_policy_engines_own`, а не заявлено коментарем.
