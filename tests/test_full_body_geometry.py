from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]


def sections(data):
  count, offset = struct.unpack_from('<II',data,28)
  return [data[offset+i*48:offset+(i+1)*48] for i in range(count)]


class FullBodyGeometryTests(unittest.TestCase):
  @integration
  def test_full_faces_and_hands_are_present_and_renderable(self):
    candidate = fixture_root() / 'build/all-appearance-geometry-v2'
    if not (candidate / 'report.json').exists():
      self.skipTest('Geometry candidate not built')
    reports = json.loads((candidate / 'report.json').read_text())
    self.assertEqual(len(reports),19)
    checked = 0
    for row in reports:
      prefix = Path(f"Character/{row['race']}/{row['sex']}")
      for original in (fixture_root() / 'build/Patch-ModernRaces-HD.MPQ' / prefix).glob('*.skin'):
        source = sections(original.read_bytes())
        repaired = (candidate / prefix / original.name).read_bytes()
        output = sections(repaired)
        count, offset = struct.unpack_from('<II',repaired,36)
        rendered = {struct.unpack_from('<H',repaired,offset+i*24+4)[0] for i in range(count)}
        for section in source:
          gid = struct.unpack_from('<H',section)[0]
          if gid not in (3202,2301):
            continue
          expected = b'\0\0'+section[2:]
          self.assertIn(expected,output,f'{prefix}/{original.name}: missing {gid}')
          self.assertIn(output.index(expected),rendered,f'{prefix}: no render batch for {gid}')
          checked += 1
    self.assertGreaterEqual(checked,19*7)

  @integration
  def test_blood_elf_face_is_not_only_mouth_interior(self):
    base = fixture_root() / 'build/Patch-ModernRaces-HD.MPQ/Character/BloodElf/Male'
    data = next(base.glob('*00.skin')).read_bytes()
    counts = {struct.unpack_from('<H',s)[0]:struct.unpack_from('<H',s,10)[0] for s in sections(data)}
    self.assertGreater(counts[3202],counts[3201]*10)
