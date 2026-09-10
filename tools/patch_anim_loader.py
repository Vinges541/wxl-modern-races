"""Accept normalized v274 headers in the external-sequence rebase only.

Not a new model-format parser: initial loading remains WarcraftXL's MD21
normalization. The stock v264 initial-load validation is unchanged.
"""
import hashlib
import struct
from pathlib import Path
import sys
from patch_wow import Pe32, PatchError, align_up
EXPECTED='2c297ffa97ae5d00923b1f62a434d573ee4b98c67ad16a16bf6dc453786e340f'
SITE=0x83c734
SIGNATURE=bytes.fromhex('8b46043d08010000')

def patch(source):
  if hashlib.sha256(source).hexdigest()!=EXPECTED: raise PatchError('Expected exact v7 EXE')
  b=bytearray(source);pe=Pe32(b);last=pe.sections()[-1]
  rva=align_up(last.virtual_address+max(last.virtual_size,last.raw_size),pe.section_alignment)
  raw=align_up(len(b),pe.file_alignment);va=pe.image_base+rva
  # ESI is the normalized, resident MD20 body. Only the external-load check
  # changes; v264 and rejected versions replay their original CMP/flags.
  code=bytearray.fromhex('8b46043d120100000f84')
  code.extend(struct.pack('<i',0x83c74e-(va+14)))
  code.extend(bytes.fromhex('3d08010000'))
  code.extend(b'\xe9'+struct.pack('<i',SITE+8-(va+len(code)+5)))
  off=pe.va_to_offset(SITE)
  if b[off:off+8]!=SIGNATURE:raise PatchError('Signature mismatch')
  header=pe.section_table+pe.section_count*40
  if header+40>pe.size_of_headers or any(b[header:header+40]):raise PatchError('No PE header slot')
  size=align_up(len(code),pe.file_alignment)
  b[header:header+40]=struct.pack('<8sIIIIIIHHI',b'.wxlanim',len(code),rva,size,raw,0,0,0,0,0x60000020)
  pe.set_u16(pe.file_header+2,pe.section_count+1)
  pe.set_u32(pe.optional+56,align_up(rva+len(code),pe.section_alignment))
  pe.set_u32(pe.optional+4,pe.u32(pe.optional+4)+size);pe.set_u32(pe.optional+64,0)
  b.extend(b'\0'*(raw-len(b)));b.extend(code+b'\0'*(size-len(code)))
  b[off:off+8]=b'\xe9'+struct.pack('<i',va-(SITE+5))+b'\x90'*3
  return bytes(b)

if __name__=='__main__':
  result=patch(Path(sys.argv[1]).read_bytes())
  with Path(sys.argv[2]).open('xb') as f:f.write(result)
  print(hashlib.sha256(result).hexdigest())
