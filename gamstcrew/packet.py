from __future__ import annotations
import hashlib
import hmac
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Mapping

MAX_PACKET_BYTES = 131072
CHECKSUM_ALGORITHM = "sha256"
CHECKSUM_VERSION = 1
INTEGRITY_COUNTER_LIMIT = 2**31 - 1


class PacketIntegrityCounter:
    """Bounded operational count of packets rejected before dispatch."""

    __slots__ = ("limit", "rejected")

    def __init__(self, *, limit: int = INTEGRITY_COUNTER_LIMIT):
        if type(limit) is not int or not 1 <= limit <= INTEGRITY_COUNTER_LIMIT:
            raise ValueError("integrity counter limit must be a positive bounded integer")
        self.limit = limit
        self.rejected = 0

    def record_rejection(self) -> int:
        self.rejected = min(self.limit, self.rejected + 1)
        return self.rejected

    @property
    def integrity_rejected(self) -> int:
        return self.rejected

    def snapshot(self) -> dict[str, int]:
        return {"integrity_rejected": self.rejected}


def _record_rejection(counter):
    if counter is None:
        return
    record = getattr(counter, "record_rejection", None)
    if callable(record):
        record()
        return
    if isinstance(counter, dict):
        value = counter.get("integrity_rejected", 0)
        if type(value) is not int or value < 0:
            raise ValueError("integrity counter must contain a nonnegative integer")
        counter["integrity_rejected"] = min(INTEGRITY_COUNTER_LIMIT, value + 1)
        return
    raise TypeError("counter must be PacketIntegrityCounter or a mutable counter mapping")


def canonical_packet_bytes(packet: Mapping[str, Any]) -> bytes:
    """Encode packet fields with the GAMST temporal canonical JSON rules."""
    if not isinstance(packet, Mapping):
        raise ValueError("packet must be an object")
    body = dict(packet)
    body.pop("checksum", None)
    try:
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("packet is not canonical JSON") from exc
    if len(raw) > MAX_PACKET_BYTES:
        raise ValueError("packet exceeds byte budget")
    return raw


def packet_sha256(packet: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_packet_bytes(packet)).hexdigest()


def packet_checksum(packet: Mapping[str, Any]) -> dict[str, Any]:
    return {"algorithm": CHECKSUM_ALGORITHM, "version": CHECKSUM_VERSION,
            "sha256": packet_sha256(packet)}


