# KORPUS technical and research bibliography — 2026

Reviewed: `2026-09-02`. Canonical data: `config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json`.

External technical, scientific, operational, legal, and assurance references that materially inform KORPUS design or evaluation.

## Epistemic boundary

- A reference records design provenance only. It does not establish compliance, deployment fitness, legal authorization, or a passing KORPUS gate.
- Doctrine sources are governed separately by config/corpus/doctrine_catalog_2026.json; inclusion here would conflate product engineering evidence with corpus authority.
- Secondary summaries are excluded when a standard, official publication, specification, law, or primary paper is available.
- Living documentation and current law must be rechecked before a production authorization decision.

## Coverage

- `abstention_calibration` — 2 sources
- `adaptive_compute` — 4 sources
- `ai_governance` — 8 sources
- `authorization_identity` — 9 sources
- `data_durability` — 3 sources
- `evaluation_tevv` — 11 sources
- `human_factors` — 5 sources
- `legal_information_governance` — 3 sources
- `military_assurance` — 4 sources
- `neuroscience_basis` — 2 sources
- `observability_reliability` — 4 sources
- `provenance_integrity` — 9 sources
- `rag_citations` — 3 sources
- `rag_foundations` — 6 sources
- `rag_security` — 5 sources
- `runtime_deployment` — 5 sources
- `secure_development` — 11 sources
- `testing_reproducibility` — 6 sources

## Bibliography

### ACL-ADAPTIVE-RAG-2024

