from __future__ import annotations
import json, math
from dataclasses import dataclass, field, asdict
from typing import Any

MAX_PACKET_BYTES = 131072

def _text(v, name, limit=256):
    if not isinstance(v, str) or not v.strip() or len(v) > limit: raise ValueError(f"{name} invalid")
    return v

def _safe(v):
    if isinstance(v, dict): return {str(k): _safe(x) for k, x in list(v.items())[:64]}
    if isinstance(v, list): return [_safe(x) for x in v[:128]]
    if isinstance(v, (str, bool, int)) or v is None: return v
    if isinstance(v, float) and math.isfinite(v): return v
    raise ValueError("value must be finite JSON")

@dataclass(frozen=True)
class EventPacket:
    event_id: str; stream_id: str; subject_id: str; modality: str; event_type: str
    source_clock: str; capture_timestamp_ms: int; receive_timestamp_ms: int
    processing_start_ms: int | None; processing_end_ms: int | None
    start_ms: int; end_ms: int; sequence: int; gap: bool; revision: int
    provider: str; model_revision: str; value: Any; uncertainty: Any = None
    freshness_ms: int = 5000; evidence_ids: tuple[str, ...] = ()
    source_spans: tuple[dict[str, Any], ...] = (); query_cutoff_ms: int | None = None
    monotonic_capture_ms: int | None = None; supersedes: str | None = None

    def __post_init__(self):
        for n in ('event_id','stream_id','subject_id','modality','event_type','source_clock','provider','model_revision'): _text(getattr(self,n),n)
        ints = ('capture_timestamp_ms','receive_timestamp_ms','start_ms','end_ms','sequence','revision','freshness_ms')
        if any(type(getattr(self,n)) is not int for n in ints): raise ValueError('integer packet fields required')
        if self.start_ms > self.end_ms or self.sequence < 0 or self.revision < 0 or not 0 <= self.freshness_ms <= 86400000: raise ValueError('invalid packet bounds')
        if self.query_cutoff_ms is not None and self.capture_timestamp_ms > self.query_cutoff_ms: raise ValueError('post-query evidence')
        if len(self.evidence_ids) > 64 or len(self.source_spans) > 64: raise ValueError('evidence bound exceeded')
        _safe(self.value); _safe(self.uncertainty); _safe(list(self.source_spans))

    def json(self):
        d = asdict(self); d['evidence_ids'] = list(self.evidence_ids); d['source_spans'] = list(self.source_spans)
        raw = json.dumps(d, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > MAX_PACKET_BYTES: raise ValueError('packet exceeds byte budget')
        return raw

@dataclass(frozen=True)
class RuntimeDescriptor:
    name: str; profile: str; provider: str; model_revision: str; license: str; ready: bool = False

@dataclass
class HealthSnapshot:
    runtime: str; state: str; queue_depth: int; capacity: int; dropped: int
    packet_age_ms: int | None = None; errors: list[str] = field(default_factory=list)
    descriptor: RuntimeDescriptor | None = None
