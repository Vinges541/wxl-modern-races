"""Losslessly pack the installed modern-races directory; never launch the game.

Build in a fresh private workspace, verify with StormLib and a separate decoder,
then explicitly apply with --discard-loose. No rollback copy is created. Helpers
for the narrow StormLib profile are adapted from wxl-equipment-textures (GPL-3.0+).
"""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time

from configure_client import require_wow_closed
from mpq_format import LegacyMPQ, hash_name, LIMIT

PATCH = 'Patch-ModernRaces-HD.MPQ'
MAX_FILES = 60000
MAX_RESOURCE = 64 * 1024**2
TABLE_RESERVE = 16 * 1024**2
PROFILE = {'headerVersion': 1, 'headerBytes': 44, 'sectorBytes': 4096,
           'compression': 'zlib', 'locale': 0, 'fileTimes': 0,
           'maxArchiveBytes': LIMIT - 1, 'maxFiles': MAX_FILES,
           'extendedOffsets': False, 'lossless': True}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def no_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f'Symlink inside physical input/output path: {part.name}')
    return path


def digest(path):
    result = hashlib.sha256()
    with no_links(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            result.update(chunk)
    return result.hexdigest()


def save_json(path, value):
    # Reports are private: source/configuration fingerprints are not public assets.
    path = no_links(path)
    data = (json.dumps(value, indent=2) + '\n').encode()
    with path.open('wb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    path.chmod(0o600)


def asset_name(name):
    if (not isinstance(name, str) or not name or len(name) >= 260
            or any(ord(ch) < 32 or ord(ch) > 126 or ch in '\\:*?"<>|' for ch in name)
            or any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in name.split('/'))):
        raise ValueError('Unsafe or non-ASCII MPQ path')
    if name.lower() in ('(listfile)', '(attributes)', '(signature)'):
        raise ValueError('Reserved MPQ metadata name')
    return name


def check_names(rows):
    names = set()
    hashes = {(hash_name('(listfile)', 1), hash_name('(listfile)', 2))}
    for row in rows:
        name = asset_name(row['path'])
        pair = (hash_name(name, 1), hash_name(name, 2))
        if name.upper() in names or pair in hashes:
            raise ValueError('Case-insensitive or MPQ name-hash collision')
        names.add(name.upper()); hashes.add(pair)
        if not isinstance(row['size'], int) or not 0 < row['size'] <= MAX_RESOURCE:
            raise ValueError('Resource outside supported size range')
        if not re.fullmatch('[0-9a-f]{64}', row['sha256']):
            raise ValueError('Invalid resource digest')
    if not rows:
        raise ValueError('Empty source')


def inventory(root, progress=False):
    root = no_links(root)
    if not root.is_dir():
        raise ValueError('Expected a loose patch directory')
    rows = []
    for path in sorted(root.rglob('*')):
        no_links(path)
        mode = path.stat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('Non-regular filesystem entry')
        name = asset_name(path.relative_to(root).as_posix())
        rows.append({'path': name, 'size': path.stat().st_size, 'sha256': digest(path)})
        if progress and len(rows) % 5000 == 0:
            print(f'Inventory: {len(rows)} files', flush=True)
    check_names(rows)
    return rows


def read_va(data, va, size):
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[:2] != b'MZ' or data[pe:pe+4] != b'PE\0\0':
        raise ValueError('Expected a PE client')
    if struct.unpack_from('<H', data, pe+4)[0] != 0x14c:
        raise ValueError('Expected x86 client')
    opt = pe+24
    if struct.unpack_from('<H', data, opt)[0] != 0x10b:
        raise ValueError('Expected PE32')
    base = struct.unpack_from('<I', data, opt+28)[0]
    table = opt + struct.unpack_from('<H', data, pe+20)[0]
    for i in range(struct.unpack_from('<H', data, pe+6)[0]):
        _, rva, raw_size, raw = struct.unpack_from('<4I', data, table+i*40+8)
        if rva <= va-base and va-base+size <= rva+raw_size:
            offset = raw + va-base-rva
            return data[offset:offset+size]
    raise ValueError('Client VA not mapped')


def loader(client):
    lock = json.loads((Path(__file__).resolve().parents[1]/'dependencies.lock.json').read_text())
    expected = lock['verifiedOutputSha256']
    actual = {name: digest(no_links(client/name)) for name in expected}
    if actual != expected:
        raise ValueError('Only the exact verified build-12340 runtime is supported')
    data = (client/'Wow.exe').read_bytes()
    for va, value in [(0x9e2700, b'patch-%s-*.MPQ\0'), (0x9e2710, b'patch-*.MPQ\0')]:
        if read_va(data, va, len(value)) != value:
            raise ValueError('Named-patch wildcard edit not present')
    return {'hashes': actual, 'namedPatchScan': True, 'gameExecuted': False}


def protected(client):
    paths = [p for p in client.iterdir() if p.is_file() and p.suffix.lower() in ('.exe', '.dll', '.wtf', '.conf', '.command')]
    for folder in ('WTF', 'Extensions'):
        if (client/folder).exists():
            paths += [p for p in (client/folder).rglob('*') if p.is_file()]
    result = hashlib.sha256()
    for path in sorted(paths):
        # Do not serialize private WTF file names or their contents in reports.
        result.update(path.relative_to(client).as_posix().encode()+b'\0'+bytes.fromhex(digest(path)))
    return {'files': len(paths), 'sha256': result.hexdigest()}


class CreateInfo(c.Structure):
    _fields_ = [('cbSize', c.c_uint32), ('version', c.c_uint32), ('user', c.c_void_p)] + [
        (name, c.c_uint32) for name in ('userBytes', 'streamFlags', 'listFlags', 'attrFlags',
                                      'sigFlags', 'attributes', 'sector', 'rawChunk', 'maxFiles')]


class Storm:
    def __init__(self, library):
        self.lib = lib = c.CDLL(str(no_links(library)))
        signatures = {
            'SFileCreateArchive2': [c.c_char_p, c.POINTER(CreateInfo), c.POINTER(c.c_void_p)],
            'SFileCreateFile': [c.c_void_p, c.c_char_p, c.c_uint64, c.c_uint32, c.c_uint32, c.c_uint32, c.POINTER(c.c_void_p)],
            'SFileWriteFile': [c.c_void_p, c.c_void_p, c.c_uint32, c.c_uint32],
            'SFileFinishFile': [c.c_void_p], 'SFileCloseArchive': [c.c_void_p],
            'SFileOpenArchive': [c.c_char_p, c.c_uint32, c.c_uint32, c.POINTER(c.c_void_p)],
            'SFileOpenFileEx': [c.c_void_p, c.c_char_p, c.c_uint32, c.POINTER(c.c_void_p)],
            'SFileReadFile': [c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32), c.c_void_p],
            'SFileCloseFile': [c.c_void_p],
        }
        for name, args in signatures.items():
            getattr(lib, name).argtypes = args
            getattr(lib, name).restype = c.c_bool
        lib.SFileGetFileSize.argtypes = [c.c_void_p, c.POINTER(c.c_uint32)]
        lib.SFileGetFileSize.restype = c.c_uint32

    def create(self, path, max_files=MAX_FILES):
        if no_links(path).exists():
            raise FileExistsError(path)
        info = CreateInfo()
        info.cbSize = c.sizeof(info); info.version = 1
        info.listFlags = 0x200; info.sector = 4096; info.maxFiles = max_files
        handle = c.c_void_p()
        if not self.lib.SFileCreateArchive2(os.fsencode(path), c.byref(info), c.byref(handle)):
            raise OSError('SFileCreateArchive2 failed')
        return handle

    def add(self, handle, name, data):
        member = c.c_void_p()
        if not self.lib.SFileCreateFile(handle, name.replace('/', '\\').encode('ascii'), 0, len(data), 0, 0x200, c.byref(member)):
            raise OSError('SFileCreateFile failed: '+name)
        try:
            success = self.lib.SFileWriteFile(member, data, len(data), 2)
        finally:
            finished = self.lib.SFileFinishFile(member)
        if not success or not finished:
            raise OSError('SFileWriteFile/FinishFile failed: '+name)

    def close(self, handle):
        if not self.lib.SFileCloseArchive(handle):
            raise OSError('SFileCloseArchive failed')

    def open(self, path):
        handle = c.c_void_p()
        if not self.lib.SFileOpenArchive(os.fsencode(no_links(path)), 0, 0x100, c.byref(handle)):
            raise OSError('SFileOpenArchive failed')
        return handle

    def read(self, handle, name):
        member, high = c.c_void_p(), c.c_uint32()
        if not self.lib.SFileOpenFileEx(handle, name.replace('/', '\\').encode('ascii'), 0, c.byref(member)):
            raise OSError('SFileOpenFileEx failed: '+name)
        try:
            size = self.lib.SFileGetFileSize(member, c.byref(high))
            if high.value or not 0 < size <= MAX_RESOURCE:
                raise ValueError('Unexpected MPQ resource size')
            buffer, read = c.create_string_buffer(size), c.c_uint32()
            if not self.lib.SFileReadFile(member, buffer, size, c.byref(read), None) or read.value != size:
                raise OSError('Incomplete MPQ read')
            return buffer.raw
        finally:
            self.lib.SFileCloseFile(member)


