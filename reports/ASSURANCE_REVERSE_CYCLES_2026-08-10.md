# KORPUS v6.7.1 — Assurance Reverse Cycles

- Git-domain source: `98c93c7a1b6c46ce351cd83feb5416120dc82c9e718c932cd322689faf070feb`
- Evidence-domain source: `ea85a6c494fd2ba27383f951f5b122c91bf71d5b04d5a805dfe1ada877e0f412`
- Fresh suite: 1318 tests; 0 failures; 0 errors; 1 skipped
- Coverage: line 0.9171; branch 0.7902
- Mutation: 259/259 killed; score 1.0

## Cycle 12 — Canonical signed release boundary
**PASS_WITH_CAVEATS · ANCHORED_LOCAL**

Ed25519 sign/verify/tamper mechanics PASS; production verifier refuses release while production_authorized=false. Trusted external/KMS signer absent.

## Cycle 11 — Production TEVV
**FAIL · ANCHORED_LOCAL**

TEVV gate failures: ['preregistered', 'source_bound', 'release_bound', 'environment_class', 'tevv_admissible', 'pass_rate', 'null_controls', 'attack_families', 'tevv:dataset declares no corpus: the run is a fixture run', 'tevv:0 observations is below the floor of 200: a point estimate from too few queries is not a measurement', 'tevv:95% interval is 1.000 wide, above the maximum 0.100: the run does not constrain the answer enough']

## Cycle 10 — Observability and incident containment
**PASS · ANCHORED_LOCAL**

Bounded metric label contract; no identity/user-text metric labels; security labels bounded.

## Cycle 9 — State-machine and transaction contracts
**PASS · ANCHORED_LOCAL**

Exhaustive review/subscription transition matrices and terminal-state invariants.

## Cycle 8 — Authorization model
**PASS · ANCHORED_LOCAL**

Executable role×permission matrix; unknown permissions denied for every role including admin.

## Cycle 7 — Pentest / red-team
**PASS_WITH_CAVEATS · ANCHORED_LOCAL**

Internal adversarial campaign=PASS; external independently attested pentest=FAIL.

## Cycle 6 — Distributed reliability qualification
**PASS_WITH_CAVEATS · ANCHORED_LOCAL**

Internal fault injection=PASS; production reliability=FAIL; chaos cases=8.

## Cycle 5 — Inference security
**PASS · ANCHORED_LOCAL**

Direct/indirect injection, retrieval poisoning, egress leakage, planner-control, evidence-boundary and cross-scope tests executed.

## Cycle 4 — PostgreSQL security
**FAIL · ANCHORED_LOCAL**

Static grant contract=True; real PostgreSQL runtime=False; adversarial suite=False.

## Cycle 3 — Supply-chain assurance
**FAIL · ANCHORED_LOCAL**

Pinned records=68; hashed records=68; scanners clean=False; container SBOMs=False.

## Cycle 2 — Exact reproducible environment
**FAIL · ANCHORED_LOCAL**

Locked components=68; missing=['ast-serialize', 'librt', 'mypy', 'mypy-extensions', 'psycopg', 'psycopg-binary', 'ruff']; mismatched=['click', 'cryptography', 'fastapi', 'pydantic-settings', 'pypdf', 'python-multipart', 'starlette', 'typing-extensions', 'pathspec', 'pytest'].

## Cycle 1 — Full mutation assurance
**PASS · ANCHORED_LOCAL**

mutants=259; valid=259; killed=259; survivors=0; scope=FULL_CATALOGUE.

## Final gates
- Local engineering hardening: **PASS_WITH_CAVEATS**
- Production assurance: **FAIL**

Unclosed predicates:
- Ruff execution
- Mypy execution
- complete dependency/filesystem/container vulnerability scanners
- container SBOMs
- real PostgreSQL adversarial/RLS/concurrency suite
- production-like load/soak and recovery drill
- production-class preregistered TEVV corpus
- independently attested trusted external pentest
- trusted external/KMS release signer
