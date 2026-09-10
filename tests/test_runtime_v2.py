from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import importlib.util
import struct
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_v2',ROOT/'tools/repair_runtime_v2.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RuntimeTests(unittest.TestCase):
  @integration
  def test_all_shadow_references_follow_retained_geometry(self):
    files=list((fixture_root() / 'build/runtime-v2/Data/Patch-ModernRaces-HD.MPQ/Character').glob('*/*/*.skin'))
    self.assertEqual(len(files),140)
    for f in files:
      b=f.read_bytes();n,o=m.array(b,28,48);c,p=m.array(b,48,12)
      for i in range(c):self.assertLess(struct.unpack_from('<H',b,p+i*12+4)[0],n)
      rel=f.relative_to(fixture_root() / 'build/runtime-v2/Data/Patch-ModernRaces-HD.MPQ')
      original=(fixture_root() / 'build/Patch-ModernRaces-HD.MPQ'/rel).read_bytes()
      repaired,_=m.shadows(original,b)
      cc,pp=m.array(repaired,48,12)
      self.assertEqual(b[p:p+c*12],repaired[pp:pp+cc*12])

  @integration
  def test_talk_tracks_are_inline_and_persistent(self):
    for sex in ('Male','Female'):
      f=fixture_root() / 'build/runtime-v2/Data/Patch-ModernRaces-HD.MPQ/Character/Tauren'/sex/('Tauren'+sex+'.m2')
      b=m.read_chunks(f.read_bytes())[0].payload
      n,o=m.array(b,0x1c,64)
      slots=[i for i in range(n) if struct.unpack_from('<HH',b,o+i*64) in ((60,0),(208,0))]
      self.assertEqual(len(slots),2)
      for slot in slots:self.assertTrue(struct.unpack_from('<I',b,o+slot*64+12)[0]&0x20)
      count,bones=m.array(b,0x2c,88)
      for i in range(count):
        for delta,size in ((16,12),(36,8),(56,12)):
          at=bones+i*88+delta
          if struct.unpack_from('<h',b,at+2)[0]>=0:continue
          for half,width in ((4,4),(12,size)):
            cnt,off=m.array(b,at+half,8)
            for slot in slots:
              if slot>=cnt:continue
              keys,ptr=struct.unpack_from('<II',b,off+slot*8)
              if keys:
                self.assertGreater(ptr,9000000)
                self.assertLessEqual(ptr+keys*width,len(b))
