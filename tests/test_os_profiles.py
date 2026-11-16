import unittest
from gamstcrew.os_profiles import profile, require_profile


class Profiles(unittest.TestCase):
    def test_profile_has_explicit_runtime_fields(self):
        value = profile().descriptor()
        for key in (
            "name",
            "os",
            "arch",
            "accelerator",
            "python",
            "supports_cuda",
            "supports_mps",
        ):
            self.assertIn(key, value)

    def test_requirement_rejects_wrong_environment(self):
        with self.assertRaises(RuntimeError):
            require_profile({"os": "darwin", "accelerator": "mps"}, required_os="linux")


if __name__ == "__main__":
    unittest.main()