def archive_name(index):
    if not 0 <= index < 999:
        raise ValueError('Too many parts')
    return f'Patch-ModernRaces-HD-{index+1:03d}.MPQ'


def validate_manifest(manifest):
    if manifest.get('schemaVersion') != 1 or manifest.get('profile') != PROFILE:
        raise ValueError('Unsupported MPQ packing manifest')
    rows = []
    for i, entry in enumerate(manifest['archives']):
        if entry['name'] != archive_name(i) or not 0 < entry['size'] < LIMIT:
            raise ValueError('Invalid archive name/size')
        if not re.fullmatch('[0-9a-f]{64}', entry['sha256']) or not 0 < len(entry['files']) <= MAX_FILES:
            raise ValueError('Invalid archive hash/count')
        rows += entry['files']
    check_names(rows)
    if sum(r['size'] for r in rows) != manifest['sourceBytes']:
        raise ValueError('Incorrect total size')
    return sorted(rows, key=lambda r: r['path'])


def verify(archive_root, library, manifest, progress=False):
    rows = validate_manifest(manifest)
    storm, total, headers = Storm(library), 0, []
    for entry in manifest['archives']:
        path = no_links(archive_root/entry['name'])
        if path.stat().st_size != entry['size'] or digest(path) != entry['sha256']:
            raise ValueError('MPQ changed: '+path.name)
        independent, handle = LegacyMPQ(path), None
        try:
            handle = storm.open(path)
            listed = independent.read('(listfile)').decode('ascii').splitlines()
            names = [name.replace('\\', '/') for name in listed if name != '(listfile)']
            if len(names) != len(set(names)) or set(names) != {r['path'] for r in entry['files']}:
                raise ValueError('Listfile coverage/case mismatch')
            if len(independent.blocks) != len(names)+1:
                raise ValueError('Unexpected extra or missing MPQ blocks')
            for row in entry['files']:
                raw = independent.read(row['path'])
                native = storm.read(handle, row['path'].swapcase())
                if len(raw) != row['size'] or sha(raw) != row['sha256'] or native != raw:
                    raise ValueError('Readback mismatch: '+row['path'])
                total += 1
                if progress and total % 5000 == 0:
                    print(f'Readback: {total}/{len(rows)} files (two readers)', flush=True)
            headers.append(independent.header)
        finally:
            independent.close()
            if handle:
                storm.close(handle)
    return {'files': total, 'readers': ['StormLib', 'independent-MPQ-v2-zlib'],
            'caseInsensitiveLookup': True, 'exactListfilePaths': True, 'headers': headers}


