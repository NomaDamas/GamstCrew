import json
import tempfile
import unittest
from pathlib import Path
from gamstcrew.registry import read_profiles

class Registry(unittest.TestCase):
    def profile(self):
        return {'name':'asr','runtime':'darwin','python':'3.11','accelerator':'mps','provider':'qwen-asr','model_revision':'r1','license':'Apache-2.0','lock_sha256':'a'*64}
    def test_read_and_validate_profile(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'profiles.json'; p.write_text(json.dumps([self.profile()]))
            profiles=read_profiles(p); self.assertEqual(profiles[0].name,'asr'); self.assertTrue(profiles[0].validate_for({'os':'darwin','accelerator':'mps'}))
    def test_duplicate_or_incomplete_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'profiles.json'; value=self.profile(); value['license']=''; p.write_text(json.dumps([value]))
            with self.assertRaises(ValueError): read_profiles(p)

if __name__=='__main__': unittest.main()
