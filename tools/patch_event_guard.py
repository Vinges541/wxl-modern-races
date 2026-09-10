"""Guard missing event timestamp arrays in the verified v4 executable.

A null timestamp pointer with nonzero count crashed at 8310AC. Skip only
that event via the engine's normal next-event path. This does not repair
missing data or non-null unrelocated bone animation pointers (828565).
"""
import hashlib
import struct
from pathlib import Path
from patch_wow import Pe32, PatchError, align_up

EXPECTED = '4f1da04ac10aab4afdacaa3fad19223c02ab97ed998cbcfe0a277cb0a49106cb'
SITE = 0x831040
NEXT_EVENT = 0x831270
SIGNATURE = bytes.fromhex('8b0085c08945e4')

def patch(source):
  if hashlib.sha256(source).hexdigest() != EXPECTED:
    raise PatchError('Expected exact v4 executable; unknown or already patched input')
  b = bytearray(source); pe = Pe32(b); last = pe.sections()[-1]
  off = pe.va_to_offset(SITE)
  if b[off:off+7] != SIGNATURE: raise PatchError('Event instruction mismatch')
  rva = align_up(last.virtual_address+max(last.virtual_size,last.raw_size),pe.section_alignment)
  raw = align_up(len(b),pe.file_alignment); va = pe.image_base+rva
  # EAX is the timestamp descriptor. CMP does not alter any live register.
  # Normal path replays TEST, restoring precisely the original branch flags.
  code = bytearray.fromhex('837804000f84')
  code.extend(struct.pack('<i', NEXT_EVENT-(va+10)))
  code.extend(SIGNATURE)
  code.extend(b'\xe9'+struct.pack('<i', SITE+7-(va+len(code)+5)))
  header = pe.section_table+pe.section_count*40
  if header+40 > pe.size_of_headers or any(b[header:header+40]):
    raise PatchError('No empty PE section header')
  size = align_up(len(code),pe.file_alignment)
  b[header:header+40] = struct.pack('<8sIIIIIIHHI',b'.wxlevt',len(code),rva,size,raw,0,0,0,0,0x60000020)
  pe.set_u16(pe.file_header+2,pe.section_count+1)
  pe.set_u32(pe.optional+56,align_up(rva+len(code),pe.section_alignment))
  pe.set_u32(pe.optional+4,pe.u32(pe.optional+4)+size)
  pe.set_u32(pe.optional+64,0)
  b.extend(b'\0'*(raw-len(b))); b.extend(code+b'\0'*(size-len(code)))
  b[off:off+7] = b'\xe9'+struct.pack('<i',va-(SITE+5))+b'\x90\x90'
  return bytes(b)

if __name__ == '__main__':
  import argparse
  p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path)
  a=p.parse_args();result=patch(a.source.read_bytes())
  with a.output.open('xb') as f: f.write(result)
  print(hashlib.sha256(result).hexdigest())
