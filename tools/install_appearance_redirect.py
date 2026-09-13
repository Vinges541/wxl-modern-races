"""Build/install a shared appearance MPQ and extension; remove verified locale copies.

Preview by default. Application needs a closed client, explicit --no-backup and
a new private report. Never changes the EXE, existing HD archives or settings.
"""
import argparse
import json
import os
from pathlib import Path
import re
import struct

from appearance_tables import NAMESPACE, TABLES, validate
from build_appearance_redirect import DLL_PATH, DLL_SHA256
from build_runtime import BASE_OUTPUT_HASHES
from configure_client import require_wow_closed
from mpq_format import LegacyMPQ
from pack_mpq import Storm, digest, inventory, no_links, read_va, save_json, sha

ARCHIVE = 'Data/Patch-ModernRaces-Appearance.MPQ'
KINDS = {ARCHIVE, DLL_PATH}


def runtime(client):
    for name, expected in BASE_OUTPUT_HASHES.items():
        if digest(no_links(client/name)) != expected:
            raise ValueError('Only the verified base runtime is supported')
    data = (client/'Wow.exe').read_bytes()
    if read_va(data, 0x9e2710, 12) != b'patch-*.MPQ\0':
        raise ValueError('Named patch loading is required')


def verify_archive(path, library, rows):
    expected = {row['path']: row for row in rows}
    if set(expected) != {f'{NAMESPACE}/{name}' for name in TABLES} or len(rows) != 2:
        raise ValueError('Exactly two namespaced appearance tables required')
    storm, reader = Storm(library), LegacyMPQ(no_links(path))
    handle = None
    try:
        handle = storm.open(path)
        names = reader.read('(listfile)').decode('ascii').replace('\\', '/').splitlines()
        names = [name for name in names if name != '(listfile)']
        if len(names) != 2 or set(names) != set(expected) or len(reader.blocks) != 3:
            raise ValueError('Unexpected archive members')
        for name, row in expected.items():
            data = reader.read(name)
            validate(name.rsplit('/', 1)[1], data)
            if (len(data) != row['size'] or sha(data) != row['sha256']
                    or storm.read(handle, name.swapcase()) != data):
                raise ValueError('Appearance readback mismatch')
    finally:
        reader.close()
        if handle:
            storm.close(handle)


def build(tables, extension, workspace, library):
    tables, extension, workspace = map(no_links, (tables, extension, workspace))
    if workspace.exists() or tables in workspace.parents:
        raise ValueError('Use a new workspace separate from inputs')
    if digest(extension) != DLL_SHA256:
        raise ValueError('Unverified appearance extension')
    payloads = {name: validate(name, no_links(tables/name).read_bytes()) for name in TABLES}
    rows = [{'path': f'{NAMESPACE}/{name}', 'size': len(data), 'sha256': sha(data)}
            for name, data in payloads.items()]
    workspace.mkdir(parents=True)
    destination = workspace/ARCHIVE
    destination.parent.mkdir()
    storm = Storm(library)
    handle = storm.create(destination, max_files=4)
    try:
        for name, data in payloads.items():
            storm.add(handle, f'{NAMESPACE}/{name}', data)
    finally:
        storm.close(handle)
    verify_archive(destination, library, rows)
    output = workspace/DLL_PATH
    output.parent.mkdir(parents=True)
    with output.open('xb') as stream:
        stream.write(extension.read_bytes())
    manifest = {'schemaVersion': 1, 'kind': 'wxl-modern-races-appearance', 'tables': rows,
                'files': [{'path': name, 'size': (workspace/name).stat().st_size,
                           'sha256': digest(workspace/name)} for name in sorted(KINDS)]}
    save_json(workspace/'manifest.json', manifest)
    return manifest


def package(workspace, library):
    manifest = json.loads(no_links(workspace/'manifest.json').read_text())
    if manifest.get('schemaVersion') != 1 or manifest.get('kind') != 'wxl-modern-races-appearance':
        raise ValueError('Unknown appearance package')
    rows = manifest['files']
    if len(rows) != 2 or {r['path'] for r in rows} != KINDS:
        raise ValueError('Unexpected package files')
    for row in rows:
        path = no_links(workspace/row['path'])
        if path.stat().st_size != row['size'] or digest(path) != row['sha256']:
            raise ValueError('Package changed')
        if row['path'] == DLL_PATH and row['sha256'] != DLL_SHA256:
            raise ValueError('Unsupported extension hash')
    verify_archive(workspace/ARCHIVE, library, manifest['tables'])
    return manifest


