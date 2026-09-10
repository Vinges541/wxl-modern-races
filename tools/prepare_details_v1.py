"""Prepare jaw and Retail eye-variant selection fixes. Never modifies scale."""
import json
import struct
import sys
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.final_details import fix_sections


def main():
  out = ROOT / 'build/details-v1'
  patch = out / 'Data/Patch-ModernRaces-HD.MPQ'
  source = ROOT / 'build/all-appearance-geometry-v2/Character/Scourge/Female'
  report = {'runtimeVerified': False, 'elfEffects': {}, 'jaw': {}, 'scale': {}}
  for race in ('NightElf', 'BloodElf'):
    for sex in ('Male', 'Female'):
      prefix = Path('Character') / race / sex
      for f in sorted((ROOT / 'build/all-appearance-geometry-v2' / prefix).glob('*.skin')):
        data, stats = fix_sections(f.read_bytes(), exclude_primalist=True)
        assert set(stats['removed']) == {1702, 1703, 1704, 1705}
        target = patch / prefix / f.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        report['elfEffects'][str(prefix / f.name)] = stats
  assert len(report['elfEffects']) == 28
  for f in sorted(source.glob('*.skin')):
    data, stats = fix_sections(f.read_bytes(), jaw=True)
    target = patch / 'Character/Scourge/Female' / f.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    report['jaw'][f.name] = stats
  assert len(report['jaw']) == 7
  # Scale experiments were rolled back. This pass only changes eye/jaw geosets.
  (out / 'report.json').write_text(json.dumps(report, indent=2))
  print(json.dumps(report, indent=2))


if __name__ == '__main__':
  main()
