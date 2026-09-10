#!/usr/bin/env python3
"""Prepare the 20 HD player-model variants as an experimental WXL directory patch."""
import json
from pathlib import Path
import shutil
import sys

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
from source_profile import validate_models
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.bundle import audit, stage
from wxl_races.chunks import inspect_asset
from wxl_races.resolver import ExportIndex
from wxl_races.skeleton import assemble


def main():
  status = json.loads((ROOT / 'assets/all_races_hd/status.json').read_text())
  models = validate_models(status)
  raw = ROOT / 'assets/all_races_hd/raw'
  prepared = ROOT / 'build/all-races-prepared'
  output = ROOT / 'build/Patch-ModernRaces-HD.MPQ'
  reports = ROOT / 'build/all-races-reports'
  reports.mkdir(parents=True, exist_ok=True)
  index = ExportIndex(raw, list(raw.rglob('*.files.manifest.json')))
  summary = {'experimental': True, 'runtimeVerified': False, 'sourceBuild': status.get('build'), 'models': []}
  for model in models:
    slug = f"{model['race'].lower()}_{model['sex'].lower()}"
    legacy = f"Character/{model['race']}/{model['sex']}/{model['race']}{model['sex']}.m2"
    target = {
      'schemaVersion': 1, 'race': model['race'], 'sex': model['sex'],
      'source': {'modelPath': model['modelPath'], 'fileDataId': model['fileDataId']},
      'target': {'clientBuild': 12340, 'legacyPath': legacy},
    }
    manifest_path = reports / f'{slug}.target.json'
    manifest_path.write_text(json.dumps(target, indent=2) + '\n')
    result = {'race': model['race'], 'sex': model['sex'], 'fileDataId': model['fileDataId']}
    summary['models'].append(result)
    try:
      if model['state'] != 'complete':
        raise RuntimeError(f"source export is {model['state']}: {model.get('error', '')}")
      source_report = audit(target, index)
      (reports / f'{slug}.source.json').write_text(json.dumps(source_report, indent=2))
      if not source_report['readyToStage']:
        raise RuntimeError('; '.join(source_report['errors']))
      source = Path(source_report['sourceModel'])
      info = source_report['model']
      dependencies = source_report['dependencies']
      animations = {
        a['fileDataId']: Path(a['path']).read_bytes()
        for a in dependencies['animations'] if a['fileDataId'] and a['path']
      }
      if info.get('skid'):
        skel = Path(dependencies['skeleton']['path'])
        converted, flat_anims, conversion = assemble(source.read_bytes(), skel.read_bytes(), animations)
      else:
        converted, flat_anims, conversion = source.read_bytes(), animations, {'skeletonAlreadyInline': True}
      destination = prepared / model['modelPath']
      destination.parent.mkdir(parents=True, exist_ok=True)
      destination.write_bytes(converted)
      files = [{'fileDataID': model['fileDataId'], 'file': str(destination)}]
      copied = set()
      for kind in ('skins', 'lodSkins', 'textures', 'animations'):
        for dependency in dependencies[kind]:
          source_path = dependency.get('path')
          if not source_path or source_path in copied:
            continue
          copied.add(source_path)
          source_path = Path(source_path)
          relative = source_path.relative_to(raw)
          dest = prepared / relative
          dest.parent.mkdir(parents=True, exist_ok=True)
          file_id = dependency['fileDataId']
          if kind == 'animations':
            dest.write_bytes(flat_anims[file_id])
          else:
            shutil.copy2(source_path, dest)
          files.append({'fileDataID': file_id, 'file': str(dest)})
      prepared_manifest = prepared / f'{slug}.files.manifest.json'
      prepared_manifest.write_text(json.dumps({'files': files}, indent=2))
      prepared_index = ExportIndex(prepared, [prepared_manifest])
      check = audit(target, prepared_index)
      if not check['readyForCurrentWarcraftXL']:
        raise RuntimeError('converted model failed compatibility audit: ' + str(check['errors']))
      staged = stage(target, prepared_index, output)
      (reports / f'{slug}.staged.json').write_text(json.dumps(staged, indent=2))
      result.update(state='prepared', conversion=conversion, stagedFiles=len(staged['staged']))
      print(slug, 'prepared', flush=True)
    except Exception as error:
      result.update(state='failed', error=str(error))
      print(slug, 'FAILED:', error, flush=True)
  summary['all20Prepared'] = len(summary['models']) == 20 and all(m['state'] == 'prepared' for m in summary['models'])
  summary['limitations'] = [
    'Runtime rendering and animation playback have not been verified in Windows.',
    'Dynamic skin, face, hair and equipment texture composition still uses the WotLK character system.',
    'Retail geoset/customization mappings and HD texture atlases are not yet ported.',
    'FacePose BFID variants are omitted.',
  ]
  (reports / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
  if output.exists():
    (output / 'bundle-report.json').write_text(json.dumps(summary, indent=2) + '\n')
  return 0 if summary['all20Prepared'] else 2


if __name__ == '__main__':
  raise SystemExit(main())
