from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import io
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from PIL import Image
from build_npc_appearance import dxt1_blp, repack_atlas
from wxl_races.helm import adapt_helmet_anchor, helmet_anchor, head_parent_pivot


class NpcAppearanceTests(unittest.TestCase):
  def test_head_moves_without_changing_armor_regions(self):
    source = Image.new('RGB', (512, 256), (20, 70, 130))
    source.paste((160, 90, 40), (256, 0, 512, 256))
    target = repack_atlas(source)
    self.assertEqual(target.size, (256, 256))
    self.assertEqual(target.getpixel((64, 200)), (160, 90, 40))
    self.assertEqual(target.getpixel((64, 80)), (20, 70, 130))
    self.assertEqual(target.getpixel((200, 200)), (20, 70, 130))

  def test_dxt_mips_are_bounded_and_decodable(self):
    data = dxt1_blp(Image.new('RGB', (256, 256), (150, 90, 40)))
    self.assertLess(len(data), 45000)
    self.assertEqual(data[8], 2)
    offsets = struct.unpack_from('<16I', data, 20)
    lengths = struct.unpack_from('<16I', data, 84)
    for i in range(9):
      self.assertEqual(lengths[i], max(1, ((256 >> i)+3)//4)**2*8)
      self.assertLessEqual(offsets[i]+lengths[i], len(data))
    decoded = Image.open(io.BytesIO(data)).convert('RGB')
    self.assertTrue(all(abs(a-b)<9 for a,b in zip(decoded.getpixel((40,40)), (150,90,40))))

  def test_rejects_original_square_atlas(self):
    with self.assertRaises(ValueError):
      repack_atlas(Image.new('RGB', (256, 256)))

  @integration
  def test_helmet_changes_only_attachment_position(self):
    source = (fixture_root() / 'build/human-appearance-v5/Character/Human/Male/HumanMale.m2').read_bytes()
    legacy = fixture_root() / 'assets/legacy/HumanMale.m2'
    if not legacy.exists():
      self.skipTest('Legacy fixture not extracted')
    target, report = adapt_helmet_anchor(source, legacy.read_bytes())
    at, _ = helmet_anchor(source)
    self.assertEqual(target[:at+8], source[:at+8])
    self.assertEqual(target[at+20:], source[at+20:])
    self.assertEqual(helmet_anchor(target)[1], helmet_anchor(legacy.read_bytes())[1])
    self.assertGreater(report['after'][2], report['before'][2])

  @integration
  def test_helmet_can_preserve_parent_relative_offset(self):
    source = (fixture_root() / 'build/human-appearance-v5/Character/Human/Male/HumanMale.m2').read_bytes()
    legacy_path = fixture_root() / 'assets/legacy/HumanMale.m2'
    if not legacy_path.exists():
      self.skipTest('Legacy fixture not extracted')
    legacy = legacy_path.read_bytes()
    target, _ = adapt_helmet_anchor(source, legacy, preserve_parent_offset=True)
    old_offset = tuple(a-b for a,b in zip(helmet_anchor(legacy)[1],head_parent_pivot(legacy)))
    new_offset = tuple(a-b for a,b in zip(helmet_anchor(target)[1],head_parent_pivot(target)))
    for old, new in zip(old_offset, new_offset):
      self.assertAlmostEqual(old, new, places=6)
