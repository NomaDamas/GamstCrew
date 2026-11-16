from __future__ import annotations
import asyncio
from collections import deque
from typing import Protocol
from .packet import EventPacket, HealthSnapshot
from .resources import ResourceAllocator, ResourceRequest


class RuntimeAdapter(Protocol):
    async def start(self): ...
    async def stop(self): ...
    async def submit(self, packet: EventPacket): ...
    def health(self): ...


class RuntimeManager:
    def __init__(self, capacity=8, *, resource_allocator=None):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.runtimes = {}
        self.adapters = {}
        self.queues = {}
        self.tasks = {}
        self.dropped = {}
        self.errors = {}
        self.lock = asyncio.Lock()
        if resource_allocator is not None and not isinstance(resource_allocator, ResourceAllocator):
            raise TypeError("resource_allocator must be a ResourceAllocator")
        self.resource_allocator = resource_allocator
        self.resource_reservations = {}

    async def register(self, name, adapter, descriptor, *, resources=None):
        if name in self.runtimes:
            raise ValueError("runtime already registered")
        reservation = None
        if resources is not None:
            if self.resource_allocator is None:
                raise ValueError("resource allocator required for runtime resources")
            if not isinstance(resources, ResourceRequest):
                raise TypeError("resources must be a ResourceRequest")
            reservation = self.resource_allocator.reserve(resources, owner=name)
        try:
            await adapter.start()
        except BaseException:
            try:
                await adapter.stop()
            finally:
                if reservation is not None:
                    self.resource_allocator.release(reservation)
            raise
        self.runtimes[name] = descriptor
        self.adapters[name] = adapter
        self.queues[name] = deque(maxlen=self.capacity)
        self.dropped[name] = 0
        self.errors[name] = []
        if reservation is not None:
            self.resource_reservations[name] = reservation
        self.tasks[name] = asyncio.create_task(
            self._drain(name), name="gamstcrew:" + name
        )

    async def register_process(self, name, process_runtime, *, resources=None):
        """Register an explicit subprocess runtime using descriptor metadata."""
        return await self.register(
            name, process_runtime, process_runtime.descriptor, resources=resources
        )

    def resource_telemetry(self):
        """Return allocator telemetry, or an explicit disabled state."""
        if self.resource_allocator is None:
            return {"enabled": False}
        value = self.resource_allocator.telemetry()
        value["enabled"] = True
        return value

    async def _drain(self, name):
        adapter = self.adapters[name]
        while name in self.runtimes:
            if not self.queues[name]:
                await asyncio.sleep(0.001)
                continue
            packet = self.queues[name].popleft()
            try:
                await adapter.submit(packet)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors[name].append(str(exc))
                self.errors[name] = self.errors[name][-16:]

    async def submit(self, name, packet):
        if name not in self.runtimes:
            raise KeyError(name)
        queue = self.queues[name]
        if len(queue) >= self.capacity:
            queue.popleft()
            self.dropped[name] += 1
        queue.append(packet)

    async def close(self, name):
        task = self.tasks.pop(name, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        adapter = self.adapters.pop(name, None)
        try:
            if adapter:
                await adapter.stop()
        finally:
            reservation = self.resource_reservations.pop(name, None)
            if reservation is not None:
                self.resource_allocator.release(reservation)
            self.runtimes.pop(name, None)
            self.queues.pop(name, None)

    def health(self, name):
        descriptor = self.runtimes[name]
        adapter_health = self.adapters[name].health()
        running = adapter_health.get("running") if isinstance(adapter_health, dict) else None
        status = "crashed" if running is False else "ready" if descriptor.ready else "not_ready"
        return HealthSnapshot(
            name,
            status,
            len(self.queues[name]),
            self.capacity,
            self.dropped[name],
            errors=list(self.errors[name]),
            descriptor=descriptor,
            integrity_rejected=(
                adapter_health.get("integrity_rejected", 0)
                if isinstance(adapter_health, dict) else 0
            ),
        )
