# Risk Register

| ID | Risk | Severity | Treatment |
|---|---|---|---|
| R01 | parallel policy stack diverges | critical | P0; canonical policy only |
| R02 | generic gateway becomes ambient superuser | critical | P0; per-capability effect/resource auth |
| R03 | provider credential leak | critical | P0; secret isolation/redaction |
| R04 | duplicate side effect | critical | P0 when effects enabled; durable idempotency |
| R05 | MCP metadata injection | high | untrusted discovery boundary |
| R06 | schema drift widens effect/data | high | P0; digest pinning/quarantine |
| R07 | audit success without record | high | P0 where audit mandatory |
| R08 | architecture over-complexity | medium | modular-monolith first |
| R09 | unnecessary SDK/policy dependencies | medium | defer until measured need |
| R10 | infinite assurance expansion | high | frozen CGW-R001..R020 |
| R11 | future main creates proposal path | low | rebase/reconcile |
| R12 | protocol version drift | medium | version pinning/compatibility tests |
