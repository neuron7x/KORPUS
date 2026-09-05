# MCP and External Adapter Model

MCP is a protocol adapter, not a KORPUS authority plane.

```text
KORPUS Gateway -> MCP Adapter -> MCP Client Session -> MCP Server -> Tool/Resource
```

## Discovery

Remote name/description/schema/annotations are `DISCOVERED_UNTRUSTED`. A local mapping owns:
- stable KORPUS capability id/version;
- effect class;
- authorization action/resource;
- egress/data policy;
- evidence profile;
- timeout/retry/idempotency;
- approved description.

Tool descriptions and resource text remain data; they do not enter privileged instruction
channels merely because an MCP server supplied them.

## Authorization

MCP OAuth/token authorization controls MCP transport/resource access. It does not answer
whether the current KORPUS subject may perform the logical action.

`MCP token valid != KORPUS action authorized`.

## Schema drift

Record provider/server identity and tool schema digests. Incompatible or authority-widening
drift disables/quarantines the local mapping. Never silently convert a read tool into a write
or broader-data capability.

## HTTP/OpenAPI

OpenAPI can bootstrap a draft mapping but cannot create local authority. Provider URL,
redirect, body size, timeout and credentials are server-side policy/configuration.

## Core isolation

The gateway core must not import MCP-specific types. MCP remains one adapter behind the same
port as internal and HTTP providers.
