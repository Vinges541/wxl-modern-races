"""Correct full-face/hand selection without rebuilding installed textures."""
import json
import struct
import sys
from pathlib import Path
from read_legacy_asset import read_asset

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.appearance import repair_human
from wxl_races.helm import adapt_helmet_anchor


def main():
  rows = json.loads((ROOT / 'build/all-appearance-v1/report.json').read_text())['models']
  out = ROOT / 'build/all-appearance-geometry-v2'
  reports = []
  for row in rows:
    race, sex = row['race'], row['sex']
    if (race, sex) == ('Human', 'Male'):
      continue
    prefix = f'Character/{race}/{sex}'
    original = ROOT / 'build/Patch-ModernRaces-HD.MPQ' / prefix
    defaults = set(row['defaults'])
    defaults.discard(3201)
    defaults.update((3202, 2301))
    source_skins = {p.name: p.read_bytes() for p in original.glob('*.skin')}
    for name, skin in source_skins.items():
      count, offset = struct.unpack_from('<II', skin, 28)
      ids = {struct.unpack_from('<H', skin, offset+i*48)[0] for i in range(count)}
      if 3201 in ids and 3202 not in ids:
        raise ValueError(f'{race} {sex} {name}: no full-face section')
    model, skins, stats = repair_human((original / f'{race}{sex}.m2').read_bytes(), source_skins,
      prefix+'/HD-Eyes.blp', default_geosets=defaults,
      static_bindings={int(k): v for k,v in row.get('staticBindings',{}).items()})
    model, anchor = adapt_helmet_anchor(model, read_asset(prefix+f'/{race}{sex}.m2'), preserve_parent_offset=True)
    target = out / prefix
    target.mkdir(parents=True, exist_ok=True)
    (target / f'{race}{sex}.m2').write_bytes(model)
    for name, data in skins.items():
      (target / name).write_bytes(data)
      assert 3202 not in stats['removedGeosets'][name]
      assert 2301 not in stats['removedGeosets'][name]
    reports.append({'race':race,'sex':sex,'defaults':sorted(defaults),'geometry':stats,'helmet':anchor})
    print(race, sex, 'full face and available hands retained', flush=True)
  assert len(reports) == 19
  (out / 'report.json').write_text(json.dumps(reports,indent=2))


if __name__ == '__main__':
  main()
