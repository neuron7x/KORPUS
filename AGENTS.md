# Repository instructions

- Preserve the evidence-first invariants in `README.md`.
- Business rules belong in `apps/api/src/korpus/domain`, not prompts or routes.
- External systems are accessed through interfaces in `application/ports.py`.
- All API changes update `packages/contracts` and contract tests.
- Any retrieval or prompt change requires an eval fixture or an explicit ADR.
- Never commit credentials, source documents, extracted sensitive text, or user PII.
- Use Ukrainian for product copy and English for identifiers and code comments.
- Run `make check` before handing off implementation work.

