"""Verified-build repair of the native SKIN geoset-id DWORD read.

The modern level high word belongs to the triangle address, not the geoset ID.
Replace only the load + first comparison with an RX trampoline using MOVZX.
The original branches, visibility writer and rebuild request remain untouched.
"""
import hashlib
from pathlib import Path
import struct
from patch_wow import Pe32, PatchError, align_up

EXPECTED = '57dd8955fd7238b00969f6011cdaa13dca14daa5849d1f9be64152bd4c7fe5da'
SITE = 0x82C7ED
ORIGINAL = bytes.fromhex('8b0410394508')


def patch(source):
  if hashlib.sha256(source).hexdigest() != EXPECTED:
    raise PatchError('not the verified WarcraftXL-patched build 12340 executable')
  data = bytearray(source)
  pe = Pe32(data)
  at = pe.va_to_offset(SITE)
  if data[at:at+6] != ORIGINAL:
    raise PatchError('geoset instruction signature differs')
  last = pe.sections()[-1]
  rva = align_up(last.virtual_address + max(last.virtual_size, last.raw_size), pe.section_alignment)
  raw = align_up(len(data), pe.file_alignment)
  va = pe.image_base + rva
  # movzx eax, word ptr [eax+edx]; cmp [ebp+8], eax; jmp original JA
  code = bytes.fromhex('0fb70410394508') + b'\xe9' + struct.pack('<i', SITE + 6 - (va + 12))
  header = pe.section_table + pe.section_count * 40
  if header + 40 > pe.size_of_headers or any(data[header:header+40]):
    raise PatchError('no empty PE header slot')
  raw_size = align_up(len(code), pe.file_alignment)
  data[header:header+40] = struct.pack('<8sIIIIIIHHI', b'.wxlgeo', len(code), rva, raw_size, raw, 0, 0, 0, 0, 0x60000020)
  pe.set_u16(pe.file_header + 2, pe.section_count + 1)
  pe.set_u32(pe.optional + 56, align_up(rva + len(code), pe.section_alignment))
  pe.set_u32(pe.optional + 4, pe.u32(pe.optional + 4) + raw_size)
  pe.set_u32(pe.optional + 64, 0)
  data.extend(b'\0' * (raw - len(data)))
  data.extend(code + b'\0' * (raw_size - len(code)))
  data[at:at+6] = b'\xe9' + struct.pack('<i', va - (SITE + 5)) + b'\x90'
  return bytes(data)


def main():
  raise SystemExit('Use build_runtime.py for the complete verified patch chain')


if __name__ == '__main__':
  main()
