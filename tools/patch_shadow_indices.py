"""Restore the high index word in the native shadow draw path, verified build only."""
import hashlib
import struct
from pathlib import Path
from patch_wow import Pe32, PatchError, align_up
EXPECTED='935ac70c502675f8c37baea08159bd1263c65908914338bf37928d320b3f47a8'
SITE=0x829C5A
ORIGINAL=bytes.fromhex('0fb746088945e0')

def patch(source):
  if hashlib.sha256(source).hexdigest()!=EXPECTED:raise PatchError('unexpected executable')
  data=bytearray(source);pe=Pe32(data);at=pe.va_to_offset(SITE)
  if data[at:at+7]!=ORIGINAL:raise PatchError('shadow signature mismatch')
  last=pe.sections()[-1]
  rva=align_up(last.virtual_address+max(last.virtual_size,last.raw_size),pe.section_alignment)
  raw=align_up(len(data),pe.file_alignment);va=pe.image_base+rva
  # Preserve EFLAGS/EDX. EAX receives (level<<16)|indexStart, then original store.
  code=bytes.fromhex('9c520fb74602c1e0100fb7560809d05a9d8945e0')
  code+=b'\xe9'+struct.pack('<i',SITE+7-(va+len(code)+5))
  header=pe.section_table+pe.section_count*40
  if header+40>pe.size_of_headers or any(data[header:header+40]):raise PatchError('no PE header slot')
  size=align_up(len(code),pe.file_alignment)
  data[header:header+40]=struct.pack('<8sIIIIIIHHI',b'.wxlshad',len(code),rva,size,raw,0,0,0,0,0x60000020)
  pe.set_u16(pe.file_header+2,pe.section_count+1)
  pe.set_u32(pe.optional+56,align_up(rva+len(code),pe.section_alignment))
  pe.set_u32(pe.optional+4,pe.u32(pe.optional+4)+size);pe.set_u32(pe.optional+64,0)
  data.extend(b'\0'*(raw-len(data)));data.extend(code+b'\0'*(size-len(code)))
  data[at:at+7]=b'\xe9'+struct.pack('<i',va-(SITE+5))+b'\x90\x90'
  return bytes(data)

if __name__=='__main__':
  raise SystemExit('Use build_runtime.py for the complete verified patch chain')
