import json
import sys
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.helm import adapt_helmet_anchor
from read_legacy_asset import read_asset


def main():
  rel = Path('Character/Human/Male/HumanMale.m2')
  source = (ROOT / 'build/human-appearance-v5' / rel).read_bytes()
  legacy = read_asset(str(rel))
  model, report = adapt_helmet_anchor(source, legacy)
  out = ROOT / 'build/npc-appearance-v1'
  (out / rel).parent.mkdir(parents=True, exist_ok=True)
  (out / rel).write_bytes(model)
  (out / 'helmet-report.json').write_text(json.dumps(report, indent=2))
  print(report)


if __name__ == '__main__':
  main()
