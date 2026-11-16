import json
import sys
import tempfile
import unittest
from pathlib import Path
from gamstcrew.launcher import launch_profile
from gamstcrew.manager import RuntimeManager

SCRIPT = "import json;print(json.dumps({'type':'ready'}),flush=True)"


class Launcher(unittest.IsolatedAsyncioTestCase):
    async def test_incompatible_profile_rejected_before_start(self):
        profile = {
            "name": "linux",
            "runtime": "linux",
            "python": "3.11",
            "accelerator": "cuda",
            "provider": "x",
            "model_revision": "r",
            "license": "MIT",
            "lock_sha256": "a" * 64,
        }
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profiles.json"
            path.write_text(json.dumps([profile]))
            with self.assertRaises(RuntimeError):
                await launch_profile(
                    RuntimeManager(), path, "linux", [sys.executable, "-c", SCRIPT]
                )


if __name__ == "__main__":
    unittest.main()
