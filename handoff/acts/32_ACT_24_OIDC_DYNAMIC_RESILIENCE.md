# ACT-24 — Browser OIDC dynamic resilience

- Value hypothesis: concurrent state correctness and exact fault classification reveal failure modes that statement coverage cannot.
- Linked findings: `IAM-002`, `OPS-004`; neither is externally closed.
- Trust boundary: concurrent browser envelopes and degraded IdP responses → bounded OIDC client → recovery.
- Allowed files: dynamic gate/tests, browser OIDC CI evidence, this act and verifier index.
- Forbidden files: production traffic, real IdP credentials, infinite soak, production authorization and fabricated SLOs.
- Killable invariants: exact scenario oracle; zero raw exceptions; zero codec corruption; complete recovery; bounded workload; machine report cannot self-authorize.
- Faults: HTTP 503, malformed JSON, ConnectError, wrong token type, concurrent AEAD seal/open and post-burst recovery.
- Acceptance: local high-concurrency and maximum bounded soak PASS; validator mutations fail; full regression/mutation/determinism green.
- Rollback: revert ACT-24 commit; no state migration.
- Residual uncertainty: mock transport does not exercise sockets, DNS, TLS, IdP quotas, kernel limits or week-long resource leakage.

## Anchored maximum local run

- Workload: 100,000 operations, 64 workers, bounded submission window 256 and 1,000 recovery calls.
- Oracle: exactly 20,000 each of success, HTTP 503, invalid JSON, ConnectError and wrong token type.
- Result: zero raw exceptions, zero codec failures, recovery 1,000/1,000, threads 1→1 and file descriptors 4→4.
- Duration: 165.244 seconds; throughput 605.167 operations/second; p50 1.506 ms, p95 86.413 ms, p99 157.497 ms and max 402.402 ms.
- Harness falsification: eager `Executor.map` reached about 445 MB RSS and was terminated; bounded windows held observed RSS near 48–55 MB and tracemalloc peak at 4,344,292 bytes.
- Evidence lifecycle falsification: the terminated run left the previous PASS JSON in place; the gate now deletes stale output before work and atomically publishes only a completed validated report.
- Method sources: HTTPX timeout/resource-limit documentation and Google SRE guidance to test state correctness under load, impulse/fault behavior and recovery beyond overload.
