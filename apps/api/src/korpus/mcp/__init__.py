"""КОРПУС як інструмент для агента: MCP поверх власного HTTP-API."""

from korpus.mcp.server import KorpusMcpServer, ToolFailure, build_tools

__all__ = ["KorpusMcpServer", "ToolFailure", "build_tools"]