def verify_packet_checksum(packet: Mapping[str, Any], *, counter=None,
                           allow_legacy: bool = False) -> bool:
    """Verify a packet before a runtime adapter receives it."""
    try:
        if not isinstance(packet, Mapping):
            raise ValueError("packet must be an object")
        checksum = packet.get("checksum")
        if checksum is None:
            if allow_legacy:
                return False
            raise ValueError("packet checksum is required")
        if (not isinstance(checksum, dict)
                or set(checksum) != {"algorithm", "version", "sha256"}
                or checksum.get("algorithm") != CHECKSUM_ALGORITHM
                or checksum.get("version") != CHECKSUM_VERSION
                or not isinstance(checksum.get("sha256"), str)
                or len(checksum["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in checksum["sha256"])):
            raise ValueError("unsupported packet checksum")
        if not hmac.compare_digest(packet_sha256(packet), checksum["sha256"]):
            raise ValueError("packet checksum mismatch")
        return True
    except (TypeError, ValueError):
        _record_rejection(counter)
        raise


verify_packet_integrity = verify_packet_checksum


def _text(v, name, limit=256):
    if not isinstance(v, str) or not v.strip() or len(v) > limit:
        raise ValueError(f"{name} invalid")
    return v


def _safe(v):
    if isinstance(v, dict):
        return {str(k): _safe(x) for k, x in list(v.items())[:64]}
    if isinstance(v, list):
        return [_safe(x) for x in v[:128]]
    if isinstance(v, (str, bool, int)) or v is None:
        return v
    if isinstance(v, float) and math.isfinite(v):
        return v
    raise ValueError("value must be finite JSON")


@dataclass(frozen=True)
class EventPacket:
    event_id: str
    stream_id: str
    subject_id: str
    modality: str
    event_type: str
    source_clock: str
    capture_timestamp_ms: int
    receive_timestamp_ms: int
    processing_start_ms: int | None
    processing_end_ms: int | None
    start_ms: int
    end_ms: int
    sequence: int
    gap: bool
    revision: int
    provider: str
    model_revision: str
    value: Any
    uncertainty: Any = None
    freshness_ms: int = 5000
    evidence_ids: tuple[str, ...] = ()
    source_spans: tuple[dict[str, Any], ...] = ()
    query_cutoff_ms: int | None = None
    monotonic_capture_ms: int | None = None
    clock_id: str = "legacy"
    clock_epoch: str = "legacy"
    supersedes: str | None = None

    def __post_init__(self):
        for n in (
            "event_id",
            "stream_id",
            "subject_id",
            "modality",
            "event_type",
            "source_clock",
            "clock_id",
            "clock_epoch",
            "provider",
            "model_revision",
        ):
            _text(getattr(self, n), n)
        ints = (
            "capture_timestamp_ms",
            "receive_timestamp_ms",
            "start_ms",
            "end_ms",
            "sequence",
            "revision",
            "freshness_ms",
        )
        if any(type(getattr(self, n)) is not int for n in ints):
            raise ValueError("integer packet fields required")
        if (
            self.start_ms > self.end_ms
            or self.sequence < 0
            or self.revision < 0
            or not 0 <= self.freshness_ms <= 86400000
        ):
            raise ValueError("invalid packet bounds")
        if (
            self.query_cutoff_ms is not None
            and self.capture_timestamp_ms > self.query_cutoff_ms
        ):
            raise ValueError("post-query evidence")
        if len(self.evidence_ids) > 64 or len(self.source_spans) > 64:
            raise ValueError("evidence bound exceeded")
        _safe(self.value)
        _safe(self.uncertainty)
        _safe(list(self.source_spans))

    def to_dict(self, *, include_checksum=True):
        d = asdict(self)
        d["evidence_ids"] = list(self.evidence_ids)
        d["source_spans"] = list(self.source_spans)
        if include_checksum:
            d["checksum"] = packet_checksum(d)
        return d

    def json(self, *, include_checksum=True):
        d = self.to_dict(include_checksum=include_checksum)
        raw = json.dumps(
            d, ensure_ascii=False, sort_keys=True, allow_nan=False,
            separators=(",", ":")
        ).encode("utf-8")
        if len(raw) > MAX_PACKET_BYTES:
            raise ValueError("packet exceeds byte budget")
        return raw

    def to_bytes(self) -> bytes:
        """Serialize a complete packet in canonical UTF-8 JSON form."""
        return self.json()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, counter=None,
                  allow_legacy: bool = False) -> "EventPacket":
        """Verify and parse a packet before it reaches a runtime adapter."""
        verify_packet_checksum(value, counter=counter, allow_legacy=allow_legacy)
        if not isinstance(value, Mapping):
            raise ValueError("packet must be an object")
        fields = {field.name for field in cls.__dataclass_fields__.values()}
        expected = fields | {"checksum"}
        if "checksum" not in value:
            expected.remove("checksum")
        if set(value) != expected:
            raise ValueError("packet has unknown or missing fields")
        kwargs = {name: value[name] for name in fields}
        kwargs["evidence_ids"] = tuple(kwargs["evidence_ids"])
        kwargs["source_spans"] = tuple(kwargs["source_spans"])
        return cls(**kwargs)

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray | memoryview, *, counter=None,
                   allow_legacy: bool = False) -> "EventPacket":
        """Decode canonical packet bytes and verify integrity before parsing."""
        try:
            if isinstance(raw, memoryview):
                raw = raw.tobytes()
            if type(raw) is not bytes or not 1 <= len(raw) <= MAX_PACKET_BYTES:
                raise ValueError("packet bytes exceed bound")

            def reject_duplicates(pairs):
                result = {}
                for key, item in pairs:
                    if key in result:
                        raise ValueError("duplicate packet field")
                    result[key] = item
                return result

            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=reject_duplicates,
                parse_constant=lambda _: (_ for _ in ()).throw(
                    ValueError("nonfinite packet number")
                ),
            )
            packet = cls.from_dict(value, counter=None, allow_legacy=allow_legacy)
            # Current packets bind exact canonical bytes. Legacy packets are
            # accepted under the explicit compatibility switch and upgraded
            # when re-serialized.
            if "checksum" in value:
                canonical = json.dumps(
                    value, ensure_ascii=False, sort_keys=True,
                    allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
                if raw != canonical:
                    raise ValueError("packet bytes are not canonical")
            return packet
        except (UnicodeDecodeError, json.JSONDecodeError):
            _record_rejection(counter)
            raise ValueError("invalid packet bytes")
        except (TypeError, ValueError):
            _record_rejection(counter)
            raise


decode_packet = EventPacket.from_bytes


@dataclass(frozen=True)
class RuntimeDescriptor:
    name: str
    profile: str
    provider: str
    model_revision: str
    license: str
    ready: bool = False

    def __post_init__(self):
        for value, name in (
            (self.name, "runtime name"),
            (self.profile, "runtime profile"),
            (self.provider, "provider"),
            (self.model_revision, "model revision"),
            (self.license, "license"),
        ):
            _text(value, name)
        if type(self.ready) is not bool:
            raise ValueError("ready must be boolean")


@dataclass
class HealthSnapshot:
    runtime: str
    state: str
    queue_depth: int
    capacity: int
    dropped: int
    packet_age_ms: int | None = None
    errors: list[str] = field(default_factory=list)
    descriptor: RuntimeDescriptor | None = None
    integrity_rejected: int = 0
    crash_count: int = 0
    restart_count: int = 0
