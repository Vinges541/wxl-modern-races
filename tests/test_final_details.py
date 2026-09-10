from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import struct
import unittest
from pathlib import Path
from wxl_races.final_details import fix_sections
from wxl_races.appearance import array

ROOT = Path(__file__).resolve().parents[1]


class DetailTests(unittest.TestCase):
  @integration
  def test_elf_fix_preserves_all_non_primalist_sections_and_materials(self):
    for race in ('NightElf', 'BloodElf'):
      for sex in ('Male', 'Female'):
        files = list((fixture_root() / 'build/all-appearance-geometry-v2/Character' / race / sex).glob('*.skin'))
        self.assertEqual(len(files), 7)
        for path in files:
          old = path.read_bytes()
          new, stats = fix_sections(old, exclude_primalist=True)
          self.assertEqual(set(stats['removed']), {1702, 1703, 1704, 1705})
          n, offset = array(old, 28, 48)
          old_sections = [old[offset+i*48:offset+(i+1)*48] for i in range(n)]
          keep = [i for i,s in enumerate(old_sections) if struct.unpack_from('<H', s)[0] not in (1702,1703,1704,1705)]
          n, offset = array(new, 28, 48)
          self.assertEqual([new[offset+i*48:offset+(i+1)*48] for i in range(n)], [old_sections[i] for i in keep])
          count, start = array(old, 36, 24)
          expected = []
          for i in range(count):
            batch = bytearray(old[start+i*24:start+(i+1)*24])
            sid = struct.unpack_from('<H', batch, 4)[0]
            if sid in keep:
              struct.pack_into('<H', batch, 4, keep.index(sid))
              expected.append(bytes(batch))
          count, start = array(new, 36, 24)
          self.assertEqual([new[start+i*24:start+(i+1)*24] for i in range(count)], expected)

  @integration
  def test_jaw_keeps_vertex_and_triangle_buffers(self):
    files = list((fixture_root() / 'build/all-appearance-geometry-v2/Character/Scourge/Female').glob('*.skin'))
    self.assertEqual(len(files), 7)
    for path in files:
      old = path.read_bytes()
      new, stats = fix_sections(old, jaw=True)
      self.assertGreater(stats['intactJawSections'], 0)
      for at, stride in ((4, 2), (12, 2), (20, 4)):
        n, offset = array(old, at, stride)
        self.assertEqual(old[offset:offset+n*stride], new[offset:offset+n*stride])
      n, offset = array(new, 28, 48)
      ids = [struct.unpack_from('<H', new, offset+i*48)[0] for i in range(n)]
      self.assertFalse(any(200 <= gid < 300 for gid in ids))
      count, start = array(new, 36, 24)
      for i in range(count):
        self.assertLess(struct.unpack_from('<H', new, start+i*24+4)[0], n)
