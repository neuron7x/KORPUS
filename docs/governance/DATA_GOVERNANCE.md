# Data governance

## Corpus classes

| Class | Examples | Serving policy |
|---|---|---|
| Public verified | official public acts and openly licensed sources | approved users/products |
| Licensed/permissioned | explicit reuse permission | license-specific controls |
| Internal reviewed | colleague-provided internal material with authority | authenticated purpose-bound use |
| Restricted | formally controlled material | separate environment; not MVP |
| Adversary/historical | analysis and old doctrine | labeled; never normative by default |
| Rejected | unknown rights, malware, unreliable or prohibited | no indexing |

Purchase or possession is not treated as a machine-readable reuse permission. Rights
basis is recorded per version. The repository stores no source documents.

## Retention

Define retention per data class. Minimize query and identity logs; separate operational
telemetry from content; support legal hold and verified deletion. Revocation removes a
document from retrieval immediately and triggers affected-answer analysis.

## Governance roles

Product owner, corpus steward, domain reviewer, security owner, privacy owner,
reliability owner, and incident commander. One person may hold multiple roles in an
MVP, but decisions and conflicts remain explicit.

