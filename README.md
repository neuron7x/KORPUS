# KORPUS v0.9.7

KORPUS is a bounded-evidence, multi-tenant knowledge/inference system with fail-closed authorization, evidence-bound answers, abstention, auditability and explicit production admission predicates.

**Authoritative start:** `README_FIRST.md`.

## Private laptop pilot

For one owner and three to five invited readers, start with the dedicated local-storage
profile and its real PostgreSQL/worker/ClamAV qualification:

```sh
make api-install
make compose-pilot-smoke
make pilot-up
```

The browser opens at `http://127.0.0.1:3000`. Follow
[the private pilot runbook](docs/operations/PRIVATE_PILOT.md) to issue scoped JWT
sessions, upload/review a corpus and configure an exact private HTTPS hostname.
The persistent project is `korpus-pilot`; it uses local object/quarantine volumes
and does not reuse the legacy S3 project's data. This qualification does not claim
S3, WORM, owner-host access, public HTTPS, load or recovery evidence.

| Surface | Where the current value is read |
|---|---|
| Behavioral source | `compute_source_digest` над `EVIDENCE_SOURCE_PATHS` (`scope=evidence_paths`) |
| Regression | `reports/PYTEST_REPORT.xml` · шардів `REGRESSION_SHARDS` у `Makefile` |
| Mutation | `reports/MUTATION_REPORT.json` — гейт вимагає `killed == valid_mutants == len(MUTANTS)` |
| Web | `make web-build` |
| Determinism | `make determinism-gate` |
| Operational engineering gate | `var/operational-gate.json` |
| Hard predicates | `reports/PRODUCTION_HARD_PREDICATES.json` |
| Production authorization | **false**. Раніше тут стояло «`production_satisfied` дорівнює нулю за побудовою, доки порожні реєстри підписантів» — виміряно 06.09.2026 як хибне: профіль вилучає атестаційні перевірки для шести предикатів, і закритих шість при підлозі шість. Поточне число має виробника (`make production-hard-predicates`) і живе в `reports/PRODUCTION_HARD_PREDICATES.json`; авторизація лишається `false` з інших підстав, перелічених там |

Одна команда, що дає всі ці числа разом і відмовляється міряти брудне або рухоме
дерево: `make release-verify`.

> **ВИПРАВЛЕНО 02.09.2026.** Числа в цьому блоці були заморожені 23.08.2026 і подавались
> як поточний стан. Виміряно: тестів **3814**, не 2345; мутантів **574**, не 349; шардів
> регресії **24**, не 64; дайджест джерела за одну годину прийняв три різні значення.
> Тому числа, що рухаються, тут більше не вкарбовані — названі ЛИШЕ джерела, бо друге
> оголошення рухомого числа розходиться мовчки, і саме так воно й розійшлось.


Repository roots: `apps/`, `packages/`, `contracts/`, `config/`, `evals/`, `deploy/`, `infra/`, `scripts/`, `docs/`, `handoff/`, `reports/`.
