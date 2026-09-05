# OpenClaw Current Verification Snapshot — 2026-09-05

**Class:** `FACT_EXTERNAL_CURRENT`  
**Purpose:** freeze the external facts actually checked while writing this proposal. These facts are not timeless; implementation MUST reverify them.

---

## 1. Gateway protocol

Official source:
- https://docs.openclaw.ai/gateway/protocol

Verified snapshot:
- OpenClaw documents the Gateway WebSocket protocol as the single control plane and node transport for operator/node clients.
- clients declare role and scope during handshake.
- current documentation reports verified stable package release `2026.8.1` for `@openclaw/gateway-protocol` and `@openclaw/gateway-client`.
- package release version and wire protocol version are distinct concepts.

Integration consequence:

```text
pin client/protocol versions
record wire version
validate compatibility explicitly
```

Do not equate same package release with guaranteed compatibility across arbitrary Gateway releases.

---

## 2. Gateway client packages

Official source:
- https://docs.openclaw.ai/gateway/clients

Verified snapshot:
- exact package pins are documented for `2026.8.1`.
- the client/protocol packages export versioned schemas/types/validators and client behavior.
- device identity/signing/token storage remain host-owned dependencies in client usage.

Integration consequence:
- implementation should pin exact tested package versions where a native Gateway client is used;
- test reconnect/auth/version behavior as part of compatibility matrix.

---

## 3. OpenClaw MCP directions

Official source:
- https://docs.openclaw.ai/cli/mcp

Verified snapshot:

`openclaw mcp` has two materially different roles.

### Direction A — OpenClaw as MCP server

```text
external MCP client
 -> openclaw mcp serve
 -> OpenClaw Gateway
 -> routed OpenClaw conversations
```

`openclaw mcp serve` is documented as a stdio MCP server bridge to local/remote Gateway sessions.

### Direction B — OpenClaw managing outbound MCP servers

```text
OpenClaw agent/runtime
 -> OpenClaw-managed mcp.servers registry
 -> external MCP server
```

This is the primary direction for Phase A KORPUS evidence-tool integration.

OpenClaw documents management commands including `add`, `set`, `configure`, `tools`, `status`, `doctor`, `probe`, `login`, `logout`, `reload` and `unset` for managed MCP definitions.

Integration consequence:

```text
KORPUS Phase A:
OpenClaw runtime -> KORPUS MCP server
```

Do not confuse that with exposing OpenClaw itself as an MCP server.

---

## 4. MCP bridge security note

Official OpenClaw MCP documentation states that OpenClaw’s MCP conversation bridge uses existing Gateway route metadata rather than inventing routing.

That is useful operationally but does not change KORPUS authority:

```text
OpenClaw route valid
!=
KORPUS subject authorized
```

---

## 5. Multi-agent routing

Official source:
- https://docs.openclaw.ai/multi-agent

Verified snapshot:
- multiple isolated agents can exist in one Gateway process;
- agents have separate workspace, state/auth profiles and session stores;
- bindings route channel accounts/peers to agents.

Integration consequence:

```text
OpenClaw agent isolation = useful orchestration separation
OpenClaw agent isolation != independent external assurance
```

---

## 6. Node model

Official sources:
- https://github.com/openclaw/openclaw/blob/main/docs/nodes/index.md
- https://docs.openclaw.ai/gateway/protocol

Verified snapshot:
- nodes connect as role `node` and expose command surfaces;
- device pairing is part of node lifecycle;
- node commands may include device/system/media capabilities depending on host/platform;
- nodes are peripherals, not Gateways;
- channel messages land on the Gateway rather than directly on nodes.

Integration consequence:

```text
NodePaired != KORPUSCapabilityAuthorized
NodeCommandAvailable != KORPUSMayInvoke
```

---

## 7. Node-hosted MCP

Official source:
- https://github.com/openclaw/openclaw/blob/main/docs/nodes/index.md

Verified snapshot:
- current node-host documentation supports MCP servers configured on the node machine;
- node-host publishes MCP tool descriptors and routes calls through the Gateway/node command path;
- Gateway-side controls can disable plugin tools or deny exact node command families.

Integration consequence:
- node-hosted KORPUS MCP is technically a possible topology;
- it is **not** the default recommendation unless KORPUS runtime locality requires it;
- node pairing and OpenClaw tool policy remain defense in depth, not KORPUS authorization.

---

## 8. Tool policy / sandbox

Official source:
- https://docs.openclaw.ai/gateway/config-tools

Verified snapshot:
- OpenClaw supports tool profiles/allowlists/denies;
- configured MCP servers may appear as plugin-owned tools;
- sandbox tool policy adds another visibility/execution gate.

Integration consequence:

```text
EffectiveToolAvailability = OpenClawPolicy ∩ KORPUSPolicy
```

where KORPUS policy remains authoritative for KORPUS actions.

---

## 9. Official OpenClaw topology summary

Official source:
- https://docs.openclaw.ai/

Current public documentation depicts:

```text
channels/apps/plugins
 -> Gateway
 -> agent runtime / CLI / Control UI / companion apps / nodes
```

The Gateway is the source of truth for OpenClaw sessions/routing/channel connections.

This statement is about OpenClaw’s own orchestration state, not KORPUS evidence or policy truth.

---

## 10. MCP specification security context

Official source checkpoint:
- https://modelcontextprotocol.io/specification/2025-06-18

The MCP specification explicitly treats tools as potentially powerful code-execution surfaces and states that tool descriptions/annotations require appropriate caution; authorization/consent/data protection are host-application responsibilities.

Integration consequence:

```text
MCP schema/description = interoperability metadata
MCP schema/description != KORPUS authority
```

---

## 11. Current implementation assumption set

As of this snapshot, a valid Phase A design may assume only:

```text
A1 OpenClaw can manage outbound MCP server definitions.
A2 KORPUS already exposes a local MCP evidence tool server.
A3 OpenClaw can route channel/session input to an agent runtime.
A4 OpenClaw tool policy can narrow tool availability.
A5 KORPUS independently authenticates/authorizes its API/MCP-backed operations.
```

Everything else is an implementation choice or hypothesis.

---

## 12. Facts NOT established by external docs

OpenClaw documentation does not prove:
- KORPUS authorization correctness;
- KORPUS evidence correctness;
- safe classification of KORPUS data for a channel/node;
- side-effect idempotency of future KORPUS capabilities;
- correctness of route→KORPUS subject binding;
- production safety of this proposal.

Those require local design + executable KORPUS evidence.

---

## 13. Reverification trigger

Re-run external verification when any of these change:

```text
OpenClaw release
Gateway protocol version
Gateway client/protocol package version
MCP CLI/config semantics
node-host MCP semantics
tool policy semantics
channel or node feature used by integration
```

Result classification:

```text
CONFIRMED
CHANGED_COMPATIBLE
CHANGED_BREAKING
UNKNOWN
```

Any material `UNKNOWN` blocks implementation assumption from being promoted to release truth.
