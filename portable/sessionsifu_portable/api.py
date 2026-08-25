"""Bounded local stdio API for launchers and trusted desktop integrations.

There is deliberately no network listener.  A caller must start SessionSifu as the
current user and exchange one JSON object per line over inherited pipes.
"""

from __future__ import annotations

import json
import sys
from typing import TextIO

from . import VERSION
from .controller import SessionController

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESULTS = 100


class LocalApi:
    def __init__(self, controller: SessionController) -> None:
        self.controller = controller

    def dispatch(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        method = str(request.get("method") or "")[:64]
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
        if method == "status":
            return {
                "version": VERSION,
                "transport": "stdio",
                "privacy_recall_entries": self.controller.recall_store.entry_count(),
                "capabilities": ["recall.search", "restore.preview"],
            }
        if method == "recall.search":
            query = str(params.get("query") or "")[:512]
            application = str(params.get("application") or "")[:256]
            results = self.controller.search_recall(
                query,
                app=application,
                semantic=bool(params.get("related")),
            )[:MAX_RESULTS]
            # Result metadata and encrypted-vault identifiers are safe to return;
            # image bytes and vault keys never cross this boundary.
            return {"results": results, "count": len(results)}
        if method == "restore.preview":
            if "name" in params:
                plan = self.controller.plan_named(str(params["name"])[:64])
            elif "history" in params:
                history = self.controller.history()
                index = max(0, min(len(history) - 1, int(params["history"])))
                if not history:
                    plan = []
                else:
                    plan = self.controller.plan_path(history[index])
            else:
                raise ValueError("restore.preview requires name or history")
            return {"applications": plan}
        raise ValueError("unknown or write-capable method")


def serve_stdio(
    controller: SessionController,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    """Serve read-only requests until EOF; malformed requests do not end the service."""
    api = LocalApi(controller)
    for line in input_stream:
        if len(line.encode("utf-8", "replace")) > MAX_REQUEST_BYTES:
            response: dict[str, object] = {"ok": False, "error": "request is too large"}
        else:
            try:
                request = json.loads(line)
                request_id = request.get("id") if isinstance(request, dict) else None
                response = {"ok": True, "result": api.dispatch(request)}
                if request_id is not None:
                    response["id"] = request_id
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                response = {"ok": False, "error": str(error)[:512]}
        output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
        output_stream.flush()
    return 0
