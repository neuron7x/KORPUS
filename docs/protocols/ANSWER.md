# Evidence-bound answer protocol

1. Authenticate and derive allowed corpora server-side.
2. Classify question domain, intent, risk, temporal sensitivity and missing qualifiers.
3. Clarify material ambiguity (role, platform, edition) before answering.
4. Retrieve only approved, valid, authorized evidence.
5. Prefer current authoritative sources and expose conflicts.
6. Require evidence threshold; otherwise return `insufficient_evidence`.
7. Generate structured claims referencing evidence IDs only.
8. Verify each externally checkable claim has supporting evidence.
9. Block answers containing unauthorized evidence or unsupported claims.
10. Display answer, citations, revision, confidence and limitations.
11. Record trace IDs and minimized telemetry; collect correction feedback.

The generator may paraphrase but may not introduce procedures, numbers, exceptions,
or conclusions absent from eligible evidence.

