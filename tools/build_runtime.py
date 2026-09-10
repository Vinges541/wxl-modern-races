"""Reproduce the verified v8 executable and v6 module into a NEW private directory."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from patch_wow import patched_bytes, EXPECTED_WOW_SHA256, PatchError
from patch_geoset_visibility import patch as geoset
from patch_shadow_indices import patch as shadow_indices
from patch_shadow_buffer import patch as shadow_buffer
from patch_event_guard import patch as event_guard
from patch_anim_loader import patch as animation_loader
from patch_shadow_bone_budget import patch as bone_budget

OUTPUT_HASHES = {
  'Wow.exe': '50e16ecacac5ab77b083c2a56a2b92b4bac69a00749652756f9d3cc369491985',
  'WarcraftXL.dll': '0723d3b115d60ad8aca27bc5caaff8dffa113efb491251d9db0fa4e22426f09d',
  'Extensions/wxl-modern-m2/wxl-modern-m2.dll': '76947b794d899280da55a639d6f6207c6e47be8d59904acdb61effcb55081d1d',
}


def build(exe, core, module):
  if hashlib.sha256(exe).hexdigest() != EXPECTED_WOW_SHA256:
    raise PatchError('Supply the original, unmodified build-12340 executable')
  exe, _ = patched_bytes(exe)
  for transform in (geoset, shadow_indices, shadow_buffer, event_guard, animation_loader):
    exe = transform(exe)
  outputs = dict(zip(OUTPUT_HASHES, (exe, core, bone_budget(module))))
  for name, data in outputs.items():
    if hashlib.sha256(data).hexdigest() != OUTPUT_HASHES[name]:
      raise PatchError(f'Runtime hash differs from the verified profile: {name}')
  return outputs


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--original-exe', type=Path, required=True)
  parser.add_argument('--core', type=Path, required=True)
  parser.add_argument('--module', type=Path, required=True, help='original wxl-modern-m2 v1.0.0 DLL')
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args(argv)
  try:
    if args.output.exists() or args.output.is_symlink():
      raise ValueError('Output must be a new directory, never an installed client')
    outputs = build(args.original_exe.read_bytes(), args.core.read_bytes(), args.module.read_bytes())
    args.output.mkdir(parents=True)
    entries = []
    for name, data in outputs.items():
      path = args.output / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(data)
      entries.append({'path': name, 'sha256': OUTPUT_HASHES[name], 'size': len(data)})
    (args.output / 'release-manifest.json').write_text(json.dumps({
      'schemaVersion': 1, 'kind': 'wxl-modern-races-runtime', 'files': entries,
      'redistributable': False, 'note': 'Contains the user-supplied game executable; never publish this directory.',
    }, indent=2) + '\n')
    print('Runtime prepared and hashes verified; NOT installed. Do not redistribute Wow.exe.')
    return 0
  except (OSError, ValueError, PatchError) as exc:
    print(f'error: {exc}', file=sys.stderr)
    return 2


if __name__ == '__main__':
  raise SystemExit(main())
