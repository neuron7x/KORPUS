# ADR-0003: Provider-independent model ports

Status: accepted

## Decision

Use application ports for generation, embeddings, reranking and transcription. Keep
model IDs in environment/configuration and version every effective run.

## Rationale

Quality, latency, cost, regional controls and availability change independently. A
single provider may be used initially without becoming domain architecture.

