# KORPUS v0.9.7 — Interface & Component Map

| Boundary | Producer | Consumer | Authority | Failure behavior |
|---|---|---|---|---|
| Release identity | release contract | API/web/receipts/package | authoritative | mismatch rejected |
| OpenAPI | API | web transport/clients | authoritative protocol | unknown method/path rejected |
| Client bootstrap | API policy/settings | routes/components | server-authority projection | component/route withheld |
| Auth + tenancy | backend policy | protected use cases | authoritative | refusal |
| Retrieval evidence | repository/retrieval | answer path | evidence input | abstain/refuse |
| Audit | application | verifier/operator | evidence | foreign/missing lineage rejected |
| Hard predicates | production reports | final authorization | authoritative gate | fail closed |
| UI navigation | bootstrap + route registry | browser | projection only | hidden/disabled |

## User surfaces
1. Consumer shell and authenticated bootstrap.
2. Chat/conversation workspace.
3. Corpus/document/span readers.
4. Offline-pack capability.
5. Billing/subscription.
6. Operator/admin console.
7. Audit and inference-status surfaces.

## Synchronization invariants
- Client release header comes from generated transport contract.
- Browser calls must exist in generated OpenAPI path+method contract, except explicitly hidden browser logout.
- Routes can require both permission and runtime capability.
- Profile/navigation consume one bootstrap snapshot.
- Backend enforcement remains authoritative if UI is bypassed.

## Current evidence
- Web Node tests: **146/146 PASS**.
- Browser E2E: **5/5 PASS**.
- Consumer transfer: **31,977 / 32,768 gzip bytes**.
- Accessibility static validation: PASS for 2 pages.
- Contrast validation: PASS for 3 surfaces.
