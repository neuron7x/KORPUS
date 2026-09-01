"""JSON-RPC 2.0 по stdio — рівно стільки MCP, скільки треба трьом інструментам.

Без нової залежності НАВМИСНО. Дерево тримає замки з хешами й гейт постачання;
SDK заради ста рядків протоколу коштував би оновлення замків, нового постачальника
в інвентарі й ще однієї поверхні, яку доведеться поновлювати. Протокол тут —
`initialize`, `tools/list`, `tools/call` і повідомлення без відповіді.

Відмова НЕ маскується під результат. `tools/call`, що впав, повертає
`isError: true` з причиною: агент, який дістав порожній результат замість помилки,
запише у висновок відсутність, якої ніхто не міряв.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

from korpus.mcp.server import KorpusMcpServer, ToolFailure, build_tools, call_tool
from korpus.mcp.transport import TransportFailure

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "korpus"


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_content(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": False,
    }


def _tool_error(reason: str, *, retryable: bool) -> dict[str, Any]:
    # `retryable` названо окремо: «спробуй ще» і «підстави немає» — різні стани, і
    # злиття їх в одне повідомлення робить транспортну відмову схожою на відповідь.
    body = {"error": reason, "retryable": retryable}
    return {
        "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}],
        "isError": True,
    }


def handle(server: KorpusMcpServer, message: dict[str, Any]) -> dict[str, Any] | None:
    """Один запит — одна відповідь; повідомлення без `id` відповіді не мають."""
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "1"},
            },
        )
    if method in {"notifications/initialized", "initialized"}:
        return None
    if method == "tools/list":
        return _result(request_id, {"tools": build_tools(server)})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            return _result(request_id, _tool_content(call_tool(server, name, arguments)))
        except TransportFailure as failure:
            return _result(request_id, _tool_error(failure.reason, retryable=failure.retryable))
        except ToolFailure as failure:
            return _result(request_id, _tool_error(str(failure), retryable=False))
    if request_id is None:
        return None
    return _error(request_id, -32601, f"method not found: {method}")


def serve(
    server: KorpusMcpServer,
    stream_in: TextIO | None = None,
    stream_out: TextIO | None = None,
    on_line: Callable[[str], None] | None = None,
) -> None:
    source = stream_in or sys.stdin
    sink = stream_out or sys.stdout
    for raw in source:
        line = raw.strip()
        if not line:
            continue
        if on_line is not None:
            on_line(line)
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            sink.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            sink.flush()
            continue
        response = handle(server, message)
        if response is None:
            continue
        sink.write(json.dumps(response, ensure_ascii=False) + "\n")
        sink.flush()


__all__ = ["PROTOCOL_VERSION", "SERVER_NAME", "handle", "serve"]
