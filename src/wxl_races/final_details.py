"""Small post-conversion fixes; leave vertex data, UVs and animation tracks intact."""
import struct
from .appearance import array


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
