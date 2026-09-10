"""Conservative bone batching for the verified modern-M2 release in Parallels.

Patch every inlined kMaxBonesPerDraw use together: reducing just the clamp
would discard valid influences. The original triangle partitioner instead
retains triangles and rebuilds each section's bone lookup and render batches.
The 21-bone budget is an empirically verified compatibility setting, not a
claim that the virtual GPU exposes only 96 shader constants.
"""
import argparse
import hashlib
from pathlib import Path

from patch_wow import PatchError, Pe32

EXPECTED = 'daada1341ba3e480585fbaf16a7badea85c8e7141036a572c5c1e72001b65766'
RESULT = '76947b794d899280da55a639d6f6207c6e47be8d59904acdb61effcb55081d1d'
BUDGET = 21
SITES = (
  (0x2fd3, '66837cca0c4b'),  # SplitSubmeshes: detect over-budget sections
  (0x3567, '83f84b'),        # SplitSubmeshes: greedy triangle-bin capacity
  (0x569a, 'b94b000000'),    # FixSubmeshes: consistent fallback ceiling
  (0x9d81, 'b84b000000'),    # hkRenderBatchShadowMap: co-instance run budget
  (0x9ee7, 'b84b000000'),    # hkDrawBatchDoodad: co-instance run budget
)


def patch(source):
  if hashlib.sha256(source).hexdigest() != EXPECTED:
    raise PatchError('Unexpected modern-M2 module; use the original v1.0.0 release')
  data = bytearray(source)
  pe = Pe32(data)
  for rva, signature in SITES:
    expected = bytes.fromhex(signature)
    offset = pe.va_to_offset(pe.image_base + rva)
    if data[offset:offset + len(expected)] != expected:
      raise PatchError(f'Bone budget instruction mismatch at RVA {rva:#x}')
    data[offset + expected.index(75)] = BUDGET
  if hashlib.sha256(data).hexdigest() != RESULT:
    raise PatchError('Unexpected patched module hash')
  return bytes(data)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('source', type=Path)
  parser.add_argument('destination', type=Path)
  args = parser.parse_args()
  result = patch(args.source.read_bytes())
  with args.destination.open('xb') as target:
    target.write(result)
  print(RESULT)
