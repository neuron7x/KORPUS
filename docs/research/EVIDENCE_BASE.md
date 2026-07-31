# Engineering evidence base

Reviewed: 2026-07-31. This is a decision bibliography, not an appeal to celebrity.
Named researchers motivate hypotheses; specifications, reproducible evaluations and
operational evidence justify implementation.

## Adopted foundations

- NIST AI RMF 1.0 and the Generative AI Profile organize risk work as govern, map,
  measure and manage across the lifecycle. We encode this through ownership, the risk
  register, eval gates and incident protocols.
- NIST SP 800-218A extends secure software development practices to generative AI. We
  treat models, prompts, datasets and retrieval indexes as versioned supply-chain
  components.
- CISA Secure by Design makes customer safety a product responsibility. Defaults are
  least privilege, abstention and execution-disabled ingestion.
- OWASP guidance on LLM applications informs prompt-injection, sensitive-disclosure,
  supply-chain, poisoning, excessive-agency and vector/embedding controls.
- OpenAI Responses API guidance supports structured tool use and explicit output
  contracts. Its file-search evaluation example separates retrieval precision/recall,
  MRR and MAP; the architecture keeps these distinct from answer faithfulness.
- Contemporary RAG evaluation literature decomposes quality into retrieval,
  relevance/completeness, claim-level faithfulness, and judge calibration. We do not
  publish a single opaque "accuracy" number.

## First-principles interpretation

The useful lesson associated with research-driven builders such as Andrej Karpathy is
to understand the full stack, keep systems inspectable, establish simple baselines,
and earn complexity through measured failure. The useful lesson associated with Ilya
Sutskever's research career is that representation and generalization matter, but
capability does not remove the need for alignment, supervision and evaluation.

Neither person's reputation is a product requirement. For this system:

- a deterministic keyword baseline precedes dense retrieval;
- a single answer orchestrator precedes a multi-agent graph;
- measured eval failures precede prompt/model tuning;
- retrieved text never becomes trusted instruction;
- human corpus review remains authoritative.

## Primary sources

1. NIST, AI Risk Management Framework 1.0: https://doi.org/10.6028/NIST.AI.100-1
2. NIST, Generative AI Profile: https://doi.org/10.6028/NIST.AI.600-1
3. NIST, Secure Software Development Practices for Generative AI and Dual-Use
   Foundation Models (SP 800-218A): https://doi.org/10.6028/NIST.SP.800-218A
4. NIST AI Resource Center / TEVV: https://airc.nist.gov/
5. CISA, Product Security Bad Practices (2025 update):
   https://www.cisa.gov/news-events/alerts/2025/01/17/cisa-and-fbi-release-updated-guidance-product-security-bad-practices
6. OWASP Top 10 for LLM Applications: https://owasp.org/www-project-top-10-for-large-language-model-applications/
7. OpenAI Responses API: https://developers.openai.com/api/reference/resources/responses/
8. OpenAI file-search evaluation cookbook:
   https://developers.openai.com/cookbook/examples/file_search_responses
9. OpenAI data controls: https://developers.openai.com/api/docs/guides/your-data
10. RAG evaluation survey (2025): https://arxiv.org/abs/2504.14891
11. RAGVUE diagnostic evaluation (2026): https://arxiv.org/abs/2601.04196

ArXiv papers are research inputs, not standards. Claims must be reproduced on the
project's own corpus and users before adoption.

