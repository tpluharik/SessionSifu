"""Read-only Model Context Protocol adapter over inherited stdio pipes."""

from __future__ import annotations

import json
import sys
from typing import TextIO

MAX_MESSAGE_BYTES = 64 * 1024


class ReadOnlyMcp:
    def __init__(self, controller) -> None:
        self.controller = controller

    @staticmethod
    def tools() -> list[dict[str, object]]:
        return [
            {"name": "recall_search", "description": "Search local encrypted Recall metadata", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "application": {"type": "string"}, "related": {"type": "boolean"}}}},
            {"name": "recall_ask", "description": "Answer from local Recall results with citations", "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
            {"name": "restore_preview", "description": "Preview a named session without launching anything", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
            {"name": "restore_journal", "description": "Inspect recent restore outcomes", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "diagnostics", "description": "Read SessionSifu capability diagnostics", "inputSchema": {"type": "object", "properties": {}}},
        ]

    def call(self, name: str, arguments: dict[str, object]) -> object:
        if name == "recall_search":
            return self.controller.search_recall(
                str(arguments.get("query") or "")[:512],
                app=str(arguments.get("application") or "")[:256],
                semantic=bool(arguments.get("related")),
            )[:100]
        if name == "recall_ask":
            return self.controller.ask_recall(str(arguments.get("question") or "")[:512])
        if name == "restore_preview":
            return self.controller.plan_named(str(arguments.get("name") or "")[:64])
        if name == "restore_journal":
            return self.controller.restore_journal.list()
        if name == "diagnostics":
            return self.controller.diagnostics()
        raise ValueError("unknown or write-capable MCP tool")

    def dispatch(self, request: dict[str, object]) -> dict[str, object] | None:
        method = str(request.get("method") or "")
        identifier = request.get("id")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            result: object = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "sessionsifu", "version": self.controller.version}}
        elif method == "tools/list":
            result = {"tools": self.tools()}
        elif method == "tools/call":
            params = request.get("params") or {}
            if not isinstance(params, dict) or not isinstance(params.get("arguments", {}), dict):
                raise ValueError("invalid MCP tool request")
            result = {"content": [{"type": "text", "text": json.dumps(self.call(str(params.get("name") or ""), params.get("arguments") or {}), ensure_ascii=False)}]}
        elif method == "ping":
            result = {}
        else:
            raise ValueError("unsupported MCP method")
        return {"jsonrpc": "2.0", "id": identifier, "result": result}


def serve_mcp(controller, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> int:
    server = ReadOnlyMcp(controller)
    for line in input_stream:
        try:
            if len(line.encode("utf-8", "replace")) > MAX_MESSAGE_BYTES:
                raise ValueError("MCP message is too large")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("MCP request must be an object")
            response = server.dispatch(request)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": str(error)[:512]}}
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
            output_stream.flush()
    return 0
