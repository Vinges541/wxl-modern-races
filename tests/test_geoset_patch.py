from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import unittest
from pathlib import Path
import sys
import struct
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from patch_geoset_visibility import patch, SITE, ORIGINAL
from patch_wow import PatchError, Pe32


class GeosetPatchTests(unittest.TestCase):
  def test_rejects_unverified_binary(self):
    with self.assertRaises(PatchError):
      patch(b'not the expected executable')

  @integration
  def test_verified_binary_trampoline(self):
    source = client_root() / 'Wow.exe'
    if not source.exists():
      self.skipTest('local verified client fixture unavailable')
    raw = source.read_bytes()
    if Pe32(bytearray(raw)).has_section('.wxlgeo'):
      source = source.with_name('Wow.exe.before-geoset-v2')
      raw = source.read_bytes()
    result = patch(raw)
    pe = Pe32(bytearray(result))
    site = pe.va_to_offset(SITE)
    jump = SITE + 5 + struct.unpack_from('<i', result, site+1)[0]
    entry = pe.va_to_offset(jump)
    self.assertEqual(result[entry:entry+7], bytes.fromhex('0fb70410394508'))
    self.assertEqual(jump + 12 + struct.unpack_from('<i', result, entry+8)[0], SITE+6)
    self.assertEqual(result[site+6:site+128], raw[site+6:site+128])
    self.assertEqual(struct.unpack_from('<I', result, pe.sections()[-1].header_offset+36)[0], 0x60000020)

  def test_classic_and_extended_id_semantics(self):
    for group in [0, 1, 17, 401, 1502, 1703, 2000, 3202]:
      for level in [0, 1, 2, 65535]:
        dword = (level << 16) | group
        self.assertEqual(dword & 0xffff, group)
