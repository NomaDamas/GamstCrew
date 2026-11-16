from __future__ import annotations
import asyncio
import json
import platform
from dataclasses import dataclass, field
from typing import Any, Mapping
from .packet import (
    EventPacket,
    MAX_PACKET_BYTES,
    PacketIntegrityCounter,
)
from .host_limits import HostLimitController, HostLimitError, HostLimitReport
from .resources import ResourceRequest


@dataclass
class ProcessRuntime:
    argv: tuple[str, ...]
    descriptor: object
    max_line: int = MAX_PACKET_BYTES
    process: asyncio.subprocess.Process | None = None
    integrity_counter: PacketIntegrityCounter = field(default_factory=PacketIntegrityCounter)
    host_controller: HostLimitController | None = None
    resource_request: ResourceRequest | None = None
    host_limit_report: HostLimitReport | None = None

    def configure_host_limits(self, controller: HostLimitController | None,
                              request: ResourceRequest | None) -> None:
        if controller is not None and not isinstance(controller, HostLimitController):
            raise TypeError("host_controller must be a HostLimitController")
        if request is not None and not isinstance(request, ResourceRequest):
            raise TypeError("resource_request must be a ResourceRequest")
        if self.process is not None:
            raise RuntimeError("host limits must be configured before start")
        self.host_controller = controller
        self.resource_request = request

    async def _read_line(self):
        try:
            return await self.process.stdout.readuntil(b"\n")
        except asyncio.LimitOverrunError as exc:
            raise ValueError("runtime line exceeds line budget") from exc
        except asyncio.IncompleteReadError as exc:
            if not exc.partial:
                return b""
            raise ValueError("runtime returned a truncated line") from exc

    async def start(self):
        if not self.argv:
            raise ValueError("runtime argv cannot be empty")
        self.process = await asyncio.create_subprocess_exec(
            *self.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self.max_line,
        )
        try:
            if self.host_controller is not None:
                request = self.resource_request or ResourceRequest()
                self.host_limit_report = self.host_controller.attach(self.process.pid, request)
            ready = await asyncio.wait_for(self._read_line(), 5)
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

    async def submit(self, packet: EventPacket | Mapping[str, Any] | bytes):
        if self.process is None or self.process.returncode is not None:
            raise RuntimeError("runtime is not running")
        if isinstance(packet, EventPacket):
            parsed = EventPacket.from_bytes(
                packet.to_bytes(), counter=self.integrity_counter
            )
            payload = parsed.to_dict()
        elif isinstance(packet, (bytes, bytearray, memoryview)):
            parsed = EventPacket.from_bytes(packet, counter=self.integrity_counter)
            payload = parsed.to_dict()
        elif isinstance(packet, Mapping):
            parsed = EventPacket.from_dict(packet, counter=self.integrity_counter)
            payload = parsed.to_dict()
        else:
            raise TypeError("runtime packet must be an EventPacket or packet mapping")
        raw = (
            json.dumps(
                {"type": "packet", "packet": payload},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        if len(raw) > self.max_line:
            raise ValueError("runtime packet exceeds line budget")
        self.process.stdin.write(raw)
        await self.process.stdin.drain()
        response = await asyncio.wait_for(self._read_line(), 5)
        if not response:
            raise RuntimeError("runtime closed stdout")
        if len(response) > self.max_line:
            raise ValueError("runtime response exceeds line budget")
        return json.loads(response)

    async def stop(self):
        if self.process is None:
            return
        process, self.process = self.process, None
        try:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        finally:
            if self.host_controller is not None and self.process is None:
                try:
                    self.host_limit_report = self.host_controller.detach(process.pid)
                except HostLimitError as exc:
                    # Shutdown must not mask the original startup/stop failure.
                    self.host_limit_report = HostLimitReport(
                        self.host_controller.mode,
                        "unavailable",
                        (self.host_controller.system or platform.system()).lower(),
                        str(exc),
                    )
            process._transport.close()

    def health(self):
        return {
            "running": self.process is not None and self.process.returncode is None,
            "returncode": None if self.process is None else self.process.returncode,
            "integrity_rejected": self.integrity_counter.integrity_rejected,
            "host_limits": None if self.host_limit_report is None else self.host_limit_report.as_dict(),
        }
