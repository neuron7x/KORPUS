# Incident response

## Severity 0

Restricted data exposure, authorization bypass, corrupted audit chain, signing-key compromise, or incorrect operational answer with material consequence.

Actions:

1. disable answer endpoint or affected corpus;
2. preserve logs, image digests, database snapshot and audit terminal hash;
3. revoke identity/provider credentials;
4. determine first affected corpus release and software commit;
5. notify accountable security and domain owners;
6. repair in a separate branch with a reproducing test;
7. re-run frozen and incident-specific evaluations;
8. restore only through an explicit authorization decision.


## Журнали: де вони і як їх читати

Виміряно 06.09.2026: слова `journalctl` не було в ЖОДНОМУ файлі дерева. Оператору ніде
не було сказано, що журнали взагалі існують — а це перше, куди він піде, коли `/ready`
мовчить. Відсутність інструкції дорожча за хибну: хибну він побачить і виправить,
відсутньої — ні.

Обидва процеси пілоту — це користувацькі юніти systemd, не контейнери:

```
systemctl --user status korpus-pilot-api.service      # приватний пілот, порт 8030
systemctl --user status korpus-public-api.service     # публічний loopback, порт 8000
journalctl --user -u korpus-pilot-api.service -n 200 --no-pager
journalctl --user -u korpus-pilot-api.service -f      # стежити далі
```

**Пастка з формою.** `--user -u <юніт>` і `--user-unit=<юніт>` — не те саме в усіх
версіях; якщо перша дає порожньо, спробуй другу, перш ніж вирішити, що записів немає.
Порожній вивід журналу НЕ означає, що сервіс мовчить: він так само може означати, що ти
питаєш не той журнал.

**Рестарт після зміни коду.** Процес тримає код, з яким стартував. Гейт
`topology_environment_class` це ловить і каже дослівно «процеси, старші за код» — але
лише під час виміру. Після будь-якої зміни джерела:

```
systemctl --user restart korpus-pilot-api.service korpus-public-api.service
```

Перезапускати треба ОБИДВА: вимір 05.09.2026 показав, що рестарт лише одного лишає
другий на старій ревізії, і клас середовища падає до `LOCAL_DEV` без жодного іншого
сліду.

## First five minutes, as commands

| symptom | command | then |
|---|---|---|
| Readers get 503 | `curl -s localhost:8000/ready \| python3 -m json.tool` | Виміряно 06.09.2026 на живому пілоті: з петлі знімок приходить ПОВНИЙ і БЕЗ токена — `database`, `schema_revision`, `expected_schema_revision`, `schema_current`, `audit_head_sequence`, `object_store`, `semantic_index`, `ready`. Попередня редакція цього рядка вимагала `Authorization: Bearer $METRICS_TOKEN`; такої змінної не існує ніде в дереві, і оператор о третій ночі шукав би її марно. Читай `schema_current` і `object_store` першими: розбіжність `schema_revision` з `expected_schema_revision` означає незастосовану міграцію, а не збій. |
| A compromised login | open the Accounts console → find by subject → disable, with a reason | the reason enters the audit chain; the account is refused everywhere next request |
| Ingestion stuck | `make audit-verify` then check for `ingestion.job_reaped` events | a crashed worker's jobs are reaped to dead_letter with a record |
| Suspected tampering | `make audit-verify` | `valid: false` names the first invalid sequence; do not restart, capture the anchor |

Disabling an account and reaping a stuck job both leave an audit event. If an action left
none, it did not happen — look again before assuming it did.
