"""Fail closed on cross-file mismatches before deploying the all-race package."""
import json
import struct
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path


def dbc_rows(data):
  assert data[:4] == b'WDBC'
  count, fields, stride, strings = struct.unpack_from('<4I', data, 4)
  assert stride == fields*4 and len(data) == 20+count*stride+strings
  return [struct.unpack_from('<'+str(fields)+'I', data, 20+i*stride) for i in range(count)], data[20+count*stride:]


def main():
  player = ROOT / 'build/all-appearance-v1'
  npc = ROOT / 'build/npc-appearance-all-v1'
  helmet = ROOT / 'build/all-appearance-helm-v1'
  report = json.loads((player / 'report.json').read_text())
  assert len(report['models']) == 20 and all(r['state'] in ('prepared', 'preserved-v5') for r in report['models'])
  assert len(json.loads((helmet / 'report.json').read_text())) == 20
  assert (helmet / 'Character/Human/Male/HumanMale.m2').read_bytes() == (ROOT / 'build/npc-appearance-v1/Character/Human/Male/HumanMale.m2').read_bytes()
  assert (player / 'DBFilesClient/CharSections.dbc').read_bytes() == (player / 'locale/DBFilesClient/CharSections.dbc').read_bytes()
  new, strings = dbc_rows((player / 'DBFilesClient/CharSections.dbc').read_bytes())
  old, _ = dbc_rows(dbc_path('CharSections.dbc').read_bytes())
  assert len(old) == len(new)
  texture_links = 0
  sizes = {0: [(256,256)], 1: [(128,64),(128,32)], 2: [(128,64),(128,32)],
           3: [None,(128,64),(128,32)], 4: [(128,64)]}
  for before, after in zip(old, new):
    assert before[:4] == after[:4] and before[7:] == after[7:]
    for slot, p in enumerate(after[4:7]):
      path = strings[p:strings.index(0,p)].decode() if p else ''
      if 'Appearance' not in path:
        continue
      file = player / path.replace('\\','/')
      assert file.is_file(), path
      data = file.read_bytes()
      expected = sizes[after[3]][slot]
      assert expected is None or struct.unpack_from('<II',data,12) == expected, path
      if expected is None:
        assert data[8] == 2, path
      texture_links += 1
  original, _ = dbc_rows(dbc_path('CreatureDisplayInfoExtra.dbc').read_bytes())
  patched, names = dbc_rows((npc / 'DBFilesClient/CreatureDisplayInfoExtra.dbc').read_bytes())
  assert len(original) == len(patched)
  npc_count = 0
  for before, after in zip(original, patched):
    assert before[:20] == after[:20]
    name = names[after[20]:names.index(0,after[20])].decode() if after[20] else ''
    if name.startswith('wxl-npc-'):
      assert (npc / 'Textures/BakedNpcTextures' / name).is_file()
      npc_count += 1
  assert npc_count == 13706
  checked = 0
  for root in (player, npc):
    for file in root.rglob('*.blp'):
      data = file.read_bytes()
      assert data[:4] == b'BLP2', str(file)
      width, height = struct.unpack_from('<II',data,12)
      assert width and height and not width & (width-1) and not height & (height-1), str(file)
      offsets = struct.unpack_from('<16I',data,20)
      lengths = struct.unpack_from('<16I',data,84)
      assert offsets[0] and lengths[0]
      assert all(o+n <= len(data) for o,n in zip(offsets,lengths)), str(file)
      checked += 1
  result = {'models':20, 'textureLinks':texture_links, 'npcBakes':npc_count, 'blpFilesChecked':checked,
            'runtimeVerified':False, 'unmatchedNpcs':15, 'approximateDkRows':384}
  (player / 'audit.json').write_text(json.dumps(result,indent=2))
  print(result)


if __name__ == '__main__':
  main()
