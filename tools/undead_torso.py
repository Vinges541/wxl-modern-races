"""Prepare a narrow Undead back-visibility overlay from installed HD skins.

Only the 1901 geoset IDs change. Install through install_release.py; existing
archives, models, textures, runtime and settings are never replaced.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from configure_client import require_wow_closed
from mpq_format import LegacyMPQ
from pack_mpq import Storm, digest, loader, no_links, protected, save_json, sha

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wxl_races.final_details import fix_undead_torso

ARCHIVE = 'Data/Patch-ModernRaces-UndeadTorso.MPQ'
KIND = 'wxl-modern-races-undead-torso'
SKINS = tuple(f'Character/Scourge/{sex}/Scourge{sex}{suffix}.skin'
              for sex in ('Female', 'Male')
              for suffix in ('00', *(f'_lod{i:02}' for i in range(1, 7))))
CANONICAL = {p.casefold(): p for p in SKINS}


def sources(client, library):
    """Reject ambiguous or foreign character overlays, including locale patches."""
    client = no_links(client)
    storm, found = Storm(library), {}
    folders = [client/'Data'] + [p for p in (client/'Data').iterdir()
                                if re.fullmatch('[a-z]{2}[A-Z]{2}', p.name) and p.is_dir()]
    for folder in folders:
        no_links(folder)
        for path in sorted(folder.iterdir()):
            if not (path.name.lower().startswith('patch-') and path.suffix.lower() == '.mpq'):
                continue
            no_links(path)
            if path.relative_to(client).as_posix() == ARCHIVE:
                continue
            if re.fullmatch(r'patch-(?:[a-z]{4}(?:-\d+)?|\d+)\.mpq', path.name.lower()):
                continue  # Original numbered patch archives are not HD inputs.
            own = folder == client/'Data' and bool(re.fullmatch(
                r'patch-modernraces-hd(?:-\d{3})?\.mpq', path.name.lower()))
            handle = None
            try:
                if path.is_dir():
                    members = {}
                    for p in path.rglob('*'):
                        no_links(p)
                        if p.is_file():
                            key = p.relative_to(path).as_posix().casefold()
                            if key in members:
                                raise ValueError('Case-colliding loose assets')
                            members[key] = p
                else:
                    handle = storm.open(path)
                    names = storm.read(handle, '(listfile)').decode('utf-8-sig').replace('\\', '/').splitlines()
                    members = {}
                    for name in names:
                        key = name.casefold()
                        if key in CANONICAL and key in members:
                            raise ValueError('Duplicate Scourge skin in listfile')
                        members[key] = name
                for key in CANONICAL.keys() & members.keys():
                    if not own or key in found:
                        raise ValueError('Conflicting Scourge overlay: ' + path.name)
                    data = members[key].read_bytes() if handle is None else storm.read(handle, members[key])
                    found[key] = data
            finally:
                if handle:
                    storm.close(handle)
    if set(found) != set(CANONICAL):
        raise ValueError('Expected all 14 installed modern Scourge skin profiles')
    return {CANONICAL[k]: data for k, data in found.items()}


def verify(package, library, original):
    package = no_links(package)
    manifest = json.loads(no_links(package/'release-manifest.json').read_text())
    if manifest.get('schemaVersion') != 1 or manifest.get('kind') != KIND:
        raise ValueError('Unknown Undead torso package')
    assets, files = manifest['assets'], manifest['files']
    if (len(assets) != 14 or {r['path'] for r in assets} != set(SKINS)
            or len(files) != 1 or files[0]['path'] != ARCHIVE):
        raise ValueError('Only the 14 Scourge skins are allowed')
    archive = no_links(package/ARCHIVE)
    if archive.stat().st_size != files[0]['size'] or digest(archive) != files[0]['sha256']:
        raise ValueError('Torso archive changed')
    storm, reader, handle = Storm(library), LegacyMPQ(archive), None
    try:
        handle = storm.open(archive)
        names = reader.read('(listfile)').decode('ascii').replace('\\', '/').splitlines()
        names = [n for n in names if n != '(listfile)']
        if len(names) != 14 or set(names) != set(SKINS) or len(reader.blocks) != 15:
            raise ValueError('Unexpected torso archive contents')
        for row in assets:
            name = row['path']
            before = original[name]
            if sha(before) != row['beforeSha256']:
                raise ValueError('Installed source changed: ' + name)
            expected, _ = fix_undead_torso(before)
            data = reader.read(name)
            if (data != expected or storm.read(handle, name.swapcase()) != data
                    or sha(data) != row['sha256'] or len(data) != row['size']):
                raise ValueError('Torso patch is not the exact two-byte repair: ' + name)
    finally:
        reader.close()
        if handle:
            storm.close(handle)
    return manifest


def build(client, output, library):
    client, output = map(no_links, (client, output))
    if output.exists() or client == output or client in output.parents:
        raise ValueError('Use a fresh output directory outside the client')
    loader(client)
    original = sources(client, library)
    payloads = {name: fix_undead_torso(data)[0] for name, data in original.items()}
    output.mkdir(parents=True)
    archive = output/ARCHIVE
    archive.parent.mkdir()
    storm = Storm(library)
    handle = storm.create(archive, max_files=32)
    try:
        for name, data in sorted(payloads.items()):
            storm.add(handle, name, data)
    finally:
        storm.close(handle)
    manifest = {'schemaVersion': 1, 'kind': KIND, 'runtimeVerified': False,
                'assets': [{'path': name, 'beforeSha256': sha(original[name]),
                            'sha256': sha(data), 'size': len(data)}
                           for name, data in sorted(payloads.items())],
                'files': [{'path': ARCHIVE, 'size': archive.stat().st_size,
                           'sha256': digest(archive)}]}
    save_json(output/'release-manifest.json', manifest)
    return verify(output, library, original)


def install(package, client, library, apply=False, no_backup=False, report=None):
    client, package = map(no_links, (client, package))
    if client == package or client in package.parents:
        raise ValueError('Package must be outside the client')
    loader(client)
    original = sources(client, library)
    manifest = verify(package, library, original)
    target = no_links(client/ARCHIVE)
    if any(p.name.casefold() == target.name.casefold() and p.name != target.name
           for p in target.parent.iterdir()):
        raise ValueError('Case-colliding installation target')
    checksum = manifest['files'][0]['sha256']
    if target.exists() and (not target.is_file() or digest(target) != checksum):
        raise ValueError('Differing torso patch already exists; it will not be overwritten')
    result = {'state': 'already-installed' if target.exists() else 'preview',
              'files': manifest['files'], 'skinProfiles': 14, 'changedBytesPerProfile': 2,
              'runtimeVerified': False, 'backupsCreated': False}
    if not apply or target.exists():
        return result
    if not no_backup or report is None:
        raise ValueError('Apply requires --no-backup and a new private --report')
    report = no_links(report)
    if report.exists() or not report.parent.is_dir() or client in report.parents or package in report.parents:
        raise ValueError('Report must be new and outside the client/package')
    require_wow_closed()
    before = protected(client)
    if sources(client, library) != original:
        raise ValueError('Client assets changed during preflight')
    payload = no_links(package/ARCHIVE).read_bytes()
    if sha(payload) != checksum:
        raise ValueError('Package changed during preflight')
    save_json(report, dict(result, state='installing'))
    with target.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if digest(target) != checksum or protected(client) != before:
        raise ValueError('Installed readback or protected settings mismatch')
    result.update(state='installed-verified', protectedUnchanged=True)
    save_json(report, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stormlib', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.client.expanduser().resolve(), args.output.expanduser(), args.stormlib)
    print(json.dumps({'assets': len(result['assets']), 'files': result['files']}, indent=2))


if __name__ == '__main__':
    main()
