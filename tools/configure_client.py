"""Reproduce the confirmed WoTLK Wine/mtld3d settings without replacing user config.

Preview by default. --check returns 1 for drift; --apply requires WoW to be closed.
No game assets, executables, launcher, account or server settings are modified.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


@dataclass(frozen=True)
class Setting:
  key: str
  value: str
  reason: str


# These are compatibility settings / the user's launch preference, not a graphics preset.
PROFILE = {
  'WTF/Config.wtf': ('wtf', (
    Setting('shadowInstancing', '0', 'Confirmed workaround for oversized creature shadows; shadows stay enabled.'),
    Setting('gxWindow', '0', 'Requested fullscreen mode.'),
    Setting('gxApi', 'd3d9', 'Matches the working Wine launcher (-d3d9).'),
  )),
  'mtld3d.conf': ('mtld3d', (
    Setting('shaderCache.enable', 'false', 'Confirmed workaround for texture corruption during shader pre-warm.'),
  )),
}


class SettingsError(ValueError):
  pass


@dataclass(frozen=True)
class FileChange:
  path: Path
  before: bytes | None
  after: bytes
  settings: list[dict]

  @property
  def changed(self) -> bool:
    return self.before != self.after


def update_settings(data: bytes, kind: str, settings: tuple[Setting, ...]) -> tuple[bytes, list[dict]]:
  """Edit only managed ASCII keys; preserve unrelated bytes, comments, BOM and EOLs."""
  if kind not in ('wtf', 'mtld3d') or b'\0' in data:
    raise SettingsError('Unsupported configuration format')
  bom = b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b''
  body = data[len(bom):]
  newline = b'\r\n' if b'\r\n' in body else b'\n'
  report = []
  for setting in settings:
    key = re.escape(setting.key.encode('ascii'))
    if kind == 'wtf':
      prefix = rb'[ \t]*SET[ \t]+' + key
      candidate = re.compile(rb'^' + prefix + rb'(?=[ \t]|$)', re.I)
      pattern = re.compile(rb'^(' + prefix + rb'[ \t]+)"([^"\r\n]*)"([ \t]*(?:(?://|#).*)?)$', re.I)
      canonical = b'SET ' + setting.key.encode() + b' "' + setting.value.encode() + b'"'
    else:
      prefix = rb'[ \t]*' + key
      candidate = re.compile(rb'^' + prefix + rb'(?=[ \t=]|$)', re.I)
      pattern = re.compile(rb'^(' + prefix + rb'[ \t]*=[ \t]*)([^ \t#\r\n]+)([ \t]*(?:#.*)?)$', re.I)
      canonical = setting.key.encode() + b' = ' + setting.value.encode()
    previous = []
    output = []
    for line in body.splitlines(keepends=True):
      content = line.rstrip(b'\r\n')
      eol = line[len(content):]
      if not candidate.match(content):
        output.append(line)
        continue
      match = pattern.fullmatch(content)
      if not match:
        raise SettingsError(f'Malformed managed setting: {setting.key}')
      previous.append(match[2].decode('ascii', errors='backslashreplace'))
      if len(previous) == 1:
        value = setting.value.encode()
        if kind == 'wtf':
          value = b'"' + value + b'"'
        output.append(match[1] + value + match[3] + eol)
      elif match[3].strip():
        # Preserve comments from redundant definitions, but not conflicting values.
        output.append(match[3].lstrip() + eol)
    body = b''.join(output)
    if not previous:
      if body and not body.endswith((b'\n', b'\r')):
        body += newline
      body += canonical + newline
    report.append({'key': setting.key, 'before': previous, 'after': setting.value, 'reason': setting.reason})
  return bom + body, report


def safe_path(root: Path, relative: str) -> Path:
  path = root
  for part in Path(relative).parts:
    path = path / part
    if path.is_symlink():
      raise SettingsError(f'Refusing symlink: {path}')
  return path


def plan(client: Path) -> list[FileChange]:
  exe = safe_path(client, 'Wow.exe')
  with exe.open('rb') as source:
    if source.read(2) != b'MZ' or not (client / 'Data').is_dir():
      raise SettingsError('Expected a WoW Windows client (Wow.exe and Data)')
  result = []
  for relative, (kind, settings) in PROFILE.items():
    path = safe_path(client, relative)
    before = path.read_bytes() if path.exists() else None
    after, details = update_settings(before or b'', kind, settings)
    result.append(FileChange(path, before, after, details))
  return result


def require_wow_closed() -> None:
  """Conservative process check for the supported macOS/Linux Wine host."""
  if sys.platform not in ('darwin', 'linux'):
    raise SettingsError('--apply is supported on macOS/Linux Wine hosts only')
  try:
    processes = subprocess.run(['ps', '-ax', '-o', 'args='], check=True,
                               capture_output=True, text=True, timeout=10).stdout
  except (OSError, subprocess.SubprocessError) as exc:
    raise SettingsError('Cannot check running processes; no settings written') from exc
  if re.search(r'''(?:^|[/\\\s"'])Wow(?:-64)?\.exe(?=$|[\s"'])''', processes, re.I | re.M):
    raise SettingsError('Close WoW before --apply: it can overwrite Config.wtf on exit')


def atomic_write(path: Path, data: bytes, mode: int) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  descriptor, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
  temporary = Path(name)
  try:
    with os.fdopen(descriptor, 'wb') as target:
      target.write(data)
      target.flush()
      os.fsync(target.fileno())
      os.fchmod(target.fileno(), mode)
    os.replace(temporary, path)
  finally:
    temporary.unlink(missing_ok=True)


def apply_changes(client: Path, changes: list[FileChange]) -> Path | None:
  pending = [change for change in changes if change.changed]
  if not pending:
    return None
  require_wow_closed()
  # Recheck every input before making a backup or writing anything.
  for change in pending:
    safe_path(client, str(change.path.relative_to(client)))
    current = change.path.read_bytes() if change.path.exists() else None
    if current != change.before:
      raise SettingsError('Configuration changed after preview; rerun the command')
  parent = safe_path(client, 'DisabledPatches/ClientSettings')
  parent.mkdir(parents=True, exist_ok=True)
  backup = Path(tempfile.mkdtemp(prefix='before-', dir=parent))
  manifest = {'profile': 'wine-mtld3d', 'files': []}
  # Back up ALL inputs before committing ANY writes. Backups can contain account names.
  for change in pending:
    relative = str(change.path.relative_to(client))
    if change.before is not None:
      atomic_write(backup / relative, change.before, 0o600)
    manifest['files'].append({'path': relative, 'existed': change.before is not None,
                              'sha256': hashlib.sha256(change.before).hexdigest() if change.before is not None else None})
  atomic_write(backup / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode(), 0o600)
  try:
    for change in pending:
      mode = stat.S_IMODE(change.path.stat().st_mode) if change.before is not None else 0o600
      atomic_write(change.path, change.after, mode)
      if change.path.read_bytes() != change.after:
        raise SettingsError('Configuration read-back verification failed')
  except (OSError, SettingsError) as exc:
    raise SettingsError(f'Apply incomplete; original files are in {backup}: {exc}') from exc
  return backup


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--client', type=Path, required=True, help='existing client directory; never inferred')
  mode = parser.add_mutually_exclusive_group()
  mode.add_argument('--dry-run', action='store_true', help='preview only (the default)')
  mode.add_argument('--check', action='store_true', help='read-only; exit 1 if settings differ')
  mode.add_argument('--apply', action='store_true', help='back up and apply; close WoW first')
  args = parser.parse_args(argv)
  try:
    client = args.client.expanduser().resolve()
    changes = plan(client)
    for change in changes:
      print(f'{change.path.relative_to(client)}: {"CHANGE" if change.changed else "OK"}')
      for setting in change.settings:
        print(json.dumps(setting, ensure_ascii=True))
    if args.apply:
      backup = apply_changes(client, changes)
      print(f'Applied; backup: {backup}' if backup else 'Already configured; nothing written.')
    elif not args.check:
      print('Preview only. Close WoW and pass --apply to write these settings.')
    return int(args.check and any(change.changed for change in changes))
  except (OSError, SettingsError) as exc:
    print(f'error: {exc}', file=sys.stderr)
    return 2


if __name__ == '__main__':
  raise SystemExit(main())
