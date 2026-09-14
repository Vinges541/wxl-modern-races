"""Build, verify and install the optional locale-independent druid-form package."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

from build_appearance_redirect import build as build_extension
from configure_client import require_wow_closed
from mpq_format import LegacyMPQ
from pack_mpq import Storm, digest, inventory, loader, no_links, save_json, sha, check_names
from plan_druid_forms import original_table
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wxl_races.bundle import audit, stage
from wxl_races.chunks import inspect_asset
from wxl_races.druids import BUILD_CONFIG, DISPLAY_IDS, NAMESPACE, bind_textures, patch_tables, select_sections, validate_geometry
from wxl_races.resolver import ExportIndex

ARCHIVE = 'Data/Patch-ModernRaces-DruidForms.MPQ'
DLL_PATH = 'Extensions/wxl-druid-forms/wxl-druid-forms.dll'
DLL_SHA256 = 'db3e5b2e3bcf6344544b1842ab2f1452de050b1a17c937d920142348a88157c0'
TABLES = ('CreatureDisplayInfo.dbc', 'CreatureModelData.dbc')


def verify_extension(data):
    from check_appearance_redirect import check
    return [check(data, delta, expected_hash=DLL_SHA256, namespace=NAMESPACE+'/DBFilesClient',
                  tables=TABLES, plugin_name='wxl-druid-forms') for delta in (0, 0x08000000)]


def conflicting_overlays(client, library):
    data = no_links(client/'Data')
    if not data.exists():
        return
    directories = [data] + [p for p in data.iterdir() if re.fullmatch('[a-z]{2}[A-Z]{2}',p.name) and p.is_dir()]
    names = {f'DBFilesClient/{n}'.casefold() for n in TABLES}
    names.update(f'{NAMESPACE}/DBFilesClient/{n}'.casefold() for n in TABLES)
    for directory in directories:
        no_links(directory)
        for patch in directory.iterdir():
            lower = patch.name.lower()
            if not lower.startswith('patch') or not lower.endswith('.mpq'):
                continue
            stock = {'patch.mpq','patch-2.mpq','patch-3.mpq'} if directory == data else {
                f'patch-{directory.name.lower()}{suffix}.mpq' for suffix in ('','-2','-3')}
            if lower in stock or (directory == data and lower == Path(ARCHIVE).name.lower()):
                continue
            no_links(patch)
            if patch.is_dir():
                members = {p.relative_to(patch).as_posix().casefold() for p in patch.rglob('*') if p.is_file()}
            else:
                reader = LegacyMPQ(patch)
                try:
                    members = set(reader.read('(listfile)').decode('ascii').replace('\\','/').casefold().splitlines())
                finally:
                    reader.close()
            if members & names:
                raise ValueError('Conflicting creature-table overlay: '+patch.name)


def build(workspace, output, library, sdk):
    workspace, output, sdk = map(no_links, (workspace, output, sdk))
    if output.exists() or output == workspace or output in workspace.parents:
        raise ValueError('Use a fresh output separate from input files')
    if sys.flags.optimize or os.environ.get('PYTHONOPTIMIZE'):
        raise ValueError('Optimized Python is not supported')
    plan = json.loads(no_links(workspace/'druid-plan.json').read_text())
    status = json.loads(no_links(workspace/'druid-export-status.json').read_text())
    if status.get('state') != 'complete' or status.get('build', {}).get('BuildConfig') != BUILD_CONFIG:
        raise ValueError('Complete pinned export required')
    raw = no_links(workspace/'assets/druid_forms/raw')
    index = ExportIndex(raw, sorted(raw.glob('*.files.manifest.json')))
    # Raw exports and the explicit variation pass can contain the same texture
    # twice. Accept only byte-identical copies; never choose between conflicting
    # FileDataIDs by filename or directory order.
    file_ids = {r['fileDataId'] for r in plan['displays']}
    file_ids.update(i for r in plan['displays'] for i in r['textureFileDataIds'] if i)
    for file_id in tuple(file_ids):
        model_path = raw/f'{file_id}.m2'
        if model_path.is_file():
            info = inspect_asset(model_path)
            file_ids.update(info.get('txid', []))
            file_ids.update(info.get('sfid', []))
            file_ids.update(r['fileDataId'] for r in info.get('afid', []))
    for file_id in file_ids - {0}:
        candidates = {p for p in index.by_fdid.get(file_id, [])
                      if p.suffix.lower() in ('.m2', '.skin', '.anim', '.blp', '.skel', '.bone')}
        candidates.update(p for name in index.manifest_fdid_paths.get(file_id, [])
                          if (p := index.resolve_path(name)) is not None)
        if len(candidates) > 1:
            if len({digest(p) for p in candidates}) != 1:
                raise ValueError('Conflicting exported copies of FileDataID '+str(file_id))
        index.by_fdid[file_id] = [sorted(candidates)[0]] if candidates else []
        index.manifest_fdid_paths[file_id] = []
    geosets = json.loads(no_links(workspace/'druid-geosets.json').read_text())
    originals = {name: no_links(workspace/'original-dbc'/name).read_bytes() for name in TABLES}
    tables = patch_tables(originals[TABLES[0]], originals[TABLES[1]], plan)
    extension = build_extension(sdk, druid_forms=True)
    checks = verify_extension(extension)
    output.mkdir(parents=True)
    staged = output/'staged'
    reports = []
    for entry in sorted(plan['displays'], key=lambda r: r['displayId']):
        source = no_links(raw/f"{entry['fileDataId']}.m2")
        info = inspect_asset(source)
        # The verified default forms have inline skeletons and ordinary AFM2
        # animation payloads. A future donor must not silently expand this profile.
        paths = {str(i): f'{NAMESPACE}/Textures/{i}.blp' for i in info.get('txid', []) if i}
        target = {'schemaVersion': 1, 'source': {'modelPath':source.name,
                  'fileDataId':entry['fileDataId'], 'fileDataIdPaths':paths},
                  'target': {'clientBuild':12340, 'legacyPath':entry['modelPath']}}
        check = audit(target,index)
        if not check['readyForCurrentWarcraftXL'] or info.get('skid'):
            raise ValueError('Druid model requires unsupported conversion: '+str(check['errors']))
        # The generic stager also accepts target-provided texture paths. Here all
        # static dependencies must actually exist in our self-contained package.
        for dep in check['dependencies']['textures']:
            if dep.get('required') and not dep['path']:
                raise ValueError('Missing druid texture '+str(dep['fileDataId']))
        result = stage(target, index, staged)
        model_path = staged/entry['modelPath']
        data, bindings = bind_textures(model_path.read_bytes(), entry['textureFileDataIds'])
        model_path.write_bytes(data)
        for file_id in bindings:
            texture = no_links(raw/'textures'/f'{file_id}.blp')
            if texture.read_bytes()[:4] not in (b'BLP1', b'BLP2'):
                raise ValueError('Invalid creature texture')
            dest = staged/NAMESPACE/'Textures'/texture.name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(texture,dest)
        selected = None
        if entry['modelGeosetDataId']:
            selected = {(r['GeosetIndex']+1)*100+r['GeosetValue'] for r in geosets
                        if r['CreatureDisplayInfoID'] == entry['displayId']}
        removed = {}
        for skin in model_path.parent.glob('*.skin'):
            converted, excluded = select_sections(skin.read_bytes(), selected)
            validate_geometry(data, converted)
            skin.write_bytes(converted)
            removed[skin.name] = excluded
        reports.append({'displayId':entry['displayId'], 'sourceModel':entry['fileDataId'],
                        'files':len(result['staged']), 'removedGeosets':removed})
    # The generic staging diagnostic is not a game resource.
    (staged/'bundle-report.json').unlink()
    table_root = staged/NAMESPACE/'DBFilesClient'
    table_root.mkdir(parents=True)
    for name, data in tables.items():
        (table_root/name).write_bytes(data)
    rows = inventory(staged)
    if any(not r['path'].startswith(NAMESPACE+'/') for r in rows):
        raise ValueError('Druid assets escaped their namespace')
    archive = output/ARCHIVE
    archive.parent.mkdir()
    storm = Storm(library)
    handle = storm.create(archive,max_files=1 << (len(rows)+1).bit_length())
    try:
        for row in rows:
            storm.add(handle,row['path'],(staged/row['path']).read_bytes())
    finally:
        storm.close(handle)
    dest = output/DLL_PATH
    dest.parent.mkdir(parents=True)
    dest.write_bytes(extension)
    manifest = {'schemaVersion':1, 'kind':'wxl-druid-forms', 'runtimeVerified':False,
                'plan':plan, 'assets':rows, 'conversion':reports, 'extensionChecks':checks,
                'files':[{'path':n,'size':(output/n).stat().st_size,'sha256':digest(output/n)}
                         for n in (ARCHIVE,DLL_PATH)]}
    save_json(output/'release-manifest.json',manifest)
    verify(output,library,originals)
    return manifest


def verify(package, library, originals=None):
    package = no_links(package)
    manifest = json.loads(no_links(package/'release-manifest.json').read_text())
    if manifest.get('schemaVersion') != 1 or manifest.get('kind') != 'wxl-druid-forms':
        raise ValueError('Unknown druid package')
    files = manifest['files']
    if len(files) != 2 or {r['path'] for r in files} != {ARCHIVE,DLL_PATH}:
        raise ValueError('Unexpected package members')
    for row in files:
        file = no_links(package/row['path'])
        if file.stat().st_size != row['size'] or digest(file) != row['sha256']:
            raise ValueError('Druid package changed')
    if digest(package/DLL_PATH) != DLL_SHA256:
        raise ValueError('Unverified druid extension')
    rows = manifest['assets']
    check_names(rows)
    if any(not r['path'].startswith(NAMESPACE+'/') for r in rows):
        raise ValueError('Unexpected global asset override')
    expected = {r['path'] for r in rows}
    if {n for n in expected if n.endswith('.m2')} != {f'{NAMESPACE}/Models/{i}/Form.m2' for i in DISPLAY_IDS}:
        raise ValueError('Incomplete/unexpected druid models')
    storm, reader = Storm(library), LegacyMPQ(package/ARCHIVE)
    handle = None
    try:
        handle = storm.open(package/ARCHIVE)
        names = reader.read('(listfile)').decode('ascii').replace('\\','/').splitlines()
        names = [n for n in names if n != '(listfile)']
        if len(names) != len(expected) or set(names) != expected or len(reader.blocks) != len(expected)+1:
            raise ValueError('Unexpected archive entries')
        for row in rows:
            data = reader.read(row['path'])
            if len(data) != row['size'] or sha(data) != row['sha256'] or storm.read(handle,row['path'].swapcase()) != data:
                raise ValueError('Native/independent readback mismatch')
        from io import BytesIO
        from PIL import Image
        for name in sorted(expected):
            if name.endswith('.m2'):
                model = reader.read(name)
                for skin in sorted(n for n in expected if n.startswith(name[:-3]) and n.endswith('.skin')):
                    validate_geometry(model, reader.read(skin))
                from wxl_races.chunks import read_chunks, texture_records
                for texture in texture_records(read_chunks(model)[0].payload):
                    if texture['name'] not in expected:
                        raise ValueError('Referenced texture absent from druid package')
            elif name.endswith('.blp'):
                with Image.open(BytesIO(reader.read(name))) as image:
                    image.load()
                    if image.width > 4096 or image.height > 4096:
                        raise ValueError('Texture exceeds the supported resolution budget')
        if originals:
            tables = patch_tables(originals[TABLES[0]],originals[TABLES[1]],manifest['plan'])
            for name,data in tables.items():
                if reader.read(f'{NAMESPACE}/DBFilesClient/{name}') != data:
                    raise ValueError('Druid DBC changes extend beyond selected model references')
    finally:
        reader.close()
        if handle: storm.close(handle)
    return manifest


def install(package, client, library, apply=False, no_backup=False, report=None):
    # Caller resolves only its known top-level client alias. Nested links fail.
    client, package = no_links(client), no_links(package)
    loader(client)
    conflicting_overlays(client, library)
    originals = {name:original_table(client,library,name) for name in TABLES}
    manifest = verify(package,library,originals)
    changes = []
    if [r['path'] for r in manifest['files']] != [ARCHIVE, DLL_PATH]:
        raise ValueError('The archive must be installed before the redirect DLL')
    for row in manifest['files']:
        target = no_links(client/row['path'])
        if target.exists():
            if not target.is_file() or digest(target) != row['sha256']:
                raise ValueError('Refusing to overwrite an unknown or older druid package')
        else:
            changes.append(row)
    if not apply:
        return {'apply':False,'newFiles':[r['path'] for r in changes]}
    if not no_backup or report is None:
        raise ValueError('Use explicit --no-backup and a new private --report')
    report = no_links(report)
    if report.exists() or not report.parent.is_dir() or report == client or client in report.parents:
        raise ValueError('Report must be new and outside the client')
    require_wow_closed()
    if any((client/r['path']).exists() for r in changes):
        raise ValueError('Druid destination appeared after preflight')
    preserved = {}
    for folder in (client,client/'WTF',client/'Extensions'):
        paths = folder.iterdir() if folder == client else folder.rglob('*')
        for path in paths:
            if path.is_file(): preserved[path] = digest(path)
    # MPQ precedes the DLL: interrupted installation cannot redirect to absent data.
    for row in changes:
        source, target = no_links(package/row['path']), no_links(client/row['path'])
        if digest(source) != row['sha256']:
            raise ValueError('Source changed during installation')
        target.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as inp, target.open('xb') as out:
            shutil.copyfileobj(inp,out)
            out.flush(); os.fsync(out.fileno())
        if digest(target) != row['sha256']:
            raise ValueError('Installed file readback mismatch')
    if any(digest(path) != checksum for path,checksum in preserved.items()):
        raise ValueError('Existing client configuration/runtime changed during installation')
    result = {'installed':manifest['files'],'newFiles':[r['path'] for r in changes],
              'runtimeVerified':False,'backupsCreated':False}
    save_json(report,result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode',required=True)
    b = sub.add_parser('build')
    b.add_argument('--workspace',type=Path,required=True)
    b.add_argument('--output',type=Path,required=True)
    b.add_argument('--sdk',type=Path,required=True)
    v = sub.add_parser('verify')
    v.add_argument('--package',type=Path,required=True)
    i = sub.add_parser('install')
    i.add_argument('--package',type=Path,required=True)
    i.add_argument('--client',type=Path,required=True)
    i.add_argument('--apply',action='store_true')
    i.add_argument('--no-backup',action='store_true')
    i.add_argument('--report',type=Path)
    for cmd in (b,v,i): cmd.add_argument('--stormlib',type=Path,required=True)
    a = p.parse_args()
    if a.mode == 'build':
        result = build(a.workspace,a.output,a.stormlib,a.sdk)
        print(json.dumps({'assets':len(result['assets']),'files':result['files']},indent=2))
    elif a.mode == 'verify':
        result = verify(a.package,a.stormlib)
        print(f"Verified {len(result['assets'])} assets through two independent readers")
    else:
        print(json.dumps(install(a.package,a.client.resolve(),a.stormlib,a.apply,a.no_backup,a.report),indent=2))


if __name__ == '__main__': main()
