# KORPUS v4.0.0 — Extended Assurance Audit Package

Date: 2026-08-01
Release audited: `KORPUS_INFRA_HARDENED_v4.0.0`, `main@a6056c5`, tag `v4.0.0`.

## Scope claim

This package does not claim that every possible unknown vulnerability has been found. It records 100% of the findings discovered in the frozen static/local audit scope, and separately identifies production areas that remain unverified without live infrastructure, a real corpus, independent TEVV/red-team and formal authorization.

## Verdict

- Production: FAIL
- Restricted military production: FAIL
- Controlled research/pilot on synthetic or open data without critical decisions: PASS_WITH_CAVEATS
- Weighted production-readiness score: 29.2/100 — EXTRAPOLATED

## Contents

- `KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.docx` — formal act suitable for review/sign-off.
- `KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.pdf` — rendered immutable review copy.
- `KORPUS_v4_EXTENDED_ASSURANCE_ACT_2026-08-01.md` — text/source-friendly act.
- `KORPUS_v4_REMEDIATION_BACKLOG_2026-08-01.csv` — 99 findings with evidence, impact, task, tools/methods and PASS predicate.
- `KORPUS_v4_FINDINGS_REGISTER_2026-08-01.json` — machine-readable findings and protocols.
- `KORPUS_v4_AUDIT_ARTIFACTS_2026-08-01.sha256` — integrity hashes.

## Finding states

- `VERIFIED_DEFECT` — demonstrated directly in source/configuration/local execution.
- `UNVERIFIED_BLOCKER` — required production evidence is absent; launch remains forbidden until produced.
- `CONDITIONAL_RISK` — applicability depends on data class, deployment or legal context and must be resolved before authorization.

## Severity counts

- P0: 30
- P1: 56
- P2: 13
- Total: 99

## Closure rule

A finding is closed only when its stated acceptance predicate passes and immutable evidence is attached. Code changes, screenshots, statements of intent or passing unrelated tests do not constitute closure.
