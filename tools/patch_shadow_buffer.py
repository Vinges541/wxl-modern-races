"""Complete the shared shadow-index path: widen source and preserve relocated high word."""
import hashlib, struct
from pathlib import Path
from patch_wow import Pe32, PatchError, align_up
EXPECTED='cd04926f330b012172fe0bc6e094dbd4266388979bbdedf21daf82278411215e'

def patch(source):
  if hashlib.sha256(source).hexdigest()!=EXPECTED:raise PatchError('unexpected input executable')
  b=bytearray(source);pe=Pe32(b);last=pe.sections()[-1]
  rva=align_up(last.virtual_address+max(last.virtual_size,last.raw_size),pe.section_alignment)
  raw=align_up(len(b),pe.file_alignment);va=pe.image_base+rva
  # Save flags/EAX/EDX; expanded start is accepted only inside the source index
  # array. Otherwise retain the original low word (legacy LOD-marker semantics).
  read=bytes.fromhex('9c50528d040b0fb750080fb75802c1e31009d38b86700100003b580c720289d35a589d')
  # Store both halves of the new packed-buffer start, preserving live registers
  # and flags, then replay the displaced next instruction.
  write=bytes.fromhex('66895a089c508bc3c1e81066894202589d0fb7520a')
  code=bytearray();sites=[]
  for site,signature,body in ((0x83619f,bytes.fromhex('0fb75c0b08'),read),(0x836240,bytes.fromhex('66895a080fb7520a'),write)):
    off=pe.va_to_offset(site)
    if b[off:off+len(signature)]!=signature:raise PatchError('instruction signature mismatch')
    target=va+len(code);code.extend(body)
    code.extend(b'\xe9'+struct.pack('<i',site+len(signature)-(va+len(code)+5)))
    sites.append((off,site,len(signature),target))
  header=pe.section_table+pe.section_count*40
  if header+40>pe.size_of_headers or any(b[header:header+40]):raise PatchError('no PE header slot')
  size=align_up(len(code),pe.file_alignment)
  b[header:header+40]=struct.pack('<8sIIIIIIHHI',b'.wxlshb',len(code),rva,size,raw,0,0,0,0,0x60000020)
  pe.set_u16(pe.file_header+2,pe.section_count+1);pe.set_u32(pe.optional+56,align_up(rva+len(code),pe.section_alignment))
  pe.set_u32(pe.optional+4,pe.u32(pe.optional+4)+size);pe.set_u32(pe.optional+64,0)
  b.extend(b'\0'*(raw-len(b)));b.extend(code+b'\0'*(size-len(code)))
  for off,site,count,target in sites:b[off:off+count]=b'\xe9'+struct.pack('<i',target-(site+5))+b'\x90'*(count-5)
  return bytes(b)

if __name__=='__main__':
  raise SystemExit('Use build_runtime.py for the complete verified patch chain')
