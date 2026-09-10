import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import install_release as installer
from wxl_races.bundle import BundleError


class InstallTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.client = self.root / 'client'
    self.package = self.root / 'package'
    self.client.mkdir()
    self.package.mkdir()
    self.name = 'Data/Patch-ModernRaces-HD.MPQ/Character/Test.m2'
    source = self.package / self.name
    source.parent.mkdir(parents=True)
    source.write_bytes(b'synthetic new')
    self.report = {'schemaVersion': 1, 'kind': 'wxl-modern-races-assets', 'locale': 'ruRU',
                   'files': [{'path': self.name, 'size': source.stat().st_size, 'sha256': installer.digest(source)}]}
    self.save()

  def save(self):
    (self.package / 'release-manifest.json').write_text(json.dumps(self.report))

  @patch.object(installer, 'require_wow_closed')
  def test_install_verify_idempotence_rollback(self, closed):
    target = self.client / self.name
    target.parent.mkdir(parents=True)
    target.write_bytes(b'synthetic old')
    entries = installer.plan(self.package, self.client)
    self.assertEqual(target.read_bytes(), b'synthetic old')
    backup = installer.apply(self.package, self.client, entries)
    self.assertEqual(target.read_bytes(), b'synthetic new')
    self.assertEqual(installer.plan(self.package, self.client), [])
    installer.rollback(backup, self.client, write=True)
    self.assertEqual(target.read_bytes(), b'synthetic old')
    self.assertTrue((backup / 'rollback.json').exists())

  @patch.object(installer, 'require_wow_closed')
  def test_new_file_rollback_and_later_modification(self, closed):
    target = self.client / self.name
    backup = installer.apply(self.package, self.client, installer.plan(self.package, self.client))
    target.write_bytes(b'user change')
    with self.assertRaises(ValueError):
      installer.rollback(backup, self.client, write=True)
    self.assertEqual(target.read_bytes(), b'user change')
    target.write_bytes(b'synthetic new')
    installer.rollback(backup, self.client, write=True)
    self.assertFalse(target.exists())

  def test_invalid_paths_hashes_duplicates_and_scale(self):
    self.report['files'].append(dict(self.report['files'][0]))
    self.save()
    with self.assertRaises(ValueError):
      installer.plan(self.package, self.client)
    self.report['files'].pop()
    for name in ('../outside.m2', '/absolute.m2', 'Data/Patch-ModernRaces-HD.MPQ/DBFilesClient/CreatureModelData.dbc'):
      self.report['files'][0]['path'] = name
      self.save()
      with self.assertRaises((ValueError, BundleError)):
        installer.plan(self.package, self.client)
    self.report['files'][0]['path'] = self.name
    self.report['files'][0]['sha256'] = '0' * 64
    self.save()
    with self.assertRaises(ValueError):
      installer.plan(self.package, self.client)

  def test_symlink_destination(self):
    (self.client / 'Data').symlink_to(self.root, target_is_directory=True)
    with self.assertRaises(BundleError):
      installer.plan(self.package, self.client)

  @patch.object(installer, 'require_wow_closed')
  def test_partial_install_has_usable_checkpoint(self, closed):
    entries = installer.plan(self.package, self.client)
    real_write = installer.atomic_write

    def fail_client_write(path, data, mode):
      if path == self.client / self.name:
        raise OSError('simulated write failure')
      return real_write(path, data, mode)

    with patch.object(installer, 'atomic_write', side_effect=fail_client_write):
      with self.assertRaisesRegex(ValueError, 'rollback checkpoint'):
        installer.apply(self.package, self.client, entries)
    backups = list((self.client / 'DisabledPatches/ReleaseBackups').iterdir())
    self.assertEqual(len(backups), 1)
    installer.rollback(backups[0], self.client, write=True)
    self.assertFalse((self.client / self.name).exists())

  @patch.object(installer, 'require_wow_closed', side_effect=ValueError('running'))
  def test_running_refuses_any_write(self, closed):
    with self.assertRaises(ValueError):
      installer.apply(self.package, self.client, installer.plan(self.package, self.client))
    self.assertFalse((self.client / 'DisabledPatches').exists())
