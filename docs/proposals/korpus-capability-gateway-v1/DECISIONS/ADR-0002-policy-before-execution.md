# ADR-0002 — Policy Before External Execution
**Status:** PROPOSED

Resolve exact capability/resource/effect and obtain canonical KORPUS authorization before any
adapter call. Unknown, deny or policy-unavailable states produce zero external calls.
