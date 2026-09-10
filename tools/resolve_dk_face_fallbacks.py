"""Prevent unmapped DK-only face rows from sampling an incompatible legacy atlas.

These are explicit corresponding ordinary-HD-face fallbacks, not an exact
reproduction of Wrath's extra DK face artwork. Class flags and IDs are preserved.
"""
import json
import struct
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path


def main():
  out = ROOT / 'build/all-appearance-v1'
  original = dbc_path('CharSections.dbc').read_bytes()
  dbc = bytearray((out / 'DBFilesClient/CharSections.dbc').read_bytes())
  n, f, stride, _ = struct.unpack_from('<4I', dbc, 4)
  assert f == 10 and stride == 40
  rows = [struct.unpack_from('<10I', original, 20+i*stride) for i in range(n)]
  by = {(r[1], r[2], r[3], r[8], r[9]): i for i, r in enumerate(rows)}
  plans = json.loads((ROOT / 'assets/appearance/all-appearance-plan.json').read_text())
  fallbacks = []
  for plan in plans:
    normal = [r[8] for r in rows if r[1:4] == (plan['raceId'], plan['sexId'], 1) and not r[7] & 4]
    if not normal:
      continue
    base = max(normal)+1
    for missing in plan['unmapped']:
      i = missing['row']
      row = rows[i]
      if row[3] != 1 or not row[7] & 4:
        raise ValueError(f'Unsupported unmapped row: {row[0]}')
      reference = by.get((row[1], row[2], 1, row[8]-base, row[9]))
      if reference is None:
        raise ValueError(f'No corresponding ordinary face for {row[0]}')
      at, ref_at = 20+i*stride+16, 20+reference*stride+16
      paths = struct.unpack_from('<3I', dbc, ref_at)
      strings = dbc[20+n*stride:]
      if not all(b'Appearance' in strings[p:strings.index(0,p)] for p in paths[:2]):
        raise ValueError('Fallback source must already use a converted HD face')
      struct.pack_into('<3I', dbc, at, *paths)
      fallbacks.append({'id': row[0], 'race': row[1], 'sex': row[2], 'ordinaryFaceRowId': rows[reference][0]})
  for directory in ('DBFilesClient', 'locale/DBFilesClient'):
    (out / directory / 'CharSections.dbc').write_bytes(dbc)
  (out / 'dk-fallbacks.json').write_text(json.dumps({'approximate': True, 'rows': fallbacks}, indent=2))
  print('Explicit corresponding-face DK fallbacks:', len(fallbacks))


if __name__ == '__main__':
  main()
