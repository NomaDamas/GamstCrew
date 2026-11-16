from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass
from .packet import EventPacket, MAX_PACKET_BYTES


@dataclass
class ProcessRuntime:
    argv: tuple[str, ...]
    descriptor: object
    max_line: int = MAX_PACKET_BYTES
    process: asyncio.subprocess.Process | None = None

    async def start(self):
        if not self.argv:
            raise ValueError("runtime argv cannot be empty")
        self.process = await asyncio.create_subprocess_exec(
            *self.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            ready = await asyncio.wait_for(self.process.stdout.readline(), 5)
            if not ready:
                raise RuntimeError("runtime exited before readiness")
            message = json.loads(ready)
            if message.get("type") != "ready":
                raise RuntimeError("runtime readiness message required")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            await self.stop()
            raise RuntimeError("runtime readiness must be JSON") from exc
        except BaseException:
            await self.stop()
            raise

    async def submit(self, packet: EventPacket):
        if self.process is None or self.process.returncode is not None:
            raise RuntimeError("runtime is not running")
        raw = (
            json.dumps(
                {"type": "packet", "packet": json.loads(packet.json())},
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        if len(raw) > self.max_line:
            raise ValueError("runtime packet exceeds line budget")
        self.process.stdin.write(raw)
        await self.process.stdin.drain()
        response = await asyncio.wait_for(self.process.stdout.readline(), 5)
        if not response:
            raise RuntimeError("runtime closed stdout")
        if len(response) > self.max_line:
            raise ValueError("runtime response exceeds line budget")
        return json.loads(response)

    async def stop(self):
        if self.process is None:
            return
        process, self.process = self.process, None
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        elif process.returncode is None:
            await process.wait()

    def health(self):
        return {
            "running": self.process is not None and self.process.returncode is None,
            "returncode": None if self.process is None else self.process.returncode,
        }
