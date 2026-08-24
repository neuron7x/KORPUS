# Assurance case

Status vocabulary: `SUPPORTED`, `PARTIAL`, `OPEN`, `FAILED`.

| Claim | Status | Current evidence | Open obligation |
|---|---|---|---|
| Unauthorized spans are excluded before ranking | SUPPORTED | SQL/FTS access predicates; noninterference tests; killed access mutants | independent penetration test; PostgreSQL RLS policy |
| Emitted claims are source-bound | SUPPORTED | extractive construction; exact offsets/hash; frozen citation checks | human factual review on real corpus |
| Stale versions are excluded by query date | SUPPORTED | temporal SQL predicate and supersession tests | complex amendment graph and jurisdiction rules |
| Audit truncation and mutation are detectable | SUPPORTED | HMAC chain, CAS head, external anchor, outbox recovery tests | remote/WORM anchor and key custody |
| Answer thresholds are statistically justified | PARTIAL | finite-sample calibration object and fail-closed production config | independent labeled dataset; preregistered risk limit |
| Query latency scales to production workload | OPEN | bounded candidate generation; local 5k-span probe | PostgreSQL load test under target concurrency and corpus size |
| System is authorized for military restricted data | OPEN | security-oriented code and controls only | formal data classification, security profile, authorization/accreditation |
| OCR preserves critical semantics | OPEN | parser limits and fail-closed extraction | page-level gold transcription and critical-field accuracy gate |
| Agent workflow is independently verified | PARTIAL | isolated branches/worktrees, MR and CODEOWNERS contracts | protected GitLab configuration and human reviewers |

A deployment may not convert `OPEN` into `SUPPORTED` by assertion. It requires new evidence and an accountable owner.
