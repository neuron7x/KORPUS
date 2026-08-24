# KORPUS standards baseline — 2026-08-15

This document is a **design cross-reference, not a certification claim**. KORPUS does not claim compliance merely because its control vocabulary maps to a standard. A control is closed only by the repository's own executable evidence and, where required, independent assessment.

## Verified external baselines

| Standard / framework | Status used by KORPUS | Why it is referenced | Official source |
|---|---|---|---|
| NIST SP 800-218 SSDF 1.1 | Final | secure development lifecycle and vulnerability-prevention vocabulary | https://csrc.nist.gov/pubs/sp/800/218/final |
| NIST SP 800-218 Rev.1 / SSDF 1.2 | Initial Public Draft | tracked only as future-facing draft; **not** treated as final normative baseline | https://csrc.nist.gov/pubs/sp/800/218/r1/ipd |
| OWASP ASVS 5.0.0 | Stable | application-security verification taxonomy | https://owasp.org/www-project-application-security-verification-standard/ |
| SLSA 1.2 | Approved/current | source/build provenance and supply-chain assurance vocabulary | https://slsa.dev/spec/v1.2/ |
| NIST AI RMF 1.0 | Published; revision underway | Govern/Map/Measure/Manage framing for AI-system risk | https://www.nist.gov/itl/ai-risk-management-framework |

## Use policy

1. Requirements are referenced with an explicit version whenever identifiers are used.
2. A crosswalk row means “this KORPUS control is relevant to this external concern,” not “audited compliant.”
3. Draft standards may inform design but cannot silently replace a final baseline.
4. External requirements never weaken a stricter KORPUS invariant.
5. Production authorization remains conjunctive and evidence-bound even when a maturity score is high.

## 2026 engineering consequence

The practical baseline is: secure SDLC controls from final SSDF 1.1; web-application verification vocabulary from ASVS 5.0.0; artifact/source provenance concepts from approved SLSA 1.2; and AI risk-governance structure from AI RMF 1.0 while explicitly tracking that NIST is revising it. This avoids the common failure mode of citing a draft as if it were already a final standard.
