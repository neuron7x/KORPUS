# Bibliography and Design Sources

Access date for online sources: 2026-09-04.

## KORPUS sources

1. KORPUS `AGENTS.md`, baseline `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`  
   https://github.com/neuron7x/KORPUS/blob/578f4ea9caa93ec6211dbe914bf11ae110a6eaed/AGENTS.md  
   Canonical workspace, isolated agent execution, protected main, no request-body authority,
   no retrieved text as privileged instruction, critical-mutant blocking.

2. KORPUS current architecture, `docs/architecture/SYSTEM.md`, baseline `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`  
   https://github.com/neuron7x/KORPUS/blob/578f4ea9caa93ec6211dbe914bf11ae110a6eaed/docs/architecture/SYSTEM.md  
   Evidence-bound product path, authorization before materialization, modular-monolith and
   source-of-truth boundaries, egress policy, extraction criteria.

3. KORPUS API dependencies, `apps/api/pyproject.toml`, baseline `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`  
   https://github.com/neuron7x/KORPUS/blob/578f4ea9caa93ec6211dbe914bf11ae110a6eaed/apps/api/pyproject.toml  
   Existing Pydantic, httpx, OpenTelemetry, Prometheus, FastAPI, SQLAlchemy and test stack.

4. KORPUS `adaptive_contracts.py`, baseline `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`  
   https://github.com/neuron7x/KORPUS/blob/578f4ea9caa93ec6211dbe914bf11ae110a6eaed/apps/api/src/korpus/application/adaptive_contracts.py  
   Repository-native precedent for deterministic explicit validation.

5. KORPUS `answer_audit_envelope.py`, baseline `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`  
   https://github.com/neuron7x/KORPUS/blob/578f4ea9caa93ec6211dbe914bf11ae110a6eaed/apps/api/src/korpus/application/answer_audit_envelope.py  
   Precedent for policy/session/service/request audit binding.

6. KORPUS `policy_evidence.py`, baseline `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`  
   https://github.com/neuron7x/KORPUS/blob/578f4ea9caa93ec6211dbe914bf11ae110a6eaed/apps/api/src/korpus/application/policy_evidence.py  
   Precedent for policy-decision correlation evidence that is explicitly not a capability
   token or alternate authorization mechanism.

## Public specifications and engineering references

7. Model Context Protocol Specification, revision 2025-11-25  
   https://modelcontextprotocol.io/specification/2025-11-25

8. MCP Base Protocol Overview, 2025-11-25  
   https://modelcontextprotocol.io/specification/2025-11-25/basic

9. MCP Authorization, 2025-11-25  
   https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

10. MCP Tools, 2025-11-25  
    https://modelcontextprotocol.io/specification/2025-11-25/server/tools

11. JSON Schema Draft 2020-12  
    https://json-schema.org/draft/2020-12

12. OpenAPI Specification 3.1.x  
    https://spec.openapis.org/oas/v3.1.0

13. OpenTelemetry Specification  
    https://opentelemetry.io/docs/specs/otel/

14. OpenTelemetry Semantic Conventions  
    https://opentelemetry.io/docs/specs/semconv/

15. CloudEvents 1.0  
    https://cloudevents.io/

16. SLSA Build Provenance v1.2  
    https://slsa.dev/spec/v1.2/build-provenance

17. in-toto Stable Specifications  
    https://in-toto.io/docs/specs/

18. NIST SP 800-207, Zero Trust Architecture  
    https://csrc.nist.gov/pubs/sp/800/207/final

19. NIST SP 800-218, Secure Software Development Framework v1.1  
    https://csrc.nist.gov/pubs/sp/800/218/final

20. Google SRE Workbook, Canarying Releases  
    https://sre.google/workbook/canarying-releases/

21. Google SRE, Reliable Product Launches at Scale  
    https://sre.google/sre-book/reliable-product-launches/

22. OpenAI, Harness engineering: leveraging Codex in an agent-first world, 2026-02-11  
    https://openai.com/index/harness-engineering/

23. Open Policy Agent, deployment model  
    https://www.openpolicyagent.org/docs/deploy

## Use discipline

Public specifications inform interoperability, policy separation, observability, provenance,
secure SDLC and release practice. They do not override stricter KORPUS repository invariants.
OPA and CloudEvents are comparative references, not v1 dependencies.
