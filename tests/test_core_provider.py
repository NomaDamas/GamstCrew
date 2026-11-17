import sys
import unittest
from gamst import Gamst, SensorMetadata, SensorStreams
from gamst.plugins import InputFrame
from gamst.schema import timestamp
from gamstcrew import CoreProviderRuntime

CONFIG = {
    "id": "court-cal",
    "reference_id": "view-1",
    "source_id": "cam",
    "sensor_id": "points",
    "input_frame": "camera.image",
    "output_frame": "court.xy",
    "image_size": [640, 480],
    "valid_roi": [0.1, 0.1, 0.9, 0.9],
    "image_to_plane": [[10, 0, 0], [0, 20, 0], [0.5, 0, 1]],
}


def frame():
    return InputFrame(
        {
            "reference_id": "view-1",
            "image_size": [640, 480],
            "points": [{"id": "contact", "xy": [0.5, 0.5], "on_plane": True}],
        },
        "video",
        timestamp(),
        sensor=SensorMetadata(
            "cam", "points", 1, "camera.image", calibration_id="court-cal"
        ),
    )


class CoreProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_crew_owned_worker_reaches_temporal_context(self):
        runtime = CoreProviderRuntime(sys.executable, "geometry.ground_plane", CONFIG)
        await runtime.start()
        try:
            async with Gamst(consent=True) as human:
                streams = SensorStreams(human)
                streams.register(runtime.spec, lambda: runtime)
                await streams.open("cam", "points", [runtime.spec.id])
                await streams.submit(frame())
                await streams.drain()
                packet = await human.build_temporal_context()
                event = next(
                    item
                    for item in packet["events"]
                    if item["event_type"] == "geometry.plane_points"
                )
                health = runtime.health()
                self.assertEqual(event["clock_id"], health["clock_id"])
                self.assertEqual(event["clock_epoch"], health["clock_epoch"])
                self.assertEqual(event["evidence_state"], "current")
        finally:
            await runtime.stop()
        self.assertFalse(runtime.health()["running"])


if __name__ == "__main__":
    unittest.main()
