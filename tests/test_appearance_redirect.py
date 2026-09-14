import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from appearance_tables import NAMESPACE, TABLES, validate
import install_appearance_redirect as installer
from pack_mpq import digest, sha


def dbc(name, text=b'synthetic.blp'):
    fields, offsets = TABLES[name]
    row = [1] + [0]*(fields-1)
    for index in offsets:
        row[index] = 1
    strings = b'\0'+text+b'\0'
    return b'WDBC'+struct.pack('<4I', 1, fields, fields*4, len(strings))+struct.pack('<'+'I'*fields, *row)+strings


class TableTests(unittest.TestCase):
    def test_layouts_and_bounds(self):
        for name in TABLES:
            data = dbc(name)
            self.assertEqual(validate(name, data), data)
            for bad in (b'', b'XXXX'+data[4:], data[:-1], data+b'\0'):
                with self.assertRaises(ValueError):
                    validate(name, bad)
            bad = bytearray(data)
            struct.pack_into('<I', bad, 20+TABLES[name][1][0]*4, 0xffffffff)
            with self.assertRaises(ValueError):
                validate(name, bad)

    def test_unknown_runtime_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root/'Wow.exe').write_bytes(b'unknown')
            with self.assertRaises(ValueError):
                installer.runtime(root)

    def test_retired_discovery_has_no_language_setting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            rows = [{'path': f'{NAMESPACE}/{name}', 'sha256': sha(dbc(name))} for name in TABLES]
            for locale in ('ruRU', 'enUS', 'deDE'):
                directory = root/f'Data/{locale}/patch-{locale}-ModernRaces.MPQ/DBFilesClient'
                directory.mkdir(parents=True)
                for name in TABLES:
                    (directory/name).write_bytes(dbc(name))
            self.assertEqual(len(installer.retired(root, rows)), 6)
            (directory/'CharSections.dbc').write_bytes(dbc('CharSections.dbc', b'changed'))
            with self.assertRaisesRegex(ValueError, 'differs'):
                installer.retired(root, rows)


@unittest.skipUnless(os.environ.get('WXL_MPQ_STORMLIB'), 'optional synthetic StormLib tests')
class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.client, self.work = self.root/'client', self.root/'package'
        self.source = self.client/'Data/ruRU/patch-ruRU-ModernRaces.MPQ/DBFilesClient'
        self.source.mkdir(parents=True)
        (self.client/'Wow.exe').write_bytes(b'untouched')
        (self.client/'WTF').mkdir()
        (self.client/'WTF/Config.wtf').write_bytes(b'synthetic unrelated setting')
        for name in TABLES:
            (self.source/name).write_bytes(dbc(name))
        self.lib = Path(os.environ['WXL_MPQ_STORMLIB']).resolve()
        self.dll = self.root/'synthetic.dll'; self.dll.write_bytes(b'synthetic extension')
        self.report = self.root/'report.json'
        for mock in (patch.object(installer, 'DLL_SHA256', digest(self.dll)),
                     patch.object(installer, 'runtime'), patch.object(installer, 'require_wow_closed')):
            mock.start(); self.addCleanup(mock.stop)
        self.manifest = installer.build(self.source, self.dll, self.work, self.lib)

    def test_roundtrip_removal_idempotence_no_backup(self):
        before = installer.guard(self.client)
        result = installer.install(self.client, self.work, self.lib)
        self.assertEqual(result['state'], 'preview')
        self.assertTrue(self.source.is_dir())
        self.assertFalse((self.client/installer.ARCHIVE).exists())
        result = installer.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertEqual(result['state'], 'installed-verified')
        self.assertFalse(self.source.parent.exists())
        self.assertTrue(self.source.parent.parent.is_dir())
        self.assertEqual(installer.guard(self.client), before)
        self.assertFalse((self.client/'DisabledPatches').exists())
        self.assertEqual(installer.install(self.client, self.work, self.lib)['state'], 'already-installed')
        self.assertEqual(json.loads(self.report.read_text())['tables'], self.manifest['tables'])

    def test_running_game_and_no_backup_required(self):
        with self.assertRaises(ValueError):
            installer.install(self.client, self.work, self.lib, True, False, self.report)
        with patch.object(installer, 'require_wow_closed', side_effect=ValueError('running')):
            with self.assertRaisesRegex(ValueError, 'running'):
                installer.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.report.exists())

    def test_unknown_locale_content_is_preserved(self):
        (self.source/'extra.dbc').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            installer.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertEqual((self.source/'extra.dbc').read_bytes(), b'extra')
        self.assertFalse((self.client/installer.ARCHIVE).exists())

    def test_changed_locale_is_preserved(self):
        (self.source/'CharSections.dbc').write_bytes(dbc('CharSections.dbc', b'changed'))
        with self.assertRaisesRegex(ValueError, 'differs'):
            installer.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertFalse((self.client/installer.ARCHIVE).exists())

    def test_destination_conflict_preserved(self):
        target = self.client/installer.ARCHIVE
        target.write_bytes(b'another patch')
        with self.assertRaises(ValueError):
            installer.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertEqual(target.read_bytes(), b'another patch')

    def test_package_symlink_and_report_inside_client_refused(self):
        with self.assertRaises(ValueError):
            installer.install(self.client, self.work, self.lib, True, True, self.client/'report.json')
        target = self.work/installer.DLL_PATH
        target.unlink(); target.symlink_to(self.dll)
        with self.assertRaises(ValueError):
            installer.install(self.client, self.work, self.lib)

    def test_later_changes_before_removal_are_preserved(self):
        def change_after_install():
            if (self.client/installer.DLL_PATH).exists():
                (self.source/'CharSections.dbc').write_bytes(dbc('CharSections.dbc', b'new'))
        with patch.object(installer, 'require_wow_closed', side_effect=change_after_install):
            with self.assertRaises(ValueError):
                installer.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertTrue(self.source.exists())
        self.assertEqual((self.source/'CharSections.dbc').read_bytes(), dbc('CharSections.dbc', b'new'))


@unittest.skipUnless(os.environ.get('WXL_REDIRECT_DLL'), 'optional actual-DLL emulation')
class EmulationTests(unittest.TestCase):
    def test_x86_abi_and_relocation(self):
        from check_appearance_redirect import check
        data = Path(os.environ['WXL_REDIRECT_DLL']).read_bytes()
        for delta in (0, 0x08000000):
            self.assertEqual(check(data, delta)['cases'], 212)
