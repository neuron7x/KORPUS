# Risk register

| ID | Failure | Kill predicate | Owner | Gate |
|---|---|---|---|---|
| R-001 | restricted data leakage | any inaccessible marker appears in response, citation, log or metric | security | release block |
| R-002 | stale document treated as current | superseded/rescinded version cited for an as-of query | corpus governance | release block |
| R-003 | unsupported answer | any answer claim lacks an immutable evidence span | retrieval | release block |
| R-004 | poisoned source instruction | retrieved text changes policy/tool behavior | security | release block |
| R-005 | unverifiable audit | chain validation fails or checkpoint absent | operations | incident |
| R-006 | false authority | source approved without appointed reviewer and issuer evidence | domain owner | corpus block |
| R-007 | agent supply-chain compromise | unreviewed agent change reaches protected main | DevSecOps | release block |
| R-008 | corpus rights violation | ingestion lacks lawful processing/distribution basis | legal owner | ingestion block |
| R-009 | OCR semantic corruption | critical field differs from gold transcription | corpus QA | document block |
| R-010 | formal authorization assumed from tests | deployment claims approval without external decision | accountable owner | deployment block |
