# Implementation Target Map

## Preferred shape

Keep v1 inside the existing API modular monolith. A likely additive shape is:

```text
apps/api/src/korpus/application/capability_gateway/
    types.py
    contracts.py
    registry.py
    policy.py
    invoke.py
    evidence.py
    effects.py
    errors.py

apps/api/src/korpus/infrastructure/integrations/
    base.py
    internal.py
    http.py
    mcp.py   # only when MCP profile is implemented
```

This is a target map, not permission to ignore live repository conventions.

## Mandatory live seam map

Before creating files, identify exact current:
identity; authorization; egress; request audit context; audit append; evidence admission;
transaction/unit-of-work; configuration/secrets; bootstrap/DI; telemetry; release identity.

Prefer existing abstractions over duplicate ones.

## Dependency posture

The baseline already has Pydantic, `httpx`, OpenTelemetry, Prometheus, FastAPI and SQLAlchemy.
The first core/HTTP slice should not need a new runtime dependency. MCP SDK adoption is a
separate implementation ADR; gateway core must remain protocol-independent.
