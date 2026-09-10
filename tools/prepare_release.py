"""Prepare all 20 race variants in a NEW private workspace; never deploy to a client.

Input contract: assets/all_races_hd/{status.json,raw/}, assets/appearance/*.json
and textures/. Export inputs with the hooks documented in docs/BUILD.md first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from source_profile import validate_models

SOURCE = Path(__file__).resolve().parents[1]
STEPS = (
  ('prepare_all_races.py',),
  ('plan_human_appearance.py',),
  ('plan_all_appearance.py',),
  ('plan_npc_appearance.py', '--all'),
  ('build_human_appearance.py', '--legacy-resolution'),
  ('build_guard_helm.py',),
  ('build_all_appearance.py',),
  ('resolve_dk_face_fallbacks.py',),
  ('build_npc_appearance.py', '--all'),
  ('adapt_all_helm_anchors.py',),
  ('audit_all_candidate.py',),
  ('repair_all_geometry.py',),
  ('prepare_details_v1.py',),
)


def copy_tree(source, destination):
  for path in sorted(source.rglob('*')):
    if path.is_symlink():
      raise ValueError(f'Symlink in prepared tree: {path}')
    if path.is_file():
      target = destination / path.relative_to(source)
      target.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy2(path, target)


def assemble(workspace, locale):
  """Explicit last-writer order; final package contains assets, not old diagnostic files."""
  build = workspace / 'build'
  release = build / 'release'
  patch = release / 'Data/Patch-ModernRaces-HD.MPQ'
  base = build / 'Patch-ModernRaces-HD.MPQ'
  for directory in ('Character',):
    copy_tree(base / directory, patch / directory)
  for candidate in ('all-appearance-v1', 'npc-appearance-all-v1', 'all-appearance-helm-v1', 'all-appearance-geometry-v2'):
    for directory in ('Character', 'Textures', 'DBFilesClient'):
      source = build / candidate / directory
      if source.exists():
        copy_tree(source, patch / directory)
  copy_tree(build / 'details-v1/Data/Patch-ModernRaces-HD.MPQ', patch)
  # Runtime fix no longer depends on whatever happens to be installed in the client.
  from repair_runtime_v2 import inline_talk, shadows
  from repair_tauren_talk_event import repair
  for sex in ('Male', 'Female'):
    directory = patch / 'Character/Tauren' / sex
    model = directory / f'Tauren{sex}.m2'
    animation = directory / f'Tauren{sex}0060-00.anim'
    model_data, animation_data = model.read_bytes(), animation.read_bytes()
    if sex == 'Male':
      model_data, animation_data = repair(model_data, animation_data)
      animation.write_bytes(animation_data)
    data, _ = inline_talk(model_data, animation_data)
    model.write_bytes(data)
  for skin in sorted((patch / 'Character').glob('*/*/*.skin')):
    data, _ = shadows((base / skin.relative_to(patch)).read_bytes(), skin.read_bytes())
    skin.write_bytes(data)
  tables = patch / 'DBFilesClient'
  if {p.name for p in tables.iterdir()} != {'CharSections.dbc', 'CreatureDisplayInfoExtra.dbc'}:
    raise ValueError('Unexpected DBC override; scale overrides are forbidden')
  copy_tree(tables, release / f'Data/{locale}/patch-{locale}-ModernRaces.MPQ/DBFilesClient')
  models = sorted((patch / 'Character').glob('*/*/*.m2'))
  if len(models) != 20:
    raise ValueError('Expected exactly 20 final models')
  entries = []
  for path in sorted(release.rglob('*')):
    if path.is_file() and path.name != 'release-manifest.json':
      entries.append({'path': path.relative_to(release).as_posix(),
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size})
  manifest = {'schemaVersion': 1, 'kind': 'wxl-modern-races-assets', 'locale': locale,
              'runtimeVerified': False, 'files': entries}
  (release / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
  return release


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--workspace', type=Path, required=True, help='private inputs; build/ must not exist')
  parser.add_argument('--client', type=Path, required=True, help='original MPQs, read-only')
  parser.add_argument('--dbc-dir', type=Path, required=True, help='original locale-matched DBCs')
  parser.add_argument('--stormlib', type=Path, required=True)
  parser.add_argument('--locale', required=True, choices=('ruRU', 'enUS', 'enGB', 'deDE', 'frFR', 'esES', 'esMX', 'koKR', 'zhCN', 'zhTW'))
  parser.add_argument('--build', action='store_true', help='execute; default only validates inputs and prints steps')
  args = parser.parse_args(argv)
  work = args.workspace.expanduser().resolve()
  if sys.flags.optimize or os.environ.get('PYTHONOPTIMIZE'):
    parser.error('Optimized Python is unsupported: conversion assertions are safety checks')
  try:
    if (work / 'build').exists():
      raise ValueError('Use a fresh workspace without build/; do not mix historical candidates')
    status = json.loads((work / 'assets/all_races_hd/status.json').read_text())
    appearance = json.loads((work / 'assets/appearance/build.json').read_text())
    key = status.get('build', {}).get('BuildConfig')
    if not key or key != appearance.get('BuildConfig'):
      raise ValueError('Model and appearance exports must come from the same pinned BuildConfig')
    validate_models(status)
    for path in (args.client / 'Data/common.MPQ', args.dbc_dir / 'CharSections.dbc',
                 args.dbc_dir / 'CreatureDisplayInfoExtra.dbc', args.stormlib):
      if not path.is_file():
        raise ValueError(f'Missing input: {path}')
    for step in STEPS:
      print(' '.join(step), flush=True)
    if not args.build:
      print('Preview only; use --build to prepare assets. Client is never modified.')
      return 0
    env = dict(os.environ, WXL_WORKSPACE=str(work), WXL_CLIENT=str(args.client.resolve()),
               WXL_DBC_DIR=str(args.dbc_dir.resolve()), WXL_STORMLIB=str(args.stormlib.resolve()),
               PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(SOURCE / 'src'))
    # Child processes get explicit inputs; no installation command occurs in this pipeline.
    for step in STEPS:
      subprocess.run([sys.executable, str(SOURCE / 'tools' / step[0]), *step[1:]], env=env, check=True)
    # The helpers below do not read environment-dependent paths.
    print(assemble(work, args.locale))
    return 0
  except (OSError, ValueError, subprocess.CalledProcessError) as exc:
    print(f'error: {exc}', file=sys.stderr)
    return 2


if __name__ == '__main__':
  raise SystemExit(main())
