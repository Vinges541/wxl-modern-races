"""Check exactly the Git publication inventory, never scan private export directories."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'assets', 'build', 'cache', 'vendor', '_local', '.venv', 'dist'}
BINARY = {'.m2', '.skin', '.anim', '.blp', '.dbc', '.db2', '.mpq', '.exe', '.dll',
          '.dylib', '.so', '.zip', '.7z', '.mov', '.png', '.jpg'}
SECRETS = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')
PERSONAL = re.compile(rb'/Users/[A-Za-z0-9_.-]+/')


def check_file(root, name):
  relative = Path(name)
  if relative.is_absolute() or '..' in relative.parts:
    return 'unsafe inventory path'
  if relative.parts[0] in PRIVATE or relative.suffix.lower() in BINARY or relative.name.startswith('.env'):
    return 'private/exported/binary file in publication inventory'
  path = root / relative
  if path.is_symlink() or not path.is_file():
    return 'not a regular source file'
  data = path.read_bytes()
  if b'\0' in data:
    return 'binary content'
  if SECRETS.search(data):
    return 'credential-like content (value redacted)'
  # Explicitly allow synthetic process-list fixtures, never the local account name.
  fixture_prefix = b'/Users/' + b'a/'
  filtered = data.replace(fixture_prefix, b'<fixture>/') if relative.parts[0] == 'tests' else data
  if PERSONAL.search(filtered):
    return 'personal absolute home path'
  return None


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--tracked', action='store_true', help='CI: inspect tracked files only')
  args = parser.parse_args(argv)
  command = ['git', 'ls-files', '-z', '--cached']
  if not args.tracked:
    command += ['--others', '--exclude-standard']
  try:
    names = set(subprocess.check_output(command, cwd=ROOT).decode().split('\0')) - {''}
    if not names:
      raise ValueError('No source files in publication inventory')
    errors = [(name, error) for name in sorted(names) if (error := check_file(ROOT, name))]
    for name, error in errors:
      print(f'{name}: {error}')
    for required in ('LICENSE', 'THIRD-PARTY-NOTICES.md', 'README.md', '.github/workflows/ci.yml'):
      if required not in names:
        errors.append((required, 'missing required release file'))
        print(f'{required}: missing required release file')
    print(f'Checked {len(names)} source files; findings: {len(errors)}. Pattern scan is not a legal/security certification.')
    return int(bool(errors))
  except (OSError, ValueError, subprocess.CalledProcessError) as exc:
    print(f'error: {exc}', file=sys.stderr)
    return 2


if __name__ == '__main__':
  raise SystemExit(main())
