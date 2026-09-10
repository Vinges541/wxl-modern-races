from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import hashlib,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from patch_anim_loader import patch,EXPECTED,SITE,SIGNATURE
from patch_wow import Pe32,PatchError
class AnimLoaderTests(unittest.TestCase):
  def test_rejects_unknown(self):
    for b in (b'',b'MZ',bytes(1024)):
      with self.assertRaises(PatchError):patch(b)
  @integration
  def test_exact_delta_and_destinations(self):
    p=client_root() / 'DisabledPatches/Before-anim-loader-v8/Wow.exe'
    if not p.exists():self.skipTest('Local v7 fixture unavailable')
    b=p.read_bytes();self.assertEqual(hashlib.sha256(b).hexdigest(),EXPECTED)
    result=patch(b);old=Pe32(bytearray(b));new=Pe32(bytearray(result))
    s=new.sections()[-1];va=new.image_base+s.virtual_address
    code=result[s.raw_offset:s.raw_offset+s.virtual_size]
    self.assertEqual(code[:10],bytes.fromhex('8b46043d120100000f84'))
    self.assertEqual(va+14+struct.unpack_from('<i',code,10)[0],0x83c74e)
    self.assertEqual(code[14:20],bytes.fromhex('3d08010000e9'))
    self.assertEqual(va+24+struct.unpack_from('<i',code,20)[0],SITE+8)
    off=old.va_to_offset(SITE)
    self.assertEqual(b[off:off+8],SIGNATURE)
    self.assertEqual(SITE+5+struct.unpack_from('<i',result,off+1)[0],va)
    for s in old.sections():
      before=bytearray(b[s.raw_offset:s.raw_offset+s.raw_size]);after=result[s.raw_offset:s.raw_offset+s.raw_size]
      if s.raw_offset<=off<s.raw_offset+s.raw_size:before[off-s.raw_offset:off-s.raw_offset+8]=result[off:off+8]
      self.assertEqual(bytes(before),after,s.name)
    with self.assertRaises(PatchError):patch(result)
