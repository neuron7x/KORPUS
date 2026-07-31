# ADR-0004: Enforce access before retrieval

Status: accepted

## Decision

Derive authorized corpora server-side and filter before both lexical and vector search.
Maintain separate indexes/object buckets for restricted tiers where practical.

## Rationale

Post-generation redaction cannot reliably undo disclosure to a model or logs.

