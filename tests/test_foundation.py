import unittest
import asyncio
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


class FlakyAdapter(Adapter):
    def __init__(self):
        super().__init__()
        self.starts = 0

    async def start(self):
        self.starts += 1

    async def submit(self, p):
        if not self.items:
            raise RuntimeError("transient provider failure")
        self.items.append(p)


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
    async def test_concurrent_registration_is_serialized(self):
        manager = RuntimeManager()
        adapters = [Adapter(), Adapter()]
        descriptors = [RuntimeDescriptor("same", "mac", "fixture", "1", "MIT", True)] * 2
        results = await asyncio.gather(
            manager.register("same", adapters[0], descriptors[0]),
            manager.register("same", adapters[1], descriptors[1]),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        await manager.close("same")

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

    async def test_failed_start_is_stopped(self):
        adapter = Adapter()
        async def fail():
            raise RuntimeError('readiness failed')
        adapter.start = fail
        manager = RuntimeManager()
        with self.assertRaises(RuntimeError):
            await manager.register('x', adapter, RuntimeDescriptor('x', 'mac', 'fixture', '1', 'MIT', True))
        self.assertTrue(adapter.stopped)
        self.assertNotIn('x', manager.runtimes)

    async def test_close_all_stops_every_runtime_and_releases_registry(self):
        manager = RuntimeManager()
        adapters = [Adapter(), Adapter()]
        descriptor = RuntimeDescriptor("runtime", "mac", "fixture", "1", "MIT", True)
        await manager.register("one", adapters[0], descriptor)
        await manager.register("two", adapters[1], descriptor)
        await manager.close_all()
        self.assertEqual(manager.runtimes, {})
        self.assertTrue(adapters[0].stopped)
        self.assertTrue(adapters[1].stopped)

    async def test_manager_async_context_closes_registered_runtimes(self):
        adapter = Adapter()
        async with RuntimeManager() as manager:
            await manager.register(
                "ctx", adapter,
                RuntimeDescriptor("ctx", "mac", "fixture", "1", "MIT", True),
            )
            self.assertIn("ctx", manager.runtimes)
        self.assertTrue(adapter.stopped)

    async def test_runtime_error_is_visible_and_restart_is_bounded(self):
        manager = RuntimeManager(restart_limit=1)
        adapter = FlakyAdapter()
        await manager.register('x', adapter, RuntimeDescriptor('x', 'mac', 'fixture', '1', 'MIT', True))
        try:
            await manager.submit('x', packet(1))
            await asyncio.sleep(0.03)
            health = manager.health('x')
            self.assertEqual(health.crash_count, 1)
            self.assertEqual(health.restart_count, 1)
            self.assertEqual(adapter.starts, 2)
        finally:
            await manager.close('x')

    async def test_temporal_clock_cutoff_revision(self):
        t = TemporalAligner(min_samples=3)
        for i in range(3):
            t.add_clock_sample("mono", i * 100, i * 100 + 5)
        self.assertTrue(t.status("mono").calibrated)
        self.assertTrue(t.accept(packet(1)))
        self.assertFalse(t.accept(packet(1)))
        self.assertEqual(len(t.eligible(1)), 1)
        self.assertEqual(len(t.eligible(0)), 0)

    async def test_revision_lineage_and_clock_epoch(self):
        from dataclasses import replace
        aligner = TemporalAligner()
        self.assertTrue(aligner.accept(packet(1)))
        with self.assertRaises(ValueError):
            aligner.accept(replace(packet(1), revision=1))
        self.assertTrue(aligner.accept(replace(packet(1), revision=1, supersedes='1')))
        with self.assertRaises(ValueError):
            aligner.accept(replace(packet(1), revision=2, supersedes='1', clock_epoch='restarted'))

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
