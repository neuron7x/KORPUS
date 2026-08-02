# Agent definitions

Agents are narrow policies over shared retrieval and audit infrastructure. They do not
own authorization, source precedence, or safety rules; those remain deterministic
domain code.

Initial roles:

- `router`: selects domain/corpus and asks clarifying questions;
- `researcher`: produces evidence-bound answers;
- `instructor`: drafts curricula and assessments from approved objectives;
- `document_assistant`: fills versioned administrative templates;
- `citation_verifier`: checks claim-to-evidence coverage;
- `corpus_curator`: proposes metadata only; cannot approve its own proposal.

Adding multiple autonomous agents is not a quality feature. Use parallel agents only
when evals show independent decomposition improves an outcome enough to justify cost,
latency and tracing complexity.

