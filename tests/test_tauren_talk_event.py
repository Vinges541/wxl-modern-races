from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import importlib.util
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('talk_repair', ROOT / 'tools/repair_tauren_talk_event.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TalkEventTests(unittest.TestCase):
  @integration
  def test_preserves_all_existing_animation_bytes(self):
    prefix = Path('Character/Tauren/Male')
    model = (fixture_root() / 'build/all-appearance-geometry-v2' / prefix / 'TaurenMale.m2').read_bytes()
    anim = (fixture_root() / 'build/Patch-ModernRaces-HD.MPQ' / prefix / 'TaurenMale0060-00.anim').read_bytes()
    new_model, new_anim = module.repair(model, anim)
    self.assertEqual(new_anim[8:-4], anim[8:])
    self.assertEqual(struct.unpack_from('<I', new_anim, len(new_anim)-4)[0], 2067)
    self.assertEqual(len(new_model), len(model))
    out = fixture_root() / 'build/tauren-talk-event-v1/Data/Patch-ModernRaces-HD.MPQ' / prefix
    self.assertEqual(new_model, (out/'TaurenMale.m2').read_bytes())
    self.assertEqual(new_anim, (out/'TaurenMale0060-00.anim').read_bytes())

  @integration
  def test_refuses_already_fixed_model(self):
    prefix = fixture_root() / 'build/tauren-talk-event-v1/Data/Patch-ModernRaces-HD.MPQ/Character/Tauren/Male'
    with self.assertRaises(AssertionError):
      module.repair((prefix/'TaurenMale.m2').read_bytes(), (prefix/'TaurenMale0060-00.anim').read_bytes())
