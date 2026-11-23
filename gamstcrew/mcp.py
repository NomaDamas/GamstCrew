"""Dependency-free MCP stdio server for explicit GamstCrew setup operations."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from .setup import apply_plan, make_plan

PROTOCOL_VERSION = "2025-03-26"
MAX_MESSAGE_BYTES = 4 * 1024 * 1024

TOOLS = [
    {
        "name": "plan_setup",
        "description": "Detect hardware and resolve GAMST goals, role dependencies, model defaults/overrides, install packages, resource totals and warnings. Does not install anything.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goals": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "overrides": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["goals"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_setup",
        "description": "Apply exactly a version 1 plan from plan_setup: create planned virtual environments, install planned packages, verify pinned weight SHA256 digests, and write the GAMST profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object"},
                "plan_path": {"type": "string"},
                "prefix": {"type": "string"},
                "profile": {"type": "string"},
            },
            "anyOf": [{"required": ["plan"]}, {"required": ["plan_path"]}],
            "additionalProperties": False,
        },
    },
]


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(value):
    text = json.dumps(value, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "structuredContent": value}


def _call_tool(arguments):
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    name = arguments.pop("name", None)
    values = arguments.pop("arguments", {})
    if not isinstance(values, dict):
        raise ValueError("tool arguments must be an object")
    if name == "plan_setup":
        if set(values) - {"goals", "overrides"} or "goals" not in values:
            raise ValueError("plan_setup requires goals and optional overrides only")
        return _tool_result(make_plan(values["goals"], values.get("overrides", {})))
    if name == "apply_setup":
        if set(values) - {"plan", "plan_path", "prefix", "profile"}:
            raise ValueError("unknown apply_setup argument")
        if ("plan" in values) == ("plan_path" in values):
            raise ValueError("supply exactly one of plan or plan_path")
        plan = values.get("plan")
        if "plan_path" in values:
            plan = json.loads(Path(values["plan_path"]).expanduser().read_text(encoding="utf-8"))
        return _tool_result(apply_plan(plan, prefix=values.get("prefix"), profile_path=values.get("profile")))
    raise ValueError("unknown tool: " + str(name))


def handle_message(message):
    """Handle one JSON-RPC message; notifications intentionally return None."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "invalid JSON-RPC request")
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "gamstcrew-setup", "version": "1"},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        try:
            return _result(request_id, _call_tool(dict(message.get("params") or {})))
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            return _result(request_id, {"content": [{"type": "text", "text": str(error)}], "isError": True})
    return _error(request_id, -32601, "method not found")


def serve(stdin=None, stdout=None):
    """Serve newline-delimited MCP JSON-RPC messages until EOF."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    for line in stdin:
        if len(line) > MAX_MESSAGE_BYTES:
            response = _error(None, -32600, "message exceeds 4 MiB")
        else:
            try:
                message = json.loads(line)
                response = handle_message(message)
            except (UnicodeDecodeError, json.JSONDecodeError):
                response = _error(None, -32700, "parse error")
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            stdout.flush()


def main():
    serve()


if __name__ == "__main__":
    main()