def retired(client, rows):
    expected = {r['path'].rsplit('/', 1)[1]: r['sha256'] for r in rows}
    found = []
    for directory in no_links(client/'Data').iterdir():
        if not re.fullmatch('[a-z]{2}[A-Z]{2}', directory.name):
            continue
        no_links(directory)
        if not directory.is_dir():
            continue
        wanted = f'patch-{directory.name}-ModernRaces.MPQ'.casefold()
        matches = [p for p in directory.iterdir() if p.name.casefold() == wanted]
        if len(matches) > 1:
            raise ValueError('Case-colliding locale patches')
        for source in matches:
            entries = inventory(source)
            if {r['path'] for r in entries} != {f'DBFilesClient/{name}' for name in TABLES}:
                raise ValueError('Locale patch contains unknown files; it will not be removed')
            if {p.relative_to(source).as_posix() for p in source.rglob('*')} != {
                    'DBFilesClient', *(f'DBFilesClient/{name}' for name in TABLES)}:
                raise ValueError('Locale patch contains unknown directories')
            for entry in entries:
                if entry['sha256'] != expected[entry['path'].rsplit('/', 1)[1]]:
                    raise ValueError('Locale table differs from the replacement; preserving it')
                found.append({'path': (source/entry['path']).relative_to(client).as_posix(),
                              'sha256': entry['sha256']})
    return sorted(found, key=lambda row: row['path'])


def guard(client):
    # Includes private settings only in an aggregate fingerprint, never in report paths.
    paths = [p for p in client.iterdir() if p.is_file() and p.suffix.lower() in
             ('.exe', '.dll', '.wtf', '.conf', '.command')]
    for folder in ('WTF', 'Extensions'):
        if (client/folder).exists():
            paths += [p for p in (client/folder).rglob('*') if p.is_file()
                      and p.relative_to(client).as_posix() != DLL_PATH]
    return sha(b''.join(p.relative_to(client).as_posix().encode() + b'\0' +
                       bytes.fromhex(digest(p)) for p in sorted(paths)))


def plan(client, workspace, library):
    no_links(client); no_links(workspace)
    if workspace == client or client in workspace.parents:
        raise ValueError('Package must be outside the client')
    runtime(client)
    manifest = package(workspace, library)
    for row in manifest['files']:
        target = no_links(client/row['path'])
        peers = [p for p in target.parent.iterdir() if p.name.casefold() == target.name.casefold()] if target.parent.exists() else []
        if any(p.name != target.name for p in peers):
            raise ValueError('Case-colliding installation target')
        if target.exists() and (not target.is_file() or digest(target) != row['sha256']):
            raise ValueError('Destination differs; refusing to overwrite: ' + row['path'])
    return manifest, retired(client, manifest['tables']), guard(client)


def install(client, workspace, library, apply=False, no_backup=False, report=None):
    manifest, old, before = plan(client, workspace, library)
    new = [r['path'] for r in manifest['files'] if not (client/r['path']).exists()]
    result = dict(manifest, state='preview' if new or old else 'already-installed',
                  installFiles=new, removedFiles=old, backupsCreated=False,
                  gameExecuted=False, protectedSha256=before)
    if not apply or not (new or old):
        return result
    if not no_backup or report is None:
        raise ValueError('Apply requires --no-backup and a new private --report')
    report = no_links(report)
    if report.exists() or not report.parent.is_dir() or client in report.parents or workspace in report.parents:
        raise ValueError('Report must be new and outside client/package')
    require_wow_closed()
    if plan(client, workspace, library) != (manifest, old, before):
        raise ValueError('Client changed after preflight')
    save_json(report, dict(result, state='installing'))
    # Install the shared data before enabling its redirect. Originals remain until
    # both new files have been read back. Exclusive creation never clobbers a file.
    for name in (ARCHIVE, DLL_PATH):
        if name in new:
            target = no_links(client/name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(no_links(workspace/name).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
    for row in manifest['files']:
        if digest(client/row['path']) != row['sha256']:
            raise ValueError('Installed readback mismatch; locale files retained')
    verify_archive(client/ARCHIVE, library, manifest['tables'])
    require_wow_closed()
    if retired(client, manifest['tables']) != old or guard(client) != before:
        raise ValueError('Client changed before locale removal')
    save_json(report, dict(result, state='new-files-verified-locale-retained'))
    # Only the two inventoried, byte-identical tables in each exact patch directory.
    for row in old:
        target = no_links(client/row['path'])
        if digest(target) != row['sha256']:
            raise ValueError('Locale table changed before removal')
        target.unlink()
    for directory in sorted({(client/r['path']).parent for r in old}):
        directory.rmdir()
        directory.parent.rmdir()
    if guard(client) != before:
        raise ValueError('Protected runtime/settings changed')
    result.update(state='installed-verified', protectedUnchanged=True)
    save_json(report, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'install'))
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--stormlib', type=Path, required=True)
    parser.add_argument('--tables', type=Path)
    parser.add_argument('--extension', type=Path)
    parser.add_argument('--client', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--no-backup', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        work = no_links(args.workspace)
        if args.action == 'build':
            if args.tables is None or args.extension is None:
                raise ValueError('Build needs --tables and --extension')
            result = build(args.tables, args.extension, work, args.stormlib)
        else:
            if args.client is None:
                raise ValueError('Install needs --client')
            result = install(args.client.expanduser().resolve(strict=True), work, args.stormlib,
                             args.apply, args.no_backup, args.report)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, struct.error) as exc:
        parser.exit(2, f'error: {exc}\n')


if __name__ == '__main__':
    main()
