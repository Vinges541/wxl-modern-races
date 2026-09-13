import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import install_glue_preview as installer
from patch_wow import PatchError


class PreviewInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.client = self.root / 'client'
        (self.client / 'Data').mkdir(parents=True)
        self.exe = self.client / 'Wow.exe'
        self.exe.write_bytes(b'original')
        self.report = self.root / 'report.json'
        for name, value in [('EXPECTED', hashlib.sha256(b'original').hexdigest()),
                            ('RESULT', hashlib.sha256(b'patched').hexdigest()),
                            ('BASE_OUTPUT_HASHES', {})]:
            mocked = patch.object(installer, name, value)
            mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch.object(installer, 'patch', return_value=b'patched')
        mocked.start(); self.addCleanup(mocked.stop)

    def test_preview_apply_no_backup_and_idempotence(self):
        self.assertEqual(installer.install(self.client)['state'], 'preview')
        self.assertEqual(self.exe.read_bytes(), b'original')
        with patch.object(installer, 'require_wow_closed') as check:
            result = installer.install(self.client, True, True, self.report)
        check.assert_called_once()
        self.assertEqual(result['state'], 'installed-verified')
        self.assertEqual(self.exe.read_bytes(), b'patched')
        self.assertEqual(json.loads(self.report.read_text()), result)
        self.assertEqual({p.name for p in self.client.iterdir()}, {'Wow.exe', 'Data'})
        self.assertEqual(installer.install(self.client, True, True, self.report)['state'], 'already-installed')

    def test_running_game_blocks_write(self):
        with patch.object(installer, 'require_wow_closed', side_effect=ValueError('running')):
            with self.assertRaises(ValueError):
                installer.install(self.client, True, True, self.report)
        self.assertEqual(self.exe.read_bytes(), b'original')
        self.assertFalse(self.report.exists())

    def test_changed_executable_preserved(self):
        with patch.object(installer, 'require_wow_closed', side_effect=lambda: self.exe.write_bytes(b'later-edit')):
            with self.assertRaises(PatchError):
                installer.install(self.client, True, True, self.report)
        self.assertEqual(self.exe.read_bytes(), b'later-edit')

    def test_apply_requires_explicit_no_backup(self):
        with self.assertRaises(ValueError):
            installer.install(self.client, True, False, self.report)
        self.assertEqual(self.exe.read_bytes(), b'original')

    def test_unknown_executable_refused(self):
        self.exe.write_bytes(b'unknown')
        with self.assertRaises(PatchError):
            installer.install(self.client)

    def test_symlink_and_report_inside_client_refused(self):
        original = self.root / 'original.exe'
        self.exe.rename(original)
        self.exe.symlink_to(original)
        with self.assertRaises(ValueError):
            installer.install(self.client)
        self.exe.unlink(); original.rename(self.exe)
        with self.assertRaises(ValueError):
            installer.install(self.client, True, True, self.client / 'report.json')
