from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import io
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
try:
  from PIL import Image
  from build_human_appearance import paletted_blp, direct_hair_blp
except ImportError:
  Image = None


@unittest.skipIf(Image is None, 'Pillow runtime required')
class TextureBudgetTests(unittest.TestCase):
  @integration
  def test_hair_sources_preserve_dxt(self):
    root = fixture_root()
    plan = json.loads((root / 'assets/appearance/human-plan.json').read_text())
    checked = 0
    for row in plan['rows']:
      if row['kind'] != 3:
        continue
      layer, = [x for x in row['layers'] if x['TextureType'] == 6]
      data = direct_hair_blp(layer)
      self.assertEqual(data[8], 2)
      self.assertLess(len(data), 180000)
      self.assertEqual(Image.open(io.BytesIO(data)).size, (512, 256))
      checked += 1
    self.assertGreater(checked, 50)

  @integration
  def test_v5_changes_only_direct_hair_and_eyes(self):
    root = fixture_root()
    candidate = root / 'build/human-appearance-v5'
    if not (candidate / 'appearance-report.json').exists():
      self.skipTest('v5 not generated yet')
    plan = json.loads((root / 'assets/appearance/human-plan.json').read_text())
    hair = {f"Character/Human/Male/Appearance/{row['id']}-0.blp":
            next(x['file'] for x in row['layers'] if x['TextureType'] == 6)
            for row in plan['rows'] if row['kind'] == 3}
    for previous in (root / 'build/human-appearance-v4').rglob('*'):
      if not previous.is_file() or previous.suffix not in ('.blp', '.m2', '.skin', '.dbc'):
        continue
      rel = previous.relative_to(root / 'build/human-appearance-v4')
      actual = (candidate / rel).read_bytes()
      if str(rel) in hair:
        expected = (root / f'assets/appearance/textures/{hair[str(rel)]}.blp').read_bytes()
      elif rel.name == 'HD-Eyes.blp':
        expected = (root / 'assets/appearance/textures/3484643.blp').read_bytes()
      else:
        expected = previous.read_bytes()
      self.assertEqual(actual, expected, str(rel))

  @integration
  def test_generated_v4_face_layers_match_native_region_aspects(self):
    root = fixture_root()
    candidate = root / 'build/human-appearance-v4'
    if not (candidate / 'appearance-report.json').exists():
      self.skipTest('v4 candidate not generated yet')
    plan = json.loads((root / 'assets/appearance/human-plan.json').read_text())
    checked = 0
    for row in plan['rows']:
      if row['kind'] not in (1, 2, 3):
        continue
      first = 1 if row['kind'] == 3 else 0
      for slot, target in ((first, (256, 128)), (first + 1, (256, 64))):
        path = candidate / f"Character/Human/Male/Appearance/{row['id']}-{slot}.blp"
        width, height = struct.unpack_from('<II', path.read_bytes(), 12)
        self.assertEqual(width * target[1], height * target[0], str(path))
        # Native 0x4F08FC only upscales if BOTH dimensions are smaller.
        self.assertTrue((width < target[0] and height < target[1]) or
                        (width >= target[0] and height >= target[1]), str(path))
        checked += 1
    self.assertGreater(checked, 500)

  def test_native_body_size_and_decode(self):
    data = paletted_blp(Image.new('RGBA', (256, 256), (170, 120, 80, 255)))
    self.assertLess(len(data), 180000)
    decoded = Image.open(io.BytesIO(data)).convert('RGBA')
    self.assertEqual(decoded.size, (256, 256))
    self.assertEqual(decoded.getpixel((0, 0)), (170, 120, 80, 255))
    offsets = struct.unpack_from('<16I', data, 20)
    lengths = struct.unpack_from('<16I', data, 84)
    self.assertTrue(offsets[1])
    for offset, length in zip(offsets, lengths):
      self.assertLessEqual(offset + length, len(data))

  def test_alpha_overlay_preserved(self):
    data = paletted_blp(Image.new('RGBA', (128, 32), (120, 70, 30, 0)))
    # Pillow's paletted BLP reader uses palette alpha, ignoring the separate
    # alpha plane. WoW/wow.export use alphaDepth bits after the index plane.
    self.assertEqual(data[9], 8)
    offset = struct.unpack_from('<I', data, 20)[0]
    length = struct.unpack_from('<I', data, 84)[0]
    pixels = 128 * 32
    self.assertEqual(length, pixels * 2)
    self.assertEqual(data[offset+pixels:offset+length], bytes(pixels))
    opaque = paletted_blp(Image.new('RGBA', (128, 32), (120, 70, 30, 255)))
    self.assertEqual(opaque[offset+pixels:offset+length], bytes([255])*pixels)