def check_destinations(client, names):
    # Refuse a priority change across ANY other currently installed patch.
    data = no_links(client/'Data')
    peers = [p.name.lower() for p in data.iterdir() if p.name.lower().startswith('patch')]
    for name in names:
        if name.lower() in peers:
            raise FileExistsError('Archive destination already occupied: '+name)
        for peer in peers:
            if peer == PATCH.lower():
                continue
            if (name.lower() < peer) != (PATCH.lower() < peer):
                raise ValueError('Another patch interleaves the selected shard names')


def build(client, workspace, library, max_bytes=LIMIT-1):
    no_links(client); no_links(workspace)
    source = no_links(client/'Data'/PATCH)
    if workspace.exists() or workspace == client or client in workspace.parents:
        raise ValueError('Use a fresh private workspace outside the client')
    if workspace in source.parents or source in workspace.parents:
        raise ValueError('Output overlaps source')
    if not TABLE_RESERVE+MAX_RESOURCE < max_bytes < LIMIT:
        raise ValueError('Invalid archive size cap')
    scan, guard = loader(client), protected(client)
    rows = inventory(source, True)
    check_destinations(client, [archive_name(0)])
    workspace.mkdir(parents=True)
    manifest = {'schemaVersion': 1, 'kind': 'wxl-modern-races-mpq', 'profile': PROFILE,
                'sourceBytes': sum(r['size'] for r in rows),
                'sourceAllocatedBytes': sum((source/r['path']).stat().st_blocks*512 for r in rows),
                'loader': scan, 'protected': guard, 'archives': []}
    storm, handle, count = Storm(library), None, 0
    try:
        for row in rows:
            bound = row['size'] + ((row['size']+4095)//4096+1)*4
            if handle is None or path.stat().st_size+bound+TABLE_RESERVE >= max_bytes or len(entry['files']) >= MAX_FILES:
                if handle is not None:
                    old, handle = handle, None
                    storm.close(old)
                    entry.update(size=path.stat().st_size, sha256=digest(path))
                    print(f'Closed {path.name}: {entry["size"]} bytes', flush=True)
                path = workspace/archive_name(len(manifest['archives']))
                entry = {'name': path.name, 'files': []}
                manifest['archives'].append(entry)
                handle = storm.create(path)
            payload = no_links(source/row['path']).read_bytes()
            if len(payload) != row['size'] or sha(payload) != row['sha256']:
                raise ValueError('Source changed during packing')
            storm.add(handle, row['path'], payload)
            entry['files'].append(row)
            count += 1
            if count % 1000 == 0:
                print(f'Packed {count}/{len(rows)} files, {path.name}: {path.stat().st_size} bytes', flush=True)
        old, handle = handle, None
        storm.close(old)
        entry.update(size=path.stat().st_size, sha256=digest(path))
        print(f'Closed {path.name}: {entry["size"]} bytes', flush=True)
    finally:
        if handle is not None:
            storm.close(handle)
    check_destinations(client, [a['name'] for a in manifest['archives']])
    manifest['verification'] = verify(workspace, library, manifest, True)
    if inventory(source, True) != rows or protected(client) != guard or loader(client) != scan:
        raise ValueError('Client changed during packing')
    manifest['state'] = 'verified'
    save_json(workspace/'manifest.json', manifest)
    return summary(manifest, 'verified')


def summary(manifest, state):
    before, after = manifest['sourceBytes'], sum(a['size'] for a in manifest['archives'])
    return {'schemaVersion': 1, 'patch': 'modern-races', 'state': state,
            'beforeBytes': before, 'afterBytes': after, 'savedBytes': before-after,
            'savedPercent': round(100*(before-after)/before, 4),
            'files': sum(len(a['files']) for a in manifest['archives']),
            'archives': [{k: v for k, v in a.items() if k != 'files'} for a in manifest['archives']],
            'profile': PROFILE, 'backupsCreated': False, 'gameplayVerified': False}


def install(client, workspace, library, apply=False, discard_loose=False, report=None):
    no_links(client); no_links(workspace)
    manifest = json.loads(no_links(workspace/'manifest.json').read_text())
    rows = validate_manifest(manifest)
    source = no_links(client/'Data'/PATCH)
    if manifest.get('state') != 'verified' or loader(client) != manifest['loader'] or protected(client) != manifest['protected']:
        raise ValueError('Verified build with unchanged runtime/settings required')
    if inventory(source, True) != rows:
        raise ValueError('Loose source changed')
    names = [a['name'] for a in manifest['archives']]
    check_destinations(client, names)
    if source.stat().st_dev != workspace.stat().st_dev:
        raise ValueError('Installation requires the same filesystem')
    result = summary(manifest, 'preview')
    if not apply:
        return result
    if not discard_loose or report is None:
        raise ValueError('Destructive apply requires --discard-loose and --report')
    report = no_links(report)
    inventory_report = report.with_name(report.stem+'.manifest.json')
    if report.exists() or inventory_report.exists() or client in report.parents or workspace in report.parents:
        raise ValueError('Report must be new and outside client/build workspace')
    if not report.parent.is_dir():
        raise ValueError('Create the private report directory first')
    require_wow_closed()
    verify(workspace, library, manifest, True)
    if inventory(source, True) != rows or protected(client) != manifest['protected']:
        raise ValueError('Client changed before installation')
    check_destinations(client, names)
    require_wow_closed()
    # All parts are exclusive hardlinks. Until all are verified in place, the
    # original remains mounted; duplicate resources are byte-identical.
    for entry in manifest['archives']:
        path = no_links(workspace/entry['name'])
        os.link(path, no_links(client/'Data'/entry['name']))
    save_json(report, summary(manifest, 'archives-linked-loose-retained'))
    result['verification'] = verify(client/'Data', library, manifest, True)
    if inventory(source, True) != rows or protected(client) != manifest['protected']:
        raise ValueError('Client changed before loose removal')
    require_wow_closed()
    save_json(inventory_report, manifest)
    # Exact owned directory; never a client/workspace root or a symlink.
    if source.name != PATCH or source.parent != client/'Data' or not source.is_dir():
        raise ValueError('Unexpected deletion target')
    shutil.rmtree(no_links(source))
    for entry in manifest['archives']:
        no_links(workspace/entry['name']).unlink()
    (workspace/'manifest.json').unlink()
    workspace.rmdir()
    if protected(client) != manifest['protected'] or loader(client) != manifest['loader']:
        raise ValueError('Protected runtime/configuration changed')
    result.update(state='installed-verified', completedAt=time.time(),
                  beforeAllocatedBytes=manifest['sourceAllocatedBytes'],
                  afterAllocatedBytes=sum((client/'Data'/name).stat().st_blocks*512 for name in names),
                  protectedUnchanged=True, looseRemoved=True, temporaryBuildRemoved=True,
                  manifest=inventory_report.name)
    save_json(report, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'verify', 'install'])
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--manifest', type=Path, help='verify already installed archives')
    parser.add_argument('--stormlib', type=Path, required=True)
    parser.add_argument('--max-archive-bytes', type=int, default=LIMIT-1)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--discard-loose', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    try:
        # Only the top-level client alias may resolve through an app symlink.
        client = args.client.expanduser().resolve(strict=True)
        workspace = args.workspace.expanduser().absolute() if args.workspace else None
        if args.action == 'verify' and args.manifest:
            manifest = json.loads(no_links(args.manifest).read_text())
            result = verify(client/'Data', args.stormlib, manifest, True)
        elif workspace is None:
            raise ValueError('--workspace is required')
        elif args.action == 'build':
            result = build(client, workspace, args.stormlib, args.max_archive_bytes)
        elif args.action == 'verify':
            result = verify(workspace, args.stormlib, json.loads((workspace/'manifest.json').read_text()), True)
        else:
            result = install(client, workspace, args.stormlib, args.apply, args.discard_loose, args.report)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, struct.error) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
