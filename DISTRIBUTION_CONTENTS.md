# KORPUS v0.9.7 distribution contract

This release is constructed from one **gitless canonical source snapshot** inside the ChatGPT
execution environment. The source boundary is byte-inventoried by `SOURCE_MANIFEST.json`; no Git
commit or historical branch identity is invented. The final recovery envelope contains the clean
source tree plus the byte-preserved uploaded predecessor under `LINEAGE/`, so provenance recovery
does not require contaminating the source tree with a nested archive.

Generated local assurance evidence is explicitly identified as local and cannot satisfy predicates
that require independent assessment, production-like PostgreSQL, a trusted hosted builder or exact
deployment attestation. `reports/PRODUCTION_ASSURANCE_REPORT.json` remains the production authority.
