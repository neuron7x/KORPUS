# ADR-0001: Begin with a modular monolith

Status: accepted

## Decision

Use one deployable API with domain modules and explicit ports. Run ingestion as a
separate worker process from the same codebase. Split deployments only for measured
scaling, data-isolation, or failure-containment requirements.

## Rationale

The small team needs transactional consistency, fast iteration and low operational
load. Microservices would create distributed failure modes before domain boundaries
and traffic are known.

