# ACT-006 — Inference Surface & Evidence Execution Loop

Target candidate: `v6.7.0`
Base HEAD: `7b6252789b9083396cb8cd6fbda87b3398589857`

## Intent

Shorten and make observable the path `question → retrieval → evidence gate → optional model
assistance → admitted extractive claim/citation → answer/refusal → audit` without granting a
model factual authority.

## Implemented

- Provider-neutral model assistance contract shared by Anthropic and OpenAI adapters.
- OpenAI Responses API transport at `/v1/responses`; every request sets `store=false`.
- New deployments default to the disabled OpenAI provider with `gpt-5.6-sol`; enabling still requires an explicit key and feature flags.
- OpenAI planner/composer requests use strict `json_schema` Structured Outputs rather than relying on prompt-only JSON formatting.
- API keys remain server-side and may be sourced from a secret file.
- Provider/model/base URL are deployment configuration rather than application-domain state.
- Egress posture is checked before network transport.
- OpenAI malformed output contributes no query variants and no composition.
- `MODEL_DISABLED` refuses before transport.
- Query planner may only suggest retrieval phrases.
- Answer composer may only order already admitted extractive sentences and propose a bounded
  opening; existing deterministic admission remains downstream.
- Authenticated `/v1/inference/status` exposes enabled/provider/model/posture/authority without
  exposing key, secret path or base URL.
- Consumer UI renders `MODEL ASSIST · OFF/OPENAI/ANTHROPIC/UNKNOWN` and retains the explicit
  statement that the model does not create facts.
- Corpus-free `scripts/inference_smoke.py` exercises configured composition without production
  corpus material.
- OpenAPI canonicalization now removes only HTTP-equivalent UploadFile schema-generator noise,
  preventing local FastAPI/Pydantic encoding drift from masking semantic API changes.
- Release identity converged to `v6.7.0` without a git tag.

## Security boundary

GOV-006 gates corpus material sent to an external composer. KORPUS cannot infer a trustworthy
classification for arbitrary user-entered question text, so an enabled external query planner
necessarily sends the question to its provider. This is documented explicitly rather than
misrepresented as tier-classified query egress. Controlled/isolated deployments still refuse
third-party model integrations.

`store=false` is a provider request control, not a KORPUS claim of Zero Data Retention.

## Verification on current working tree

- Backend ACT-006 + auth/answer/tenancy/API contract targeted suite: 142/142 PASS.
- Web mutation/interaction suite: first 120/122 PASS in the bounded full run; final two negative
  controls separately PASS (LiqPay CSP and server-derived inference status), yielding 122/122
  current-tree cases with no assertion failure.
- Web lint: PASS.
- Web typecheck gate: PASS.
- Web build: PASS.
- Consumer transfer: 29,045 gzip bytes under 32 KiB ceiling.
- Design system: 39 tokens / 10 component contracts PASS.
- Internal import cycles: 0.
- Module budget: 183 modules / 0 unbudgeted / 0 violations.
- OpenAPI contract: PASS after semantic-only ACT-006 delta.
- Repository requirements: 103/103 PASS; 99/99 audit findings classified.
- Release identity parity: PASS without requiring a git tag.

## External inference limitation

No OpenAI/API credential is present in this execution environment. Therefore no live vendor
request is claimed. Transport behavior is verified through mocked HTTP boundaries; live model
latency, provider availability, quota, billing and exact enabled model ID remain deployment
checks.

## Promotion

`production_authorized=false` remains unchanged. No `v6.7.0` git tag is created. Fresh exact-lock
full assurance, live IdP/payment dependencies, live external inference and production operational
gates remain separate promotion requirements.
