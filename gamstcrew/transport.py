from __future__ import annotations
import asyncio
import json
import os
import tempfile
from .packet import MAX_PACKET_BYTES


class JsonlUnixServer:
    def __init__(self, handler, path=None, max_line=MAX_PACKET_BYTES,
                 handler_timeout_s=30.0):
        self.handler, self.path, self.max_line, self.server = (
            handler,
            path or tempfile.mktemp(prefix="gamstcrew-", suffix=".sock"),
            max_line,
            None,
        )
        if type(handler_timeout_s) not in (int, float) or handler_timeout_s <= 0:
            raise ValueError("handler_timeout_s must be positive")
        self.handler_timeout_s = float(handler_timeout_s)

    async def start(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        # StreamReader's line limit bounds buffering before a delimiter arrives.
        self.server = await asyncio.start_unix_server(
            self._client, self.path, limit=self.max_line
        )

    async def _client(self, reader, writer):
        try:
            while True:
                try:
                    line = await reader.readuntil(b"\n")
                except asyncio.LimitOverrunError as exc:
                    raise ValueError("line exceeds transport bound") from exc
                except asyncio.IncompleteReadError as exc:
                    if not exc.partial:
                        break
                    raise ValueError("truncated transport line") from exc
                if not line:
                    break
                if len(line) > self.max_line or not line.endswith(b"\n"):
                    raise ValueError("line exceeds transport bound")
                request = json.loads(line)
                response = await asyncio.wait_for(
                    self.handler(request), timeout=self.handler_timeout_s
                )
                raw = (
                    json.dumps(
                        response,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ).encode()
                    + b"\n"
                )
                if len(raw) > self.max_line:
                    raise ValueError("response exceeds transport bound")
                writer.write(raw)
                await writer.drain()
        except (ValueError, json.JSONDecodeError, asyncio.TimeoutError) as exc:
            writer.write(json.dumps({"error": str(exc)}).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


async def jsonl_call(path, request, max_line=MAX_PACKET_BYTES, timeout_s=30.0):
    if type(timeout_s) not in (int, float) or timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    reader, writer = await asyncio.open_unix_connection(path, limit=max_line)
    try:
        raw = json.dumps(request, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        if len(raw) > max_line:
            raise ValueError("request exceeds transport bound")
        writer.write(raw)
        await asyncio.wait_for(writer.drain(), timeout=timeout_s)
        try:
            response = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=timeout_s)
        except asyncio.LimitOverrunError as exc:
            raise ValueError("response exceeds transport bound") from exc
        if len(response) > max_line:
            raise ValueError("response exceeds transport bound")
        return json.loads(response)
    finally:
        writer.close()
        await writer.wait_closed()
