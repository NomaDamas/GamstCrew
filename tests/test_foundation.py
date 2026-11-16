import unittest
from gamstcrew import EventPacket, RuntimeDescriptor, RuntimeManager, TemporalAligner


class Adapter:
    def __init__(self):
        self.items = []
        self.stopped = False

    async def start(self):
        pass

    async def stop(self):
        self.stopped = True

    async def submit(self, p):
        self.items.append(p)

    def health(self):
        return {}


def packet(i, cut=None):
    return EventPacket(
        str(i),
        "s",
        "u",
        "audio",
        "event",
        "mono",
        i,
        i,
        None,
        None,
        i,
        i,
        i,
        False,
        0,
        "fixture",
        "1",
        {"i": i},
        query_cutoff_ms=cut,
    )


class Foundation(unittest.IsolatedAsyncioTestCase):
    async def test_manager_bounded_health(self):
        m = RuntimeManager(capacity=2)
        a = Adapter()
        await m.register(
            "x", a, RuntimeDescriptor("x", "mac", "fixture", "1", "MIT", True)
        )
        for i in range(5):
            await m.submit("x", packet(i))
        self.assertEqual(m.health("x").dropped, 3)
        await m.close("x")
        self.assertTrue(a.stopped)

    async def test_temporal_clock_cutoff_revision(self):
        t = TemporalAligner(min_samples=3)
        for i in range(3):
            t.add_clock_sample("mono", i * 100, i * 100 + 5)
        self.assertTrue(t.status("mono").calibrated)
        self.assertTrue(t.accept(packet(1)))
        self.assertFalse(t.accept(packet(1)))
        self.assertEqual(len(t.eligible(1)), 1)
        self.assertEqual(len(t.eligible(0)), 0)

    def test_clock_identity_survives_packet_serialization(self):
        from dataclasses import replace
        import json
        value = replace(packet(1), clock_id='camera-clock', clock_epoch='boot-7')
        decoded = json.loads(value.json())
        self.assertEqual(decoded['clock_id'], 'camera-clock')
        self.assertEqual(decoded['clock_epoch'], 'boot-7')
        with self.assertRaises(ValueError):
            replace(value, clock_epoch='')

    def test_descriptor_requires_revision_and_license(self):
        with self.assertRaises(ValueError):
            RuntimeDescriptor("x", "mac", "fixture", "", "MIT", True)


if __name__ == "__main__":
    unittest.main()
