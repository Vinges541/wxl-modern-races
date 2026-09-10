"""Use the validated Human helmet-anchor adaptation on each prepared variant."""
import json
import sys
from pathlib import Path
from read_legacy_asset import read_asset

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.helm import adapt_helmet_anchor


def main():
  source = ROOT / 'build/all-appearance-v1'
  rows = json.loads((source / 'report.json').read_text())['models']
  if len(rows) != 20 or any(r['state'] == 'failed' for r in rows):
    raise ValueError('All twenty models must be prepared before the helmet pass')
  out = ROOT / 'build/all-appearance-helm-v1'
  reports = []
  for row in rows:
    race, sex = row['race'], row['sex']
    rel = Path(f'Character/{race}/{sex}/{race}{sex}.m2')
    legacy = read_asset(str(rel))
    converted, report = adapt_helmet_anchor((source / rel).read_bytes(), legacy,
      preserve_parent_offset=(race, sex) != ('Human', 'Male'))
    (out / rel).parent.mkdir(parents=True, exist_ok=True)
    (out / rel).write_bytes(converted)
    reports.append({'race': race, 'sex': sex, **report})
    print(race, sex, report['before'], '->', report['after'], flush=True)
  (out / 'report.json').write_text(json.dumps(reports, indent=2))


if __name__ == '__main__':
  main()
