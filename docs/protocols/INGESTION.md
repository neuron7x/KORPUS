# Document ingestion protocol

## State machine

```text
received → quarantined → scanned → extracted → metadata_reviewed
         → content_reviewed → approved → indexed
                              ↘ rejected
indexed → superseded | revoked → removed_from_serving
```

## Procedure

1. Register acquisition event, source URI, declared owner and rights basis.
2. Write original into quarantine with execution disabled.
3. Compute SHA-256 and inspect actual MIME independently of extension.
4. Malware-scan and content-disarm supported office/PDF formats. Never execute APK,
   EXE, LNK, macros, or embedded objects.
5. Detect exact and perceptual duplicates before OCR.
6. Extract text, layout, tables and page coordinates in a sandbox. Record tool/version
   and quality score. OCR low-confidence pages are flagged, not silently accepted.
7. Classify language, issuing authority, date, revision, platform, topic, access tier,
   risk class and validity.
8. A reviewer confirms metadata, provenance, rights and corpus eligibility.
9. A domain reviewer approves content. High-risk corpora require two reviewers.
10. Chunk semantically within document structure; never merge across versions.
11. Embed, lexical-index, run retrieval fixtures, and atomically promote the index.
12. Store a signed ingestion record and schedule revalidation.

## Rejection conditions

Unknown provenance without a documented exception; prohibited distribution; malware;
corrupt/incomplete file; no reliable extraction; superseded normative content presented
as current; or policy-incompatible high-risk material.

