# Inference operation

KORPUS does not delegate factual authority to a language model. Optional inference has
only two bounded capabilities:

1. **query planner** — suggests short search phrases; the original question is always
   searched first and every suggestion passes `admissible_variant`;
2. **answer composer** — may reorder already admitted extractive sentences and propose
   one opening line; `compose_answer` checks permutation and vocabulary constraints.

Claims, citations, authority ranking, temporal validity, contradiction handling,
clearance and corpus access remain deterministic KORPUS controls.

## Executor lifecycle and failure isolation

Planner and composer adapters are constructed once per API-process lifespan, not once
per request. Each adapter owns a thread-safe circuit breaker: three consecutive
transport or response failures open the circuit for 15 seconds, so later requests use
the deterministic extractive path without paying another provider timeout. A half-open
probe is single-flight; success closes the circuit and resets the failure count. The
circuit never grants evidence authority and never converts malformed model output into
an answer.

## OpenAI Responses API

Set the provider explicitly and provide an explicit API model name:

```dotenv
KORPUS_QUERY_PLANNER_PROVIDER=openai
KORPUS_QUERY_PLANNER_MODEL=gpt-5.6-sol
KORPUS_QUERY_PLANNER_API_KEY_FILE=/run/secrets/openai_api_key
KORPUS_QUERY_PLANNER_BASE_URL=
KORPUS_QUERY_PLANNER_ENABLED=true
KORPUS_ANSWER_COMPOSER_ENABLED=true
KORPUS_MODEL_EGRESS_POSTURE=external_allowed
KORPUS_MODEL_EGRESS_MAX_TIER=public
```

An empty base URL selects `https://api.openai.com`. The OpenAI adapter calls
`POST /v1/responses` server-side and sets `store=false` on every request. API keys are
never browser configuration.

Do **not** raise `MODEL_EGRESS_MAX_TIER` merely to make inference work. If evidence is
above the configured ceiling, KORPUS keeps the extractive answer and refuses composition.
`controlled` and `isolated` environments refuse third-party planner/composer use.

## Live smoke test

After deploying the secret and model configuration:

```bash
PYTHONPATH=apps/api/src python scripts/inference_smoke.py
```

The smoke test uses synthetic public sentences only. It proves transport + parsing +
admission without sending production corpus bytes. `PASS` means the configured optional
model seam is reachable; it does **not** certify retrieval quality or production TEVV.
