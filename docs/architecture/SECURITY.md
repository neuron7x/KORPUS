# Threat model and security architecture

## Protected assets

Source documents, access labels, user identity and role, queries, drafts, learning
history, model credentials, audit evidence, and infrastructure control planes.

## Primary threats

| Threat | Control |
|---|---|
| Indirect prompt injection in a document | Treat text as data; fixed tool policy; no document-triggered tools |
| Cross-corpus leakage | Pre-retrieval ABAC, separate stores/buckets, post-generation DLP test |
| Poisoned or forged source | Provenance, hash, quarantine, reviewer approval, authority class |
| Stale normative answer | Validity/supersession graph and scheduled review |
| Hallucinated citation | Citation IDs supplied by retriever; claim-level verifier |
| Malicious uploads | MIME sniffing, AV/CDR, sandboxed extraction, macro/executable quarantine |
| Account takeover | OIDC, phishing-resistant MFA for reviewers/admins, session rotation |
| Insider bulk extraction | least privilege, rate/volume anomalies, watermarking, immutable audit |
| Provider data exposure | per-corpus provider policy, minimization, regional/ZDR controls |
| Supply-chain compromise | lockfiles, SBOM, signed images, dependency scanning, provenance attestations |

## Authorization

Use RBAC for organizational roles and ABAC for document decisions:

```text
allow = role permits action
    AND user.clearance >= document.access_tier
    AND corpus.policy permits purpose
    AND document.review_state == approved
    AND document is currently valid
```

Authorization runs before vector search so forbidden chunks never enter model context.

## Secure delivery gates

Threat-model review, SAST, dependency scan, secret scan, container scan, contract tests,
access-control tests, prompt-injection suite, backup restore test, and incident-response
tabletop are required before production.

