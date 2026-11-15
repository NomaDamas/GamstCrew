from __future__ import annotations
import statistics
from dataclasses import dataclass
from .packet import EventPacket

@dataclass(frozen=True)
class ClockStatus:
    source_clock: str; calibrated: bool; samples: int; offset_ms: float | None; drift: float | None; residual_ms: float | None

class TemporalAligner:
    def __init__(self, min_samples=8, max_samples=128):
        if type(min_samples) is not int or min_samples < 2 or type(max_samples) is not int or max_samples < min_samples: raise ValueError('invalid sample bounds')
        self.min_samples, self.max_samples = min_samples, max_samples; self.samples = {}; self.events = {}
    def add_clock_sample(self, clock, source_ms, monotonic_ms):
        if type(source_ms) is not int or type(monotonic_ms) is not int: raise ValueError('clock values must be integers')
        values = self.samples.setdefault(clock, []); values.append((source_ms, monotonic_ms)); del values[:-self.max_samples]
    def status(self, clock):
        values = self.samples.get(clock, [])
        if len(values) < self.min_samples: return ClockStatus(clock, False, len(values), None, None, None)
        x0, y0 = values[0]; dx=[x-x0 for x,_ in values]; dy=[y-y0 for _,y in values]; den=sum(x*x for x in dx); slope=sum(x*y for x,y in zip(dx,dy))/den if den else 1
        offset=statistics.mean(y-slope*x for x,y in values); residual=statistics.mean(abs(y-(offset+slope*x)) for x,y in values)
        return ClockStatus(clock, True, len(values), offset, slope-1, residual)
    def accept(self, event):
        old=self.events.get(event.event_id)
        if old and event.revision <= old.revision: return False
        self.events[event.event_id]=event; return True
    def eligible(self, cutoff): return [e for e in self.events.values() if e.capture_timestamp_ms <= cutoff]
    @staticmethod
    def overlap(a: EventPacket, b: EventPacket):
        intersection=max(0,min(a.end_ms,b.end_ms)-max(a.start_ms,b.start_ms)); union=max(a.end_ms,b.end_ms)-min(a.start_ms,b.start_ms)
        return intersection/union if union else 1.0
    def relation_candidate(self,a,b,relation): return {'status':'candidate','relation':relation,'event_ids':[a.event_id,b.event_id],'overlap':self.overlap(a,b),'uncertainty':'unverified'}
