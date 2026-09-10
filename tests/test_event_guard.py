from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import hashlib
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from patch_event_guard import patch, EXPECTED, SITE, NEXT_EVENT, SIGNATURE
from patch_wow import Pe32, PatchError

class EventGuardTests(unittest.TestCase):
  def test_unknown_input(self):
    for value in (b'',b'MZ',bytes(1024)):
      with self.assertRaises(PatchError): patch(value)

  @integration
  def test_exact_patch_and_control_flow(self):
    root=client_root()
    paths=[root/'DisabledPatches/Before-event-guard-v7/Wow.exe',root/'Wow.exe']
    source=next((p.read_bytes() for p in paths if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==EXPECTED),None)
    if source is None: self.skipTest('Local v4 fixture unavailable')
    result=patch(source); old=Pe32(bytearray(source));new=Pe32(bytearray(result))
    sec=new.sections()[-1]; va=new.image_base+sec.virtual_address
    code=result[sec.raw_offset:sec.raw_offset+sec.virtual_size]
    self.assertEqual(code[:6],bytes.fromhex('837804000f84'))
    self.assertEqual(va+10+struct.unpack_from('<i',code,6)[0],NEXT_EVENT)
    self.assertEqual(code[10:17],SIGNATURE)
    self.assertEqual(code[17],0xe9)
    self.assertEqual(va+22+struct.unpack_from('<i',code,18)[0],SITE+7)
    off=old.va_to_offset(SITE)
    self.assertEqual(SITE+5+struct.unpack_from('<i',result,off+1)[0],va)
    for s in old.sections():
      before=bytearray(source[s.raw_offset:s.raw_offset+s.raw_size])
      after=result[s.raw_offset:s.raw_offset+s.raw_size]
      if s.raw_offset<=off<s.raw_offset+s.raw_size:
        before[off-s.raw_offset:off-s.raw_offset+7]=result[off:off+7]
      self.assertEqual(bytes(before),after,s.name)
    with self.assertRaises(PatchError): patch(result)
