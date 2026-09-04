# Capability Model

## Effect classes

| Class | Meaning | Default |
|---|---|---|
| `READ_LOCAL` | authorized local read | deny until mapped |
| `READ_REMOTE` | outbound remote read | deny until policy + egress + contract pass |
| `WRITE_REMOTE` | external state mutation | explicit effect auth + idempotency |
| `TRANSACTIONAL_SIDE_EFFECT` | consequential workflow/message/payment/deploy-like effect | strongest guard + receipt + reconciliation |
| `PRIVILEGED_ADMIN` | administrative/configuration mutation | not general agent discovery |

## Lifecycle

```text
DISCOVERED_UNTRUSTED -> DECLARED -> VALIDATED -> ENABLED
                                      |            |
                                      v            v
                                  QUARANTINED <- DISABLED
                                      |
                                      v
                                    RETIRED
```

A remote discovery cannot directly create `ENABLED`.

## CapabilitySpec must identify

- stable logical id and semantic version;
- local approved description;
- provider type;
- adapter id/version;
- effect class;
- input/output schema identities;
- authorization action/resource mapper;
- data sensitivity/egress class;
- evidence profile;
- timeout/retry;
- idempotency rule;
- audit/observability rule;
- lifecycle state.

## Exact resolution

A provider rename, case fold, fuzzy match or version fallback must never convert one
capability into another. Production execution binds an exact version before authorization.
