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

## Verification and governance layer

Added 2026-08-02. Every entry below was fetched and its title, authors and date
confirmed in the session that added it; the date in brackets is the arXiv or
publisher record, not a guess. Each entry names the design decision it underwrites.
An entry that underwrites nothing does not belong here.

### Agent design (primary lab sources only)

12. Anthropic, *Building Effective AI Agents* (2024-12-19).
    https://www.anthropic.com/engineering/building-effective-agents
    Underwrites: one answer orchestrator before any multi-agent graph; complexity is
    earned by a measured failure, not by architecture taste.
13. Anthropic, *Effective context engineering for AI agents* (2025-09-29).
    https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
    Underwrites: just-in-time retrieval of a targeted slice instead of a top-k dump
    into the window; the context budget is a finite resource with an owner.

### Claim-level auditability

14. J. James, C. Xiao, Y. Li, N. S. Moosavi, C. Lin, *RIGOURATE: Quantifying
    Scientific Exaggeration with Evidence-Aligned Claim Evaluation*,
    arXiv:2601.04350 (2026-01-07).
    Underwrites: overclaim is a measurable distance between an assertion and the
    evidence offered for it — therefore a gate, not an editorial opinion.
15. R. A. Rasheed, S. Banerjee, A. Mukherjee, R. Hazra, *From Fluent to Verifiable:
    Claim-Level Auditability for Deep Research Agents*, arXiv:2602.13855
    (2026-02-14).
    Underwrites: the unit of audit is the claim, not the answer; fluency of output
    raises, not lowers, the verification burden.
16. Y. Du, M. Dinh, K. Zhang, N. Li, *AutoVerifier: An Agentic Automated
    Verification Framework Using Large Language Models*, arXiv:2604.02617
    (2026-04-03).
    Underwrites: decomposition of a draft into claim triples with layered checks —
    the shape of the machine pass that precedes human sign-off on administrative
    drafts.

### Authority, attestation, audit records

17. J. Salfeld-Nebgen, *Governing Actions, Not Agents: Institutional Attestation as
    a Governance Model for Autonomous AI Systems*, arXiv:2606.26298 (2026-06-24).
    Underwrites: the core product constraint — planning autonomy without execution
    authority. High-risk actions require independent attestation; in this system the
    attesting party is the responsible officer, and the system holds no signature.
18. O. Solozobov, *DEMM-Bench: A Cross-Regime Benchmark for Agent-Runtime
    Governance-Evidence Sufficiency*, arXiv:2606.20634 (2026).
    Underwrites: the log is judged by whether a decision can be reconstructed from
    it, not by volume. Sets what must be recorded per answer.

### Integrity of our own measurements

19. X. Tu, T. Wang, Y. Lu, K. Huang, Y. Qu, S. Mostafavi, *BenchGuard: Who Guards
    the Benchmarks? Automated Auditing of LLM Agent Benchmarks*, arXiv:2604.24955
    (2026-04-27).
    Underwrites: eval fixtures are themselves audited; a defective fixture produces
    invalid failures and invalid green.
20. B. Nguyen, D. Soós, Q. Ma, R. R. Obadage, Z. Ranjan, S. Koneru, T. M. Errington,
    S. Nematova, S. Rajtmajer, J. Wu, M. Jiang, *ReplicatorBench: Benchmarking LLM
    Agents for Replicability in Social and Behavioral Sciences*, arXiv:2602.11354
    (2026-02-11).
    Underwrites: replication is a measured capability with a number, not a claim in
    a README.
21. M. Iscan, *Falsification, Not Exposure: An Internally Preregistered
    Placebo-Controlled Decomposition of Self-Repair Feedback in Frozen Small Code
    Models*, arXiv:2606.31511 (2026-06-30).
    Underwrites: the experimental protocol for any retrieval or prompt change —
    preregistered hypothesis, placebo arm, executable audit invariants. Without a
    placebo arm an improvement is indistinguishable from re-exposure.

### Formal specification (adopted where the cost is justified)

22. L. de Moura, S. Ullrich, *The Lean 4 Theorem Prover and Programming Language*,
    CADE-28, LNAI 12699, pp. 625–635 (2021). https://doi.org/10.1007/978-3-030-79876-5_37
    Underwrites: where a rule must not be violated, specification, proof and
    executable code live in one artifact. Caveat carried explicitly: compilation is
    not verification — a file with `sorry`, a restated theorem or incompatible
    axioms still compiles.
23. L. Lamport, *Specifying Systems: The TLA+ Language and Tools for Hardware and
    Software Engineers*, Addison-Wesley (2002). Canonical reference, not re-fetched
    in the session that added this list.
    Underwrites: model-checking of concurrent and distributed protocols at the
    specification level, ahead of implementation; bounded by state-space explosion.

### Deliberately excluded

Training-from-scratch curricula (CS336, LLM101n, nanochat), NeuroAI (Zador et al.),
and adaptive-compute work (MoD, MoR, CODA) are tracked elsewhere and underwrite no
decision here: this system does not train models and does not route compute. They are
omitted on purpose, not by oversight.

Correction to entry 11: RAGVUE was submitted 2025-12-03 and announced under
arXiv:2601.04196; the parenthetical "(2026)" refers to the announcement, not the work.

