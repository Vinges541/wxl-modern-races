import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from wxl_races.appearance import array
from wxl_races.final_details import fix_undead_torso
import undead_torso as package
from pack_mpq import digest, sha, Storm


def skin():
    data = bytearray(64)
    data[:4] = b'SKIN'
    groups = (0, 202, 1302, 1901, 1902, 0)
    # Real buffers are opaque to this fix; every byte must survive unchanged.
    for header, records in ((4, b'\x01\0\x02\0\x03\0'), (12, b'\0\0\x01\0\x02\0')):
        struct.pack_into('<II', data, header, 3, len(data))
        data.extend(records)
    struct.pack_into('<II', data, 28, len(groups), len(data))
    for gid in groups:
        section = bytearray(48)
        struct.pack_into('<H', section, 0, gid)
        struct.pack_into('<H', section, 10, 3)
        data.extend(section)
    for header, stride in ((36, 24), (48, 12)):
        struct.pack_into('<II', data, header, len(groups), len(data))
        for index in range(len(groups)):
            record = bytearray(stride)
            struct.pack_into('<H', record, 4, index)
            data.extend(record)
    return bytes(data)


class TorsoGeometryTests(unittest.TestCase):
    def test_only_two_id_bytes_change(self):
        old = skin()
        new, report = fix_undead_torso(old)
        count, offset = array(old, 28, 48)
        changed = offset+3*48
        self.assertEqual([i for i, (a, b) in enumerate(zip(old, new)) if a != b],
                         [changed, changed+1])
        self.assertEqual(len(old), len(new))
        self.assertEqual(report['offset'], changed)
        self.assertEqual([struct.unpack_from('<H', new, offset+i*48)[0] for i in range(count)],
                         [0, 202, 1302, 0, 1902, 0])
        for header, stride in ((4, 2), (12, 2), (36, 24), (48, 12)):
            n, at = array(old, header, stride)
            self.assertEqual(old[at:at+n*stride], new[at:at+n*stride])

    def test_unknown_profile_and_double_conversion_refused(self):
        original = skin()
        _, offset = array(original, 28, 48)
        for gid in (0, 1900, 1901, 1903):
            changed = bytearray(original)
            struct.pack_into('<H', changed, offset+4*48, gid)
            with self.assertRaises(ValueError):
                fix_undead_torso(bytes(changed))
        with self.assertRaises(ValueError):
            fix_undead_torso(fix_undead_torso(original)[0])

    def test_bad_headers_and_batch_references_refused(self):
        for data in (b'', b'SKIN', b'NOPE'+skin()[4:]):
            with self.assertRaises(ValueError):
                fix_undead_torso(data)
        for header in (28, 36, 48):
            changed = bytearray(skin())
            struct.pack_into('<II', changed, header, 10, len(changed)-1)
            with self.assertRaises(ValueError):
                fix_undead_torso(changed)
        for header, stride in ((36, 24), (48, 12)):
            changed = bytearray(skin())
            _, offset = array(changed, header, stride)
            struct.pack_into('<H', changed, offset+4, 6)
            with self.assertRaises(ValueError):
                fix_undead_torso(changed)


@unittest.skipUnless(os.environ.get('WXL_MPQ_STORMLIB'), 'optional synthetic StormLib tests')
class TorsoPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.client, self.output = self.root/'client', self.root/'package'
        self.library = Path(os.environ['WXL_MPQ_STORMLIB'])
        self.source = self.client/'Data/Patch-ModernRaces-HD.MPQ'
        for name in package.SKINS:
            target = self.source/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(skin())
        (self.client/'WTF').mkdir()
        (self.client/'WTF/Config.wtf').write_bytes(b'SET shadowInstancing "0"\n')
        self.loader = patch.object(package, 'loader', return_value={})
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def build(self):
        return package.build(self.client, self.output, self.library)

    def install(self, **kw):
        return package.install(self.output, self.client, self.library, **kw)

    def test_roundtrip_install_only_adds_archive_and_is_idempotent(self):
        self.build()
        before = {p.relative_to(self.client): p.read_bytes()
                  for p in self.client.rglob('*') if p.is_file()}
        with patch.object(package, 'require_wow_closed') as closed:
            self.assertEqual(self.install()['state'], 'preview')
            closed.assert_not_called()
            report = self.root/'report.json'
            result = self.install(apply=True, no_backup=True, report=report)
            self.assertEqual(result['state'], 'installed-verified')
            closed.assert_called_once()
        self.assertEqual(self.install(apply=True)['state'], 'already-installed')
        after = {p.relative_to(self.client): p.read_bytes()
                 for p in self.client.rglob('*') if p.is_file()}
        self.assertEqual(set(after)-set(before), {Path(package.ARCHIVE)})
        for name in before:
            self.assertEqual(after[name], before[name])
        self.assertFalse((self.client/'DisabledPatches').exists())

    def test_conflicting_locale_and_root_patches_refused(self):
        for relative in ('Data/Patch-Foreign.MPQ', 'Data/ruRU/patch-ruRU-Foreign.MPQ'):
            target = self.client/relative/package.SKINS[0]
            target.parent.mkdir(parents=True)
            target.write_bytes(skin())
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                package.sources(self.client, self.library)
            target.unlink()

    def test_changed_source_and_existing_destination_refused(self):
        self.build()
        source = self.source/package.SKINS[0]
        source.write_bytes(source.read_bytes()+b'extra')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.install()
        source.write_bytes(skin())
        (self.client/package.ARCHIVE).write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError, 'Differing torso patch'):
            self.install()

    def test_apply_guards(self):
        self.build()
        with self.assertRaisesRegex(ValueError, '--no-backup'):
            self.install(apply=True)
        report = self.root/'report.json'
        with patch.object(package, 'require_wow_closed', side_effect=ValueError('running')):
            with self.assertRaisesRegex(ValueError, 'running'):
                self.install(apply=True, no_backup=True, report=report)
        self.assertFalse((self.client/package.ARCHIVE).exists())
        self.assertFalse(report.exists())

    def test_rehashed_non_id_mutation_is_rejected(self):
        manifest = self.build()
        archive = self.output/package.ARCHIVE
        archive.unlink()  # Synthetic test output only.
        storm = Storm(self.library)
        handle = storm.create(archive, max_files=32)
        try:
            for row in manifest['assets']:
                data = bytearray(fix_undead_torso(skin())[0])
                if row['path'] == package.SKINS[0]:
                    data[64] ^= 1
                storm.add(handle, row['path'], bytes(data))
                row['sha256'] = sha(data)
        finally:
            storm.close(handle)
        manifest['files'][0].update(sha256=digest(archive), size=archive.stat().st_size)
        (self.output/'release-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'exact two-byte'):
            self.install()


if __name__ == '__main__':
    unittest.main()
