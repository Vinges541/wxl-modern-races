"""Match original NPC bake records to Retail HD resources; never guess IDs."""
import json
import argparse
import struct
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
DATA = ROOT / 'assets/appearance'


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--all', action='store_true', help='Queue all matched NPC bakes for the twenty race variants')
  args = parser.parse_args()
  modern = {r['ID']: r for r in json.loads((DATA / 'CreatureDisplayInfoExtra.json').read_text())}
  files = {r['MaterialResourcesID']: r['FileDataID'] for r in json.loads((DATA / 'TextureFileData.json').read_text()) if r['UsageType'] == 0}
  dbc = dbc_path('CreatureDisplayInfoExtra.dbc').read_bytes()
  count, fields, stride, _ = struct.unpack_from('<4I', dbc, 4)
  assert fields == 21 and stride == 84
  strings = dbc[20 + count * stride:]
  matched, missing = [], []
  for i in range(count):
    r = struct.unpack_from('<21I', dbc, 20 + i * stride)
    if r[1] not in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11) or r[2] not in (0, 1):
      continue
    old_name = strings[r[20]:].split(b'\0')[0].decode()
    if not old_name:
      continue
    row = modern.get(r[0])
    fid = files.get(row['HDBakeMaterialResourcesID']) if row else None
    if not row or (row['DisplayRaceID'], row['DisplaySexID']) != r[1:3] or not fid:
      missing.append(r[0])
      continue
    matched.append({'id': r[0], 'row': i, 'race': r[1], 'sex': r[2], 'file': fid,
                    'bakeName': old_name, 'appearance': list(r[3:8]), 'helmet': r[8]})
  (DATA / 'npc-plan.json').write_text(json.dumps({'matched': matched, 'missing': missing}, indent=2))
  # Fetch guards first; the remaining NPC requests are staged per race later.
  priority = [r['file'] for r in matched if r['id'] in (346, 1518)]
  requests = json.loads((DATA / 'texture-requests.json').read_text())
  if args.all:
    requests += [r['file'] for r in matched]
  (DATA / 'texture-requests.json').write_text(json.dumps(priority + sorted(set(requests) - set(priority))))
  print('NPC matched:', len(matched), 'missing:', len(missing), 'guard sources:', priority)


if __name__ == '__main__':
  main()
