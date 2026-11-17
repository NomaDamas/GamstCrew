from __future__ import annotations
import statistics
from dataclasses import dataclass
from .packet import EventPacket


@dataclass(frozen=True)
class ClockStatus:
    source_clock: str
    calibrated: bool
    samples: int
    offset_ms: float | None
    drift: float | None
    residual_ms: float | None


class TemporalAligner:
    def __init__(self, min_samples=8, max_samples=128):
        if (
            type(min_samples) is not int
            or min_samples < 2
            or type(max_samples) is not int
            or max_samples < min_samples
        ):
            raise ValueError("invalid sample bounds")
        self.min_samples, self.max_samples = min_samples, max_samples
        self.samples = {}
        self.events = {}
        self._last_sequences = {}
        self._sequence_results = {}

    def add_clock_sample(self, clock, source_ms, monotonic_ms):
        if type(source_ms) is not int or type(monotonic_ms) is not int:
            raise ValueError("clock values must be integers")
        values = self.samples.setdefault(clock, [])
        values.append((source_ms, monotonic_ms))
        del values[: -self.max_samples]

    def status(self, clock):
        values = self.samples.get(clock, [])
        if len(values) < self.min_samples:
            return ClockStatus(clock, False, len(values), None, None, None)
        x0, y0 = values[0]
        dx = [x - x0 for x, _ in values]
        dy = [y - y0 for _, y in values]
        den = sum(x * x for x in dx)
        slope = sum(x * y for x, y in zip(dx, dy)) / den if den else 1
        offset = statistics.mean(y - slope * x for x, y in values)
        residual = statistics.mean(abs(y - (offset + slope * x)) for x, y in values)
        return ClockStatus(clock, True, len(values), offset, slope - 1, residual)

    @staticmethod
    def _status_dict(status):
        return {
            "source_clock": status.source_clock,
            "calibrated": status.calibrated,
            "samples": status.samples,
            "offset_ms": status.offset_ms,
            "drift": status.drift,
            "residual_ms": status.residual_ms,
        }

    def normalize_timestamp(self, clock, source_ms):
        """Map a source timestamp onto the monotonic timeline when calibrated.

        The uncalibrated result is explicit and carries no guessed timestamp.
        This keeps runtime boundaries from silently treating independent source
        clocks as comparable evidence.
        """
        if not isinstance(clock, str) or not clock.strip():
            raise ValueError("clock must be a non-empty string")
        if type(source_ms) is not int:
            raise ValueError("source timestamp must be an integer")
        status = self.status(clock)
        normalized = None
        if status.calibrated:
            normalized = round(status.offset_ms + (1.0 + status.drift) * source_ms)
        return {
            "source_clock": clock,
            "source_timestamp_ms": source_ms,
            "normalized_timestamp_ms": normalized,
            "calibrated": status.calibrated,
            "clock": self._status_dict(status),
        }

    def sequence_gap(self, event):
        """Return bounded sequence continuity state without fabricating events."""
        if not isinstance(event, EventPacket):
            raise TypeError("sequence gap requires an EventPacket")
        cached = self._sequence_results.get(event.event_id)
        if cached is not None:
            return dict(cached)
        stream_key = (event.stream_id, event.clock_id, event.clock_epoch)
        previous = self._last_sequences.get(stream_key)
        expected = None if previous is None else previous + 1
        detected = previous is not None and event.sequence != expected
        if previous is None:
            state = "initial"
        elif event.sequence <= previous:
            state = "reordered"
        elif detected:
            state = "gap"
        else:
            state = "contiguous"
        return {
            "stream_id": event.stream_id,
            "previous_sequence": previous,
            "expected_sequence": expected,
            "observed_sequence": event.sequence,
            "declared_gap": bool(event.gap),
            "detected_gap": bool(detected),
            "state": state,
        }

    def accept(self, event):
        old = self.events.get(event.event_id)
        if old and (old.clock_id, old.clock_epoch) != (event.clock_id, event.clock_epoch):
            raise ValueError("event identity cannot cross clock epochs")
        if old and event.revision <= old.revision:
            return False
        if event.revision > 0 and (not old or event.supersedes != old.event_id):
            raise ValueError("newer revision must supersede the previous event")
        gap = self.sequence_gap(event)
        self.events[event.event_id] = event
        self._sequence_results[event.event_id] = gap
        stream_key = (event.stream_id, event.clock_id, event.clock_epoch)
        previous = self._last_sequences.get(stream_key)
        if previous is None or event.sequence > previous:
            self._last_sequences[stream_key] = event.sequence
        return True

    def eligible(self, cutoff):
        return [e for e in self.events.values() if e.capture_timestamp_ms <= cutoff]

    @staticmethod
    def overlap(a: EventPacket, b: EventPacket):
        intersection = max(0, min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms))
        union = max(a.end_ms, b.end_ms) - min(a.start_ms, b.start_ms)
        return intersection / union if union else 1.0

    def relation_candidate(self, a, b, relation):
        left_clock = self.status(a.source_clock)
        right_clock = self.status(b.source_clock)
        return {
            "status": "candidate",
            "relation": relation,
            "event_ids": [a.event_id, b.event_id],
            "overlap": self.overlap(a, b),
            "uncertainty": "unverified",
            "evidence_ids": list(dict.fromkeys(
                list(a.evidence_ids) + list(b.evidence_ids)
            ))[:128],
            "source_clocks": [a.source_clock, b.source_clock],
            "clock_calibration": [
                self._status_dict(left_clock), self._status_dict(right_clock)
            ],
            "sequence_gaps": [self.sequence_gap(a), self.sequence_gap(b)],
        }

    def contradiction_candidate(self, a, b, reason="value_conflict"):
        """Create an abstaining contradiction candidate with both values."""
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 128:
            raise ValueError("reason must be a bounded non-empty string")
        result = self.relation_candidate(a, b, "contradiction")
        result.update({
            "contradiction_status": "candidate",
            "reason": reason,
            "values": {"left": a.value, "right": b.value},
        })
        return result
