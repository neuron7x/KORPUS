# Security architecture

## Threats explicitly covered by executable tests

- client attempts to select a higher access tier;
- request for an unassigned corpus;
- retrieval of an inaccessible restricted document;
- use of quarantined or unapproved content;
- prompt-injection text in a query;
- modification of an audit event;
- duplicate upload ambiguity;
- approval of a source with unknown authority.

## Controls

- Production startup rejects development authentication.
- Identity roles, clearance, and corpus assignments come from verified claims.
- Query bodies can narrow corpus scope but cannot widen it.
- Retrieval receives only pre-authorized, approved, temporally active candidates.
- Retrieved content is never concatenated into an executable system prompt.
- Source bytes are content-addressed by SHA-256.
- Document states follow an explicit transition graph.
- Audit events use canonical serialization and HMAC-SHA256 chaining.
- GitLab uses protected branches, CODEOWNERS, independent verification, secret scan, SBOM and dependency audit.

## Known limitations

The local implementation is not a certification claim. HMAC audit chaining detects database changes only while the key and trusted checkpoint remain uncompromised. Production requires external checkpoint anchoring or append-only/WORM storage. Antivirus, content-disarm-and-reconstruction, formal security profile, penetration test, authorization, SOC monitoring, HSM-backed keys, and incident ownership are deployment obligations.

## Agent egress policy

Codex and Claude Code receive synthetic fixtures only. Restricted source documents, production database dumps, JWT signing keys, audit keys, cloud credentials and personal data are forbidden in agent worktrees or prompts.
