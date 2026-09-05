# ADR-0001 — Additive Gateway in the Modular Monolith
**Status:** PROPOSED

Implement v1 as an additive application-layer module in the existing modular monolith. Do not
extract a service until KORPUS' own extraction criteria are met. This minimizes transaction,
authorization and operational drift while preserving a clear adapter port.
