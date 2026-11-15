from __future__ import annotations
import asyncio
from collections import deque
from typing import Protocol
from .packet import EventPacket, RuntimeDescriptor, HealthSnapshot

class RuntimeAdapter(Protocol):
    async def start(self): ...
    async def stop(self): ...
    async def submit(self, packet: EventPacket): ...
    def health(self): ...

class RuntimeManager:
    def __init__(self, capacity=8): self.capacity=capacity; self.runtimes={}; self.queues={}; self.tasks={}; self.dropped={}; self.errors={}; self.lock=asyncio.Lock()
    async def register(self,name,adapter,descriptor):
        if name in self.runtimes: raise ValueError('runtime already registered')
        self.runtimes[name]=descriptor; self.queues[name]=deque(maxlen=self.capacity); self.dropped[name]=0; self.errors[name]=[]; await adapter.start(); self.tasks[name]=asyncio.create_task(self._drain(name,adapter))
    async def _drain(self,name,adapter):
        while name in self.runtimes:
            if not self.queues[name]: await asyncio.sleep(.001); continue
            packet=self.queues[name].popleft()
            try: await adapter.submit(packet)
            except asyncio.CancelledError: raise
            except Exception as exc: self.errors[name].append(str(exc)); self.errors[name]=self.errors[name][-16:]
    async def submit(self,name,packet):
        if name not in self.runtimes: raise KeyError(name)
        queue=self.queues[name]
        if len(queue) >= self.capacity: queue.popleft(); self.dropped[name]+=1
        queue.append(packet)
    async def close(self,name):
        task=self.tasks.pop(name,None)
        if task: task.cancel(); await asyncio.gather(task,return_exceptions=True)
        self.runtimes.pop(name,None); self.queues.pop(name,None)
    def health(self,name):
        descriptor=self.runtimes[name]; return HealthSnapshot(name,'ready' if descriptor.ready else 'not_ready',len(self.queues[name]),self.capacity,self.dropped[name],descriptor=descriptor,errors=list(self.errors[name]))
