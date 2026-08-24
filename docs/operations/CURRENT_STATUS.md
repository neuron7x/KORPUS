# КОРПУС — поточний статус

> Згенеровано з реєстрів `scripts/generate_status.py`. Не редагувати вручну —
> `test_status_document_matches_the_registers.py` впаде, якщо цифри розійдуться
> з реєстрами. Це той документ, по якому ухвалюють рішення про допуск.

**production_authorized:** `false`

## Борг, який закривається лише поза кодом

**9** зовнішніх боргів. Жоден не закривається кодом у цьому
дереві — кожен потребує людини, підпису, інфраструктури або незалежної перевірки.

| id | серйозність | що потрібно |
|---|---|---|
| GOV-001 | P0 | Призначити system owner, data owner, security owner; створити authorization pack |
| GOV-004 | P0 | Незалежний code review, API/cloud pentest, AI/RAG red-team, corpus poisoning exe |
| GOV-006 | P0 | Провести rights clearance; заборонити external egress для неочищених класів. |
| INF-003 | P0 | TLS 1.2/1.3 ingress, mTLS/service mesh або equivalent, certificate rotation. |
| INF-004 | P0 | Define availability class; HA Postgres, object replication, redundant API, PITR. |
| INF-006 | P0 | Vault/KMS/HSM, workload identity, envelope encryption, rotation/revocation drill |
| RAG-003 | P0 | Подвійна незалежна розмітка, adjudication, reviewer qualifications, ambiguity la |
| SRE-002 | P0 | On-call model, severity matrix, paging, tabletop + technical game days. |
| SUP-007 | P1 | Export GitLab settings evidence; 2-person review; protected tags; isolated runne |

Локально помʼякшених (код зробив усе, що міг): **66**.

## Підстави, чому допуск не надано

**5** відкритих підстав. Кожна — рішення людини, не коду.

| підстава | що це |
|---|---|
| 2.5 | Автентифікація не пройшла незалежної оцінки |
| 2.6 | Немає TEVV на справжньому корпусі |
| 2.7 | Питання класифікації та прав не вирішені |
| 2.9 | Цілі відновлення (RTO/RPO) не оголошені |
| superseded-never-current | Чи знімає завантаження чернетки наступника чинність попередньої версії |

## Що доведено кодом

Тести, покриття, мутація, цілісність аудиту, деградація під відмовою залежностей —
усе виміряно запуском і лежить у `reports/`. Це доводить, що система робить те, що
заявлено; воно **не** доводить дозволу на продакшн, прав на корпус, незалежної
стійкості до атак чи оголошених цілей відновлення. Ці рядки — вище.