Soyeong Jeong; Jinheon Baek; Sukmin Cho; Sung Ju Hwang; Jong Park (2024). *Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity*. Association for Computational Linguistics. [https://aclanthology.org/2024.naacl-long.389/](https://aclanthology.org/2024.naacl-long.389/). DOI: `10.18653/v1/2024.naacl-long.389`.

Status: `research`; type: `peer-reviewed-research`; domains: `adaptive_compute`, `rag_foundations`.

Use: Adaptive retrieval-policy and query-complexity evaluation design.

Boundary: Does not validate KORPUS routing thresholds or transfer reported benchmark gains.

### ACL-ALCE-2023

Tianyu Gao; Howard Yen; Jinguo Yu; Danqi Chen (2023). *Enabling Large Language Models to Generate Text with Citations*. Association for Computational Linguistics. [https://aclanthology.org/2023.emnlp-main.398/](https://aclanthology.org/2023.emnlp-main.398/). DOI: `10.18653/v1/2023.emnlp-main.398`.

Status: `research`; type: `peer-reviewed-research`; domains: `rag_citations`, `evaluation_tevv`.

Use: Citation correctness, completeness, and answer-quality evaluation dimensions.

Boundary: Its datasets and metrics do not establish KORPUS corpus-domain performance.

### ACL-DPR-2020

Vladimir Karpukhin; Barlas Oğuz; Sewon Min; Patrick Lewis; Ledell Wu; Sergey Edunov; Danqi Chen; Wen-tau Yih (2020). *Dense Passage Retrieval for Open-Domain Question Answering*. Association for Computational Linguistics. [https://aclanthology.org/2020.emnlp-main.550/](https://aclanthology.org/2020.emnlp-main.550/). DOI: `10.18653/v1/2020.emnlp-main.550`.

Status: `research`; type: `peer-reviewed-research`; domains: `rag_foundations`.

Use: Dense-retrieval baseline and retrieval-recall evaluation vocabulary.

Boundary: Does not justify using dense retrieval without authorization, temporal, and citation gates.

### ANTHROPIC-AGENT-EVALS-2026

Anthropic (2026). *Demystifying evals for AI agents*. Anthropic. [https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

Status: `current`; type: `industry-methodology`; domains: `evaluation_tevv`.

Use: Lifecycle evaluation, multi-step task decomposition, and failure taxonomy.

Boundary: Vendor methodology is informative and is not independent evidence about KORPUS.

### ARXIV-INDIRECT-PROMPT-2026

Hongyan Chang; Ergute Bao; Xinjian Luo; Ting Yu (2026). *Overcoming the Retrieval Barrier: Indirect Prompt Injection in the Wild for LLM Systems*. arXiv. [https://arxiv.org/abs/2601.07072](https://arxiv.org/abs/2601.07072).

Status: `preprint`; type: `preprint`; domains: `rag_security`.

Use: Adversarial breadth for retrieval-borne indirect prompt injection.

Boundary: Preprint threat evidence motivates tests; it does not prove detector effectiveness.

### ARXIV-RAG-ROLL-2024

Gianluca De Stefano; Lea Schönherr; Giancarlo Pellegrino (2024). *Rag and Roll: An End-to-End Evaluation of Indirect Prompt Manipulations in LLM-based Application Frameworks*. arXiv. [https://arxiv.org/abs/2408.05025](https://arxiv.org/abs/2408.05025).

Status: `preprint`; type: `preprint`; domains: `rag_security`.

Use: Retrieved-content trust-boundary and injection destruction tests.

Boundary: Reported attacks are not a quantitative residual-risk estimate for KORPUS.

### ARXIV-RAGCHECKER-2024

Dongyu Ru; Lin Qiu; Xiangkun Hu; Tianhang Zhang; Peng Shi; Shuaichen Chang; Cheng Jiayang; Cunxiang Wang; Shichao Sun; Huanyu Li; Zizhao Zhang; Binjie Wang; Jiarong Jiang; Tong He; Zhiguo Wang; Pengfei Liu; Yue Zhang; Zheng Zhang (2024). *RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation*. arXiv. [https://arxiv.org/abs/2408.08067](https://arxiv.org/abs/2408.08067).

Status: `preprint`; type: `preprint`; domains: `rag_citations`, `evaluation_tevv`.

Use: Diagnostic separation of retrieval and generation failure modes.

Boundary: Metric definitions require local validation before use as release thresholds.

### ARXIV-SELECTIVE-CONFORMAL-2025

Yunpeng Xu; Wenge Guo; Zhi Wei (2025). *Selective Conformal Risk Control*. arXiv. [https://arxiv.org/abs/2512.12844](https://arxiv.org/abs/2512.12844).

Status: `preprint`; type: `preprint`; domains: `abstention_calibration`.

Use: Separation of prediction, selection, abstention, and risk-control evidence.

Boundary: KORPUS does not claim conformal guarantees without validated exchangeability assumptions.

### ARXIV-TESTING-NONINTERFERENCE-2014

Catalin Hritcu; Leonidas Lampropoulos; Antal Spector-Zabusky; Arthur Azevedo de Amorim; Maxime Dénès; John Hughes; Benjamin C. Pierce; Dimitrios Vytiniotis (2014). *Testing Noninterference, Quickly*. arXiv. [https://arxiv.org/abs/1409.0393](https://arxiv.org/abs/1409.0393).

Status: `research`; type: `preprint`; domains: `testing_reproducibility`, `authorization_identity`.

Use: Property-based noninterference tests for authorization boundaries.

Boundary: Tested finite observations do not constitute a general formal proof.

### AWS-S3-INTEGRITY

Amazon Web Services (2026). *Checking object integrity in Amazon S3*. Amazon Web Services. [https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html).

Status: `living`; type: `official-documentation`; domains: `data_durability`, `provenance_integrity`.

Use: Object checksum and integrity-verification semantics for S3-compatible storage.

Boundary: Vendor behavior is not inherited by every S3-compatible implementation.

### AWS-S3-OBJECT-LOCK

Amazon Web Services (2026). *Locking objects with Object Lock*. Amazon Web Services. [https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html).

Status: `living`; type: `official-documentation`; domains: `data_durability`, `provenance_integrity`.

Use: Retention and write-once storage threat modeling.

Boundary: Configuration and governance mode require production-side evidence.

### C2PA-2.4

Coalition for Content Provenance and Authenticity (2026). *C2PA Technical Specification, version 2.4*. Coalition for Content Provenance and Authenticity. [https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html](https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html).

Status: `current`; type: `specification`; domains: `provenance_integrity`.

Use: Signed content-provenance vocabulary and trust-boundary comparison.

Boundary: KORPUS does not claim C2PA conformance or that provenance proves truth.

### CDAO-AI-TE-2024

CDAO (2024). *CDAO Test and Evaluation Strategy Frameworks*. United States Department of Defense Chief Digital and Artificial Intelligence Office. [https://www.ai.mil/Latest/Blog/Article-Display/Article/3940283/cdao-test-and-evaluation-strategy-frameworks/](https://www.ai.mil/Latest/Blog/Article-Display/Article/3940283/cdao-test-and-evaluation-strategy-frameworks/).

Status: `final`; type: `official-guidance`; domains: `evaluation_tevv`, `human_factors`, `military_assurance`.

Use: Model, human-systems, systems-integration, and operational T&E decomposition.

Boundary: Public framework is not an operational authorization or completed independent T&E.

### DEEPMIND-FSF-3.1

Google DeepMind (2026). *Frontier Safety Framework 3.1*. Google DeepMind. [https://deepmind.google/frontier-safety/](https://deepmind.google/frontier-safety/).

Status: `current`; type: `industry-methodology`; domains: `ai_governance`, `evaluation_tevv`.

Use: Capability-level, early-warning evaluation, and proportional-mitigation concepts.

Boundary: A frontier-model framework does not define KORPUS deployment readiness.

### GOOGLE-SRE-ERROR-BUDGET

Google SRE (2018). *Example Error Budget Policy*. Google. [https://sre.google/workbook/error-budget-policy/](https://sre.google/workbook/error-budget-policy/).

Status: `living`; type: `official-guidance`; domains: `observability_reliability`.

Use: Operational decision policy tied to measured reliability consumption.

Boundary: Example policy requires locally agreed objectives and risk ownership.

### GOOGLE-SRE-SLO

Chris Jones; John Wilkes; Niall Murphy; Cody Smith (2017). *Service Level Objectives*. Google. [https://sre.google/sre-book/service-level-objectives/](https://sre.google/sre-book/service-level-objectives/).

Status: `living`; type: `official-guidance`; domains: `observability_reliability`.

Use: SLI, SLO, and error-budget vocabulary for production evidence.

Boundary: No SLO attainment follows from adopting the vocabulary.

### HFES-OUT-OF-LOOP-1995

Mica R. Endsley; Esin O. Kiris (1995). *The Out-of-the-Loop Performance Problem and Level of Control in Automation*. Human Factors and Ergonomics Society. [https://doi.org/10.1518/001872095779064555](https://doi.org/10.1518/001872095779064555). DOI: `10.1518/001872095779064555`.

Status: `research`; type: `peer-reviewed-research`; domains: `human_factors`.

Use: Human-override, situation-awareness, and automation-level threat modeling.

Boundary: Laboratory findings do not establish operator performance in the KORPUS context.

### HFES-TRUST-AUTOMATION-2004

John D. Lee; Katrina A. See (2004). *Trust in Automation: Designing for Appropriate Reliance*. Human Factors and Ergonomics Society. [https://doi.org/10.1518/hfes.46.1.50_30392](https://doi.org/10.1518/hfes.46.1.50_30392). DOI: `10.1518/hfes.46.1.50_30392`.

Status: `research`; type: `peer-reviewed-research`; domains: `human_factors`.

Use: Appropriate reliance and calibrated operator trust.

Boundary: Design guidance does not itself demonstrate calibrated reliance.

### ICLR-SELF-RAG-2024

Akari Asai; Zeqiu Wu; Yizhong Wang; Avirup Sil; Hannaneh Hajishirzi (2024). *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection*. International Conference on Learning Representations. [https://openreview.net/forum?id=hSyW5go0v8](https://openreview.net/forum?id=hSyW5go0v8).

Status: `research`; type: `peer-reviewed-research`; domains: `adaptive_compute`, `rag_foundations`.

Use: Retrieval-on-demand and explicit critique/action vocabulary.

Boundary: KORPUS does not inherit Self-RAG training results or self-critique reliability.

### IEEE-MUTATION-SURVEY-2011

Yue Jia; Mark Harman (2011). *An Analysis and Survey of the Development of Mutation Testing*. IEEE. [https://doi.org/10.1109/TSE.2010.62](https://doi.org/10.1109/TSE.2010.62). DOI: `10.1109/TSE.2010.62`.

Status: `research`; type: `peer-reviewed-research`; domains: `testing_reproducibility`.

Use: Mutation-testing methodology and equivalent-mutant caution.

Boundary: Mutation score alone is not a release verdict or proof of correctness.

### IEEE-REPRODUCIBLE-BUILDS-2022

Chris Lamb; Stefano Zacchiroli (2022). *Reproducible Builds: Increasing the Integrity of Software Supply Chains*. IEEE Software. [https://doi.org/10.1109/MS.2021.3073045](https://doi.org/10.1109/MS.2021.3073045). DOI: `10.1109/MS.2021.3073045`.

Status: `research`; type: `peer-reviewed-research`; domains: `testing_reproducibility`, `provenance_integrity`.

Use: Independent rebuild comparison and separation of source review from artifact trust.

Boundary: Reproducibility alone does not establish source correctness or builder trust.

### IN-TOTO-1.0

in-toto project (2022). *in-toto Specification, version 1.0*. in-toto project. [https://github.com/in-toto/docs/blob/v1.0/in-toto-spec.md](https://github.com/in-toto/docs/blob/v1.0/in-toto-spec.md).

Status: `stable`; type: `specification`; domains: `provenance_integrity`, `secure_development`.

Use: Attestation statement and software-supply-chain layout semantics.

Boundary: A structurally valid statement does not make its signer trusted.

### K8S-NETWORK-POLICY

Kubernetes project (2026). *Network Policies*. Kubernetes. [https://kubernetes.io/docs/concepts/services-networking/network-policies/](https://kubernetes.io/docs/concepts/services-networking/network-policies/).

Status: `living`; type: `official-documentation`; domains: `runtime_deployment`, `authorization_identity`.

Use: Default-deny and explicit ingress/egress policy semantics.

Boundary: Policy objects are ineffective without a supporting network plugin and runtime evidence.

### K8S-POD-SECURITY-STANDARDS

Kubernetes project (2026). *Pod Security Standards*. Kubernetes. [https://kubernetes.io/docs/concepts/security/pod-security-standards/](https://kubernetes.io/docs/concepts/security/pod-security-standards/).

Status: `living`; type: `official-documentation`; domains: `runtime_deployment`, `secure_development`.

Use: Restricted workload security-context baseline.

Boundary: Manifest conformance does not prove cluster admission or node security.

### NATO-AI-STRATEGY-2024

NATO (2024). *Summary of NATO's revised Artificial Intelligence strategy*. North Atlantic Treaty Organization. [https://www.nato.int/en/about-us/official-texts-and-resources/official-texts/2024/07/10/summary-of-natos-revised-artificial-intelligence-ai-strategy](https://www.nato.int/en/about-us/official-texts-and-resources/official-texts/2024/07/10/summary-of-natos-revised-artificial-intelligence-ai-strategy).

Status: `final`; type: `official-policy`; domains: `military_assurance`, `ai_governance`, `human_factors`.

Use: Responsible-use, testing, interoperability, and lifecycle-risk context.

Boundary: Alliance policy context is not a national legal authorization or KORPUS approval.

### NATO-DIGITAL-STRATEGY-2026

NATO (2026). *Alliance Digital Strategy*. North Atlantic Treaty Organization. [https://www.nato.int/en/about-us/official-texts-and-resources/official-texts/2026/01/13/alliance-digital-strategy](https://www.nato.int/en/about-us/official-texts-and-resources/official-texts/2026/01/13/alliance-digital-strategy).

Status: `final`; type: `official-policy`; domains: `military_assurance`, `runtime_deployment`, `human_factors`.

Use: Tactical-edge resilience, federated access, interoperability, and digital proficiency context.

Boundary: Strategy does not specify KORPUS requirements or authorize operational deployment.

### NATURE-FREE-ENERGY-2010

Karl Friston (2010). *The free-energy principle: a unified brain theory?*. Nature Reviews Neuroscience. [https://doi.org/10.1038/nrn2787](https://doi.org/10.1038/nrn2787). DOI: `10.1038/nrn2787`.

Status: `research`; type: `peer-reviewed-research`; domains: `neuroscience_basis`, `adaptive_compute`.

Use: Conceptual provenance for prediction-error and adaptive-control hypotheses.

Boundary: Neuroscience theory is not implementation evidence and is not claimed as a literal software homology.

### NEURIPS-BEIR-2021

Nandan Thakur; Nils Reimers; Andreas Rücklé; Abhishek Srivastava; Iryna Gurevych (2021). *BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models*. Neural Information Processing Systems. [https://openreview.net/forum?id=wCu6T5xFjeJ](https://openreview.net/forum?id=wCu6T5xFjeJ).

Status: `research`; type: `peer-reviewed-research`; domains: `rag_foundations`, `evaluation_tevv`.

Use: Heterogeneous retrieval evaluation and out-of-domain generalization caution.

Boundary: Benchmark rankings do not establish performance on the governed KORPUS corpus.

### NEURIPS-RAG-2020

Patrick Lewis; Ethan Perez; Aleksandra Piktus; Fabio Petroni; Vladimir Karpukhin; Naman Goyal; Heinrich Küttler; Mike Lewis; Wen-tau Yih; Tim Rocktäschel; Sebastian Riedel; Douwe Kiela (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. Neural Information Processing Systems. [https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html).

Status: `research`; type: `peer-reviewed-research`; domains: `rag_foundations`.

Use: Foundational retrieval-plus-generation architecture and evaluation baseline.

Boundary: Parametric/non-parametric generation does not satisfy KORPUS exact-span admissibility.

### NEURON-EVC-2013

Amitai Shenhav; Matthew M. Botvinick; Jonathan D. Cohen (2013). *The Expected Value of Control: An Integrative Theory of Anterior Cingulate Cortex Function*. Neuron. [https://doi.org/10.1016/j.neuron.2013.07.007](https://doi.org/10.1016/j.neuron.2013.07.007). DOI: `10.1016/j.neuron.2013.07.007`.

Status: `research`; type: `peer-reviewed-research`; domains: `neuroscience_basis`, `adaptive_compute`.

Use: Conceptual provenance for cost-sensitive allocation of control.

Boundary: Biological mechanism is not asserted for KORPUS; only falsifiable controller analogues are tested.

### NIST-AI-RMF-1.0

Elham Tabassi (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*. National Institute of Standards and Technology. [https://doi.org/10.6028/NIST.AI.100-1](https://doi.org/10.6028/NIST.AI.100-1). DOI: `10.6028/NIST.AI.100-1`.

Status: `final-under-revision`; type: `standard`; domains: `ai_governance`, `evaluation_tevv`.

Use: Govern, Map, Measure, and Manage risk lifecycle.

Boundary: Voluntary framework; version 1.0 is under revision and is not a certification.

### NIST-GENAI-PROFILE-600-1

National Institute of Standards and Technology (2024). *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile*. National Institute of Standards and Technology. [https://doi.org/10.6028/NIST.AI.600-1](https://doi.org/10.6028/NIST.AI.600-1). DOI: `10.6028/NIST.AI.600-1`.

Status: `final`; type: `standard`; domains: `ai_governance`, `rag_security`.

Use: GenAI-specific risk identification, measurement, and governance actions.

Boundary: Profile use does not establish conformance or residual-risk acceptability.

### NIST-SP-800-162

Vincent C. Hu; David Ferraiolo; Rick Kuhn; Adam Schnitzer; Kenneth Sandlin; Robert Miller; Karen Scarfone (2014). *Guide to Attribute Based Access Control (ABAC) Definition and Considerations*. National Institute of Standards and Technology. [https://doi.org/10.6028/NIST.SP.800-162](https://doi.org/10.6028/NIST.SP.800-162). DOI: `10.6028/NIST.SP.800-162`.

Status: `final`; type: `standard`; domains: `authorization_identity`.

Use: ABAC terminology, policy inputs, and deployment considerations.

Boundary: ABAC vocabulary does not verify KORPUS policy completeness or enforcement.

### NIST-SP-800-218

Murugiah Souppaya; Karen Scarfone; Donna Dodson (2022). *Secure Software Development Framework (SSDF) Version 1.1*. National Institute of Standards and Technology. [https://doi.org/10.6028/NIST.SP.800-218](https://doi.org/10.6028/NIST.SP.800-218). DOI: `10.6028/NIST.SP.800-218`.

Status: `final`; type: `standard`; domains: `secure_development`.

Use: Secure development lifecycle and vulnerability-prevention practices.

Boundary: Reference mapping is not an SSDF conformity assessment.

### NIST-SP-800-218A

Harold Booth; Murugiah Souppaya; Apostol Vassilev; Michael Ogata; Martin Stanley; Karen Scarfone (2024). *Secure Software Development Practices for Generative AI and Dual-Use Foundation Models: An SSDF Community Profile*. National Institute of Standards and Technology. [https://doi.org/10.6028/NIST.SP.800-218A](https://doi.org/10.6028/NIST.SP.800-218A). DOI: `10.6028/NIST.SP.800-218A`.

Status: `final`; type: `standard`; domains: `secure_development`, `ai_governance`.

Use: AI-specific secure-development threats and evidence expectations.

Boundary: KORPUS is an AI system, not a claimed dual-use foundation model.

### NIST-SP-800-63-4

David Temoshok; Diana Proud-Madruga; Yee-Yin Choong; Ryan Galluzzo; Sarbari Gupta; Connie LaSalle; Naomi Lefkovitz; Andrew Regenscheid (2025). *Digital Identity Guidelines*. National Institute of Standards and Technology. [https://doi.org/10.6028/NIST.SP.800-63-4](https://doi.org/10.6028/NIST.SP.800-63-4). DOI: `10.6028/NIST.SP.800-63-4`.

Status: `final`; type: `standard`; domains: `authorization_identity`, `secure_development`.

Use: Identity proofing, authentication, federation, and authenticator assurance vocabulary.

Boundary: Deployment assurance levels require explicit local risk selection and operational evidence.

### OAUTH-RFC9700

Torsten Lodderstedt; John Bradley; Andrey Labunets; Daniel Fett (2025). *Best Current Practice for OAuth 2.0 Security*. Internet Engineering Task Force. [https://www.rfc-editor.org/info/rfc9700](https://www.rfc-editor.org/info/rfc9700). DOI: `10.17487/RFC9700`.

Status: `best-current-practice`; type: `standard`; domains: `authorization_identity`, `secure_development`.

Use: OAuth threat model and current security recommendations.

Boundary: Protocol selection does not prove provider or client configuration correctness.

### OIDC-CORE-ERRATA2

Nat Sakimura; John Bradley; Michael B. Jones; Breno de Medeiros; Chuck Mortimore (2023). *OpenID Connect Core 1.0 incorporating errata set 2*. OpenID Foundation. [https://openid.net/specs/openid-connect-core-1_0-errata2.html](https://openid.net/specs/openid-connect-core-1_0-errata2.html).

Status: `final`; type: `standard`; domains: `authorization_identity`.

Use: OIDC authentication, claims, token validation, and relying-party semantics.

Boundary: Specification conformance and identity-provider assurance remain deployment evidence.

### OPENAI-3P-EVALS-2026

OpenAI (2026). *A shared playbook for trustworthy third party evaluations*. OpenAI. [https://openai.com/index/trustworthy-third-party-evaluations-foundations/](https://openai.com/index/trustworthy-third-party-evaluations-foundations/).

Status: `current`; type: `industry-methodology`; domains: `evaluation_tevv`, `ai_governance`.

Use: Evaluand identity, harness disclosure, elicitation budget, validity hazards, and independence.

Boundary: Vendor-authored methodology is not a third-party evaluation of KORPUS.

### OPENAI-EVAL-INTEGRITY-2026

OpenAI (2026). *Separating signal from noise in coding evaluations*. OpenAI. [https://openai.com/index/separating-signal-from-noise-coding-evaluations/](https://openai.com/index/separating-signal-from-noise-coding-evaluations/).

Status: `current`; type: `industry-methodology`; domains: `evaluation_tevv`, `testing_reproducibility`.

Use: Task-level quality audit and avoidance of misleading aggregate benchmark scores.

Boundary: Observed benchmark defects do not quantify defects in KORPUS evaluation fixtures.

### OPENAI-MODEL-SPEC-METHOD-2026

OpenAI (2026). *Inside our approach to the Model Spec*. OpenAI. [https://openai.com/index/our-approach-to-the-model-spec/](https://openai.com/index/our-approach-to-the-model-spec/).

Status: `current`; type: `industry-methodology`; domains: `ai_governance`.

Use: Explicit hierarchical behavioral specifications and eval-facing policy artifacts.

Boundary: KORPUS policy hierarchy is independently specified and does not inherit Model Spec authority.

### OPENTELEMETRY-SPEC-1.60.0

OpenTelemetry project (2026). *OpenTelemetry Specification 1.60.0*. OpenTelemetry. [https://opentelemetry.io/docs/specs/otel/](https://opentelemetry.io/docs/specs/otel/).

Status: `current`; type: `specification`; domains: `observability_reliability`.

Use: Portable telemetry signal and context-propagation semantics.

Boundary: Telemetry is operational evidence, not tamper-evident audit authority.

### OWASP-ASVS-5.0.0

OWASP Foundation (2025). *Application Security Verification Standard 5.0.0*. OWASP Foundation. [https://owasp.org/www-project-application-security-verification-standard/](https://owasp.org/www-project-application-security-verification-standard/).

Status: `stable`; type: `standard`; domains: `secure_development`, `authorization_identity`.

Use: Application-security verification taxonomy and control review.

Boundary: Checklist mapping and tests do not constitute ASVS certification.

### OWASP-LLM-TOP10-2025

OWASP GenAI Security Project (2025). *OWASP Top 10 for LLM Applications 2025*. OWASP Foundation. [https://genai.owasp.org/llm-top-10/](https://genai.owasp.org/llm-top-10/).

Status: `stable`; type: `industry-methodology`; domains: `rag_security`, `secure_development`.

Use: LLM application threat taxonomy including prompt injection and supply-chain risks.

Boundary: A threat list is not a complete system threat model or penetration result.

### PMLR-CALIBRATION-2017

Chuan Guo; Geoff Pleiss; Yu Sun; Kilian Q. Weinberger (2017). *On Calibration of Modern Neural Networks*. Proceedings of Machine Learning Research. [https://proceedings.mlr.press/v70/guo17a.html](https://proceedings.mlr.press/v70/guo17a.html).

Status: `research`; type: `peer-reviewed-research`; domains: `abstention_calibration`, `evaluation_tevv`.

Use: Calibration measurement and post-hoc calibration baseline.

Boundary: Model confidence calibration does not calibrate end-to-end evidence admissibility.

### POSTGRES-CONTINUOUS-ARCHIVING

PostgreSQL Global Development Group (2026). *Continuous Archiving and Point-in-Time Recovery*. PostgreSQL Global Development Group. [https://www.postgresql.org/docs/current/continuous-archiving.html](https://www.postgresql.org/docs/current/continuous-archiving.html).

Status: `living`; type: `official-documentation`; domains: `data_durability`, `runtime_deployment`.

Use: WAL archiving, recovery points, and restore-drill design.

Boundary: Documentation does not prove backups are complete, restorable, or within local objectives.

### POSTGRES-ROW-SECURITY

PostgreSQL Global Development Group (2026). *Row Security Policies*. PostgreSQL Global Development Group. [https://www.postgresql.org/docs/current/ddl-rowsecurity.html](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

Status: `living`; type: `official-documentation`; domains: `authorization_identity`, `runtime_deployment`.

Use: Row-security, owner bypass, BYPASSRLS, and FORCE ROW LEVEL SECURITY semantics.

Boundary: SQLite tests cannot establish PostgreSQL RLS behavior or production role hygiene.

### PROMETHEUS-INSTRUMENTATION

Prometheus Authors (2026). *Instrumentation*. Prometheus. [https://prometheus.io/docs/practices/instrumentation/](https://prometheus.io/docs/practices/instrumentation/).

Status: `living`; type: `official-documentation`; domains: `observability_reliability`.

Use: Metric naming, cardinality constraints, and failure-oriented instrumentation.

Boundary: Metrics do not replace audit records and can be absent or sampled.

### QUICKCHECK-2000

Koen Claessen; John Hughes (2000). *QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs*. ACM. [https://doi.org/10.1145/351240.351266](https://doi.org/10.1145/351240.351266). DOI: `10.1145/351240.351266`.

Status: `research`; type: `peer-reviewed-research`; domains: `testing_reproducibility`.

Use: Property-based testing, generators, shrinking, and executable invariants.

Boundary: Sampled property testing does not prove unbounded correctness.

### RFC8725-JWT

Yaron Sheffer; Dick Hardt; Michael B. Jones (2020). *JSON Web Token Best Current Practices*. Internet Engineering Task Force. [https://www.rfc-editor.org/info/rfc8725](https://www.rfc-editor.org/info/rfc8725). DOI: `10.17487/RFC8725`.

Status: `best-current-practice`; type: `standard`; domains: `authorization_identity`, `secure_development`.

Use: JWT algorithm verification, validation rules, and cross-JWT confusion defenses.

Boundary: Following the BCP does not establish key custody or identity-provider security.

### RFC8785-JCS

Anders Rundgren; Bradley Jordan; Samuel Erdtman (2020). *JSON Canonicalization Scheme (JCS)*. Internet Engineering Task Force. [https://www.rfc-editor.org/info/rfc8785](https://www.rfc-editor.org/info/rfc8785). DOI: `10.17487/RFC8785`.

Status: `informational`; type: `standard`; domains: `provenance_integrity`, `testing_reproducibility`.

Use: Deterministic JSON serialization and digest/signature boundary analysis.

Boundary: KORPUS canonical encodings are separately specified; citation does not assert JCS conformance.

### SLSA-1.2

SLSA project (2025). *SLSA Specification, version 1.2*. Supply-chain Levels for Software Artifacts. [https://slsa.dev/spec/v1.2/](https://slsa.dev/spec/v1.2/).

Status: `approved`; type: `specification`; domains: `secure_development`, `provenance_integrity`.

Use: Source/build track, provenance, and hosted-builder assurance vocabulary.

Boundary: Local provenance deliberately claims no SLSA level without trusted hosted-builder evidence.

### SPDX-3.0.1

SPDX Workgroup (2024). *SPDX Specification 3.0.1*. Linux Foundation SPDX Workgroup. [https://spdx.github.io/spdx-spec/v3.0.1/](https://spdx.github.io/spdx-spec/v3.0.1/).

Status: `current`; type: `specification`; domains: `secure_development`, `provenance_integrity`.

Use: Software bill-of-materials and software-component relationship vocabulary.

Boundary: An SBOM inventory does not establish component safety or vulnerability absence.

### TMLR-HELM-2023

Percy Liang; Rishi Bommasani; Tony Lee; Dimitris Tsipras; Dilara Soylu; Michihiro Yasunaga; Yian Zhang; Deepak Narayanan; Yuhuai Wu; Ananya Kumar; Benjamin Newman; Binhang Yuan; Bobby Yan; Ce Zhang; Christian Cosgrove; Christopher D. Manning; Christopher Ré; Diana Acosta-Navas; Drew A. Hudson; Eric Zelikman; Esin Durmus; Faisal Ladhak; Frieda Rong; Hongyu Ren; Huaxiu Yao; Jue Wang; Keshav Santhanam; Laurel Orr; Lucia Zheng; Mert Yuksekgonul; Mirac Suzgun; Nathan Kim; Neel Guha; Niladri Chatterji; Omar Khattab; Peter Henderson; Qian Huang; Ryan Chi; Sang Michael Xie; Shibani Santurkar; Surya Ganguli; Tatsunori Hashimoto; Thomas Icard; Tianyi Zhang; Vishrav Chaudhary; William Wang; Xuechen Li; Yifan Mai; Yuhui Zhang; Yuta Koreeda (2023). *Holistic Evaluation of Language Models*. Transactions on Machine Learning Research. [https://arxiv.org/abs/2211.09110](https://arxiv.org/abs/2211.09110).

Status: `research`; type: `peer-reviewed-research`; domains: `evaluation_tevv`, `ai_governance`.

Use: Multi-metric evaluation taxonomy, scenario transparency, and reproducibility.

Boundary: HELM results do not evaluate KORPUS or authorize deployment.

### UA-LAW-2297-VI

Verkhovna Rada of Ukraine (2010). *Law of Ukraine No. 2297-VI: On Personal Data Protection*. Verkhovna Rada of Ukraine. [https://zakon.rada.gov.ua/go/2297-17](https://zakon.rada.gov.ua/go/2297-17).

Status: `law-current`; type: `law`; domains: `legal_information_governance`.

Use: Personal-data processing and protection legal boundary.

Boundary: Current applicability and lawful basis require qualified legal review; this is not legal advice.

### UA-LAW-2657-XII

Verkhovna Rada of Ukraine (1992). *Law of Ukraine No. 2657-XII: On Information*. Verkhovna Rada of Ukraine. [https://zakon.rada.gov.ua/go/2657-12](https://zakon.rada.gov.ua/go/2657-12).

Status: `law-current`; type: `law`; domains: `legal_information_governance`.

Use: Information-regime, access, and protection legal boundary.

Boundary: The repository does not decide legal classification or authority to process information.

### UA-LAW-3855-XII

Verkhovna Rada of Ukraine (1994). *Law of Ukraine No. 3855-XII: On State Secrets*. Verkhovna Rada of Ukraine. [https://zakon.rada.gov.ua/go/3855-12](https://zakon.rada.gov.ua/go/3855-12).

Status: `law-current`; type: `law`; domains: `legal_information_governance`, `military_assurance`.

Use: Secret-information classification, access, and protection legal boundary.

Boundary: KORPUS does not classify state secrets or self-authorize handling classified information.

### USENIX-POISONEDRAG-2025

Wei Zou; Runpeng Geng; Binghui Wang; Jinyuan Jia (2025). *PoisonedRAG: Knowledge Corruption Attacks to Retrieval-Augmented Generation of Large Language Models*. USENIX Association. [https://www.usenix.org/conference/usenixsecurity25/presentation/zou-poisonedrag](https://www.usenix.org/conference/usenixsecurity25/presentation/zou-poisonedrag).

Status: `research`; type: `peer-reviewed-research`; domains: `rag_security`, `rag_foundations`.

Use: Corpus-poisoning threat model and retrieval-integrity adversarial tests.

Boundary: Attack success rates do not estimate KORPUS residual risk.

### W3C-PROV-O-2013

Timothy Lebo; Satya Sahoo; Deborah McGuinness (2013). *PROV-O: The PROV Ontology*. World Wide Web Consortium. [https://www.w3.org/TR/prov-o/](https://www.w3.org/TR/prov-o/).

Status: `recommendation`; type: `standard`; domains: `provenance_integrity`, `rag_citations`.

Use: Entity, activity, agent, derivation, and attribution provenance vocabulary.

Boundary: KORPUS uses its own binding schema and does not claim PROV-O interoperability.
