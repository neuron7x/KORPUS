# OpenClaw Facts and References

**Research snapshot:** 2026-09-05.  
This document records external facts used by the proposal. Re-verify them before implementation because OpenClaw is an actively evolving project.

## 1. Gateway

OpenClaw documents its Gateway as the central control plane for operator and node clients. CLI, web UI, macOS application, iOS/Android nodes and headless nodes connect through the Gateway protocol over WebSocket and declare role/scope during handshake.

Operationally, the Gateway is described as an always-on process for routing, control-plane functions and channel connections, with WebSocket control/RPC plus HTTP surfaces and hooks.

**Integration consequence:** KORPUS may use the Gateway as OpenClaw's routing/control transport, but KORPUS authorization remains local.

References:
- https://docs.openclaw.ai/gateway/protocol
- https://github.com/openclaw/openclaw/blob/main/docs/gateway/index.md

At the time of this research, the Gateway protocol documentation reported `@openclaw/gateway-protocol` / `@openclaw/gateway-client` stable package release `2026.8.1`. Pin or verify an implementation-time version; do not embed this research version as an eternal compatibility claim.

## 2. MCP

OpenClaw currently exposes an MCP mode through `openclaw mcp serve`. The documented bridge runs as a stdio MCP server, connects to an OpenClaw Gateway over WebSocket, and exposes routed channel conversations/session functions to the MCP client.

OpenClaw documentation also describes an outbound MCP server registry for MCP servers that OpenClaw runtimes may consume.

**Integration consequence:** there are two distinct MCP directions that must not be confused:

```text
A. OpenClaw acting as MCP server
   external MCP client -> OpenClaw

B. OpenClaw consuming/managing MCP servers
   OpenClaw runtime -> external MCP server (e.g. KORPUS)
```

KORPUS v1 primarily needs direction B: OpenClaw consumes KORPUS MCP evidence tools.

References:
- https://docs.openclaw.ai/cli/mcp
- https://github.com/openclaw/openclaw/blob/main/docs/cli/mcp.md

## 3. Channels

OpenClaw supports multiple messaging channels/plugins and routes conversations through the Gateway. Current public documentation includes channels such as Discord, Google Chat, iMessage, Matrix, Microsoft Teams, Signal, Slack, Telegram, WhatsApp, Zalo and others.

**Integration consequence:** channel identity and KORPUS identity are distinct. A channel route is a delivery/routing fact, not KORPUS authorization.

References:
- https://docs.openclaw.ai/
- https://github.com/openclaw/openclaw/blob/main/src/channels/AGENTS.md

## 4. Multi-agent routing

OpenClaw documents multiple isolated agents within one Gateway process, with separate workspaces, state directories/auth profiles and session history. Channel accounts can be bound to particular agents.

**Integration consequence:** OpenClaw can provide orchestration-level separation, but KORPUS must independently enforce authorization and evidence boundaries. Separate OpenClaw agents are not automatically independent assurance parties.

Reference:
- https://github.com/openclaw/openclaw/blob/main/docs/concepts/multi-agent.md

## 5. Nodes/devices

OpenClaw documentation describes remote/pairable nodes connected to the Gateway, and node tools used for device-side capabilities such as screen/camera/system interactions depending on platform/configuration.

**Integration consequence:** node capability does not imply permission to receive restricted KORPUS data. Device actions require separate KORPUS policy/effect reasoning where KORPUS-protected material or actions are involved.

Reference:
- https://github.com/openclaw/openclaw/blob/main/docs/help/faq.md

## 6. Tool profiles and groups

OpenClaw configuration documentation describes tool profiles/groups for runtime, filesystem, sessions, web, UI, automation, messaging, nodes, agents, media, OpenClaw built-ins and plugins. Configured MCP servers can be exposed through MCP/plugin tooling depending on profile/configuration.

**Integration consequence:** OpenClaw's own tool allow/deny system is useful defense-in-depth, but it must not replace KORPUS capability authorization. Use both:

```text
OpenClaw tool policy = orchestration-side least privilege
KORPUS policy        = authoritative KORPUS permission/effect boundary
```

Reference:
- https://github.com/openclaw/openclaw/blob/main/docs/gateway/config-tools.md

## 7. ACP/plugin-tool bridge

OpenClaw documentation describes an ACPX plugin-tools MCP bridge for exposing installed plugin tools to ACP harness sessions when enabled.

**Integration consequence:** future coding-agent workflows could gain KORPUS tools through an OpenClaw-managed bridge, but this proposal does not depend on ACP and does not grant generic production code execution.

Reference:
- https://github.com/openclaw/openclaw/blob/main/docs/tools/acp-agents-setup.md

## 8. KORPUS facts used by this proposal

At proposal creation, KORPUS `main` contains:
- an MCP server under `apps/api/src/korpus/mcp/`;
- `scripts/run_mcp_server.py` requiring `MCP_KORPUS_TOKEN` and using the KORPUS HTTP API;
- evidence-oriented MCP tools including `korpus_ask`, `korpus_grounds`, `korpus_quote` and `korpus_verify`;
- an architecture where API/worker is the protected backend plane and web/PWA is a consumer/operator surface;
- canonical authorization/evidence/audit semantics in KORPUS rather than the browser or external agent.

The separate draft Capability Gateway PR #44 contains a generalized MCP/HTTP/internal adapter theory, but it is not merge-ready and is not modified by this OpenClaw proposal.

## 9. Claims deliberately not made

This proposal does **not** claim that:
- every OpenClaw channel has identical security semantics;
- current OpenClaw APIs are stable indefinitely;
- OpenClaw itself proves KORPUS authorization;
- OpenClaw session history is admissible KORPUS evidence;
- OpenClaw nodes are safe for restricted KORPUS material by default;
- MCP authentication equals action authorization;
- PR #44 is production-ready;
- this documentation proves an implemented integration.

## 10. Re-verification rule

Before implementation, record:

```text
OpenClaw release/version
Gateway protocol/schema version/digest
relevant MCP configuration semantics
required channel/node feature versions
KORPUS exact source SHA/digest
```

If implementation assumptions differ from this research snapshot, update the proposal or adapt the integration rather than silently preserving stale assumptions.
