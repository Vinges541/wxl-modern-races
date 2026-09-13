"""Upgrade only the verified client's GLUE preview calls. Preview by default."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys

from build_runtime import BASE_OUTPUT_HASHES
from configure_client import atomic_write, require_wow_closed
from pack_mpq import no_links, save_json
from patch_glue_preview import EXPECTED, RESULT, SCALES, SITES, patch
from patch_wow import PatchError


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def plan(client):
    client = no_links(client)
    if not no_links(client / 'Data').is_dir():
        raise ValueError('Expected the existing Windows client')
    for name, expected in BASE_OUTPUT_HASHES.items():
        if name != 'Wow.exe' and fingerprint(no_links(client / name).read_bytes()) != expected:
            raise ValueError('Runtime dependency differs from the supported profile')
    target = no_links(client / 'Wow.exe')
    source = target.read_bytes()
    before = fingerprint(source)
    if before == RESULT:
        return source, source
    if before != EXPECTED:
        raise PatchError('Unknown client; no executable will be overwritten')
    return source, patch(source)


def install(client, apply=False, no_backup=False, report=None):
    source, output = plan(client)
    changed = source != output
    result = {'schemaVersion': 1, 'kind': 'tauren-glue-preview',
              'state': 'preview' if changed else 'already-installed',
              'changedFile': 'Wow.exe' if changed else None,
              'beforeSha256': fingerprint(source), 'afterSha256': fingerprint(output),
              'callSites': {k: hex(v) for k, v in SITES.items()}, 'previewScales': SCALES,
              'worldScaleChanged': False, 'assetsChanged': False,
              'backupsCreated': False, 'gameplayVerified': False}
    if not apply or not changed:
        return result
    if not no_backup or report is None:
        raise ValueError('Apply requires explicit --no-backup and a new private --report')
    report = no_links(report)
    if report.exists() or client in report.parents or not report.parent.is_dir():
        raise ValueError('Report must be new, outside the client, in an existing directory')
    require_wow_closed()
    # Revalidate all signatures after the process check, before the single write.
    if plan(client) != (source, output):
        raise ValueError('Client changed after preflight')
    target = no_links(client / 'Wow.exe')
    atomic_write(target, output, stat.S_IMODE(target.stat().st_mode))
    if fingerprint(target.read_bytes()) != RESULT:
        raise ValueError('Executable readback failed')
    result['state'] = 'installed-verified'
    save_json(report, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--no-backup', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    try:
        client = args.client.expanduser().resolve(strict=True)
        print(json.dumps(install(client, args.apply, args.no_backup, args.report), indent=2))
        return 0
    except (OSError, ValueError, PatchError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
