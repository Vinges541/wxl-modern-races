"""Small post-conversion fixes; leave vertex data, UVs and animation tracks intact."""
import struct
from .appearance import array


def fix_undead_torso(data):
  """Expose the default Bony back without changing any draw/shadow indices.

  Build 12340 hides ids 0..2000, then selects only slots 0..18. Retail
  Scourge's back is group 19: choice Bony selects 1901; Mottled/Fresh 1902.
  Freeze only 1901 as base geometry (0), leaving 1902 hidden. The other
  Bony parts (2901/3001) are already frozen by appearance preparation.
  """
  if len(data) < 60 or data[:4] != b'SKIN':
    raise ValueError('expected modern SKIN header')
  count, start = array(data, 28, 48)
  if count == 0 or start < 60:
    raise ValueError('expected nonempty skin sections outside the header')
  sections = [start+i*48 for i in range(count)]
  group = [(at, struct.unpack_from('<H', data, at)[0]) for at in sections
           if 1900 <= struct.unpack_from('<H', data, at)[0] < 2000]
  if sorted(gid for _, gid in group) != [1901, 1902]:
    raise ValueError('expected exactly the two Scourge back variants 1901/1902')
  # Both batch tables must remain valid and byte-identical after the change.
  for header, stride in ((36, 24), (48, 12)):
    n, offset = array(data, header, stride)
    if n and offset < 60:
      raise ValueError('batch table overlaps header')
    for i in range(n):
      if struct.unpack_from('<H', data, offset+i*stride+4)[0] >= count:
        raise ValueError('invalid draw/shadow section reference')
  out = bytearray(data)
  at = next(at for at, gid in group if gid == 1901)
  struct.pack_into('<H', out, at, 0)
  return bytes(out), {'defaultBack': 1901, 'hiddenBack': 1902, 'offset': at,
                      'changedBytes': 2, 'runtimeVerified': False}


def fix_sections(data, *, jaw=False, exclude_primalist=False):
  skin = bytearray(data)
  if skin[:4] != b'SKIN':
    raise ValueError('expected SKIN')
  count, start = array(skin, 28, 48)
  batch_count, batches = array(skin, 36, 24)
  mapping, sections, removed = {}, [], []
  jaw_count = 0
  for i in range(count):
    section = bytearray(skin[start+i*48:start+(i+1)*48])
    gid = struct.unpack_from('<H', section)[0]
    # Retail ChrCustomizationGeoset 11398..11401 are optional Primalist
    # Earth/Fire/Air/Water eyes, not the ordinary racial iris/glow.
    if (jaw and 200 <= gid < 300 and gid != 202) or (exclude_primalist and gid in (1702, 1703, 1704, 1705)):
      removed.append(gid)
      continue
    if jaw and gid == 202:
      struct.pack_into('<H', section, 0, 0)
      jaw_count += 1
    mapping[i] = len(sections)
    sections.append(section)
  if jaw and not jaw_count:
    raise ValueError('expected intact jaw 202')
  kept_batches = []
  for i in range(batch_count):
    batch = bytearray(skin[batches+i*24:batches+(i+1)*24])
    sid = struct.unpack_from('<H', batch, 4)[0]
    if sid >= count:
      raise ValueError('invalid section reference')
    if sid in mapping:
      struct.pack_into('<H', batch, 4, mapping[sid])
      kept_batches.append(batch)
  for at, records in ((28, sections), (36, kept_batches)):
    skin.extend(b'\0' * (-len(skin) % 16))
    offset = len(skin)
    skin.extend(b''.join(records))
    struct.pack_into('<II', skin, at, len(records), offset)
  return bytes(skin), {'removed': removed, 'intactJawSections': jaw_count}
