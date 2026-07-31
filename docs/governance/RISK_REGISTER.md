# Risk register

| ID | Failure | Kill predicate | Owner | Gate |
|---|---|---|---|---|
| R-001 | restricted data leakage | any inaccessible marker enters candidate memory, response, citation, log, metric or release hash | security | release block |
| R-002 | stale document treated as current | superseded/rescinded version cited outside valid `as_of` interval | corpus governance | release block |
| R-003 | unsupported answer | any emitted claim lacks exact evidence offsets and valid quote hash | retrieval | release block |
| R-004 | poisoned source instruction | source/query instruction changes policy or appears as answer | security | release block |
| R-005 | unverifiable audit | sequence, predecessor, HMAC, DB head or external anchor disagree | operations | incident |
| R-006 | anchor crash window | committed event lacks recoverable outbox checkpoint | operations | readiness block |
| R-007 | false authority | source approved without issuer evidence and appointed reviewer | domain owner | corpus block |
| R-008 | agent supply-chain compromise | unreviewed agent change reaches protected `main` | DevSecOps | release block |
| R-009 | corpus rights violation | no lawful basis for ingestion, processing, citation or distribution | legal owner | ingestion block |
| R-010 | OCR semantic corruption | critical field differs from reviewed gold transcription | corpus QA | document block |
| R-011 | benchmark overfit | frozen cases pass while blind production cases fail | assurance | deployment block |
| R-012 | unbounded retrieval | query path scans the complete accessible corpus in application memory | platform | release block |
| R-013 | index recall loss | candidate index excludes required evidence under target workload | retrieval | calibration block |
| R-014 | schema drift | runtime metadata and migrated production schema differ | platform | deployment block |
| R-015 | false formal assurance | tests are presented as state authorization or accreditation | accountable owner | deployment block |
