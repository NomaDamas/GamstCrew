import sys
import unittest
from gamstcrew.packet import EventPacket, RuntimeDescriptor
from gamstcrew.process_runtime import ProcessRuntime

SCRIPT = "import sys,json; print(json.dumps({'type':'ready'}),flush=True); [print(json.dumps({'accepted':True}),flush=True) for line in sys.stdin]"


def packet():
    return EventPacket(
        "e",
        "s",
        "u",
        "vision",
        "event",
        "mono",
        1,
        1,
        None,
        None,
        1,
        1,
        1,
        False,
        0,
        "fixture",
        "1",
        {"x": 1},
    )


class ProcessRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_submit_stop(self):
        runtime = ProcessRuntime(
            (sys.executable, "-u", "-c", SCRIPT),
            RuntimeDescriptor("x", "mac", "fixture", "1", "MIT", True),
        )
        await runtime.start()
        try:
            self.assertEqual(await runtime.submit(packet()), {"accepted": True})
            self.assertTrue(runtime.health()["running"])
        finally:
            await runtime.stop()
        self.assertIsNone(runtime.process)

    async def test_bad_readiness_fails(self):
        runtime = ProcessRuntime(
            (sys.executable, "-u", "-c", "print('bad',flush=True)"),
            RuntimeDescriptor("x", "mac", "fixture", "1", "MIT", True),
        )
        with self.assertRaises(RuntimeError):
            await runtime.start()
        await runtime.stop()


if __name__ == "__main__":
    unittest.main()
