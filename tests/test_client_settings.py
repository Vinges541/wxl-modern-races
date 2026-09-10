import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import configure_client as config


class ClientSettingsTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.client = Path(self.directory.name)
    (self.client / 'Wow.exe').write_bytes(b'MZ fixture')
    (self.client / 'Data').mkdir()
    (self.client / 'WTF').mkdir()
    self.wtf = self.client / 'WTF/Config.wtf'

  def run_cli(self, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
      result = config.main(['--client', str(self.client), *args])
    return result, output.getvalue()

  def test_preserves_unmanaged_bytes_bom_crlf_and_comments(self):
    original = (b'\xef\xbb\xbfSET accountName "PRIVATE"\r\n'
                b'# legacy text: \xff\xfe\r\nSET extShadowQuality "5"\r\n'
                b'  SET SHADOWINSTANCING "1" // keep explanation\r\n')
    after, _ = config.update_settings(original, *config.PROFILE['WTF/Config.wtf'])
    self.assertTrue(after.startswith(original.split(b'  SET')[0]))
    self.assertIn(b'  SET SHADOWINSTANCING "0" // keep explanation\r\n', after)
    self.assertNotIn(b'\n', after.replace(b'\r\n', b''))
    self.assertEqual(config.update_settings(after, *config.PROFILE['WTF/Config.wtf'])[0], after)

  def test_duplicates_and_missing_final_newline(self):
    data = b'SET shadowInstancing "1"\nSET shadowinstancing "1" # explanation'
    after, details = config.update_settings(data, *config.PROFILE['WTF/Config.wtf'])
    self.assertEqual(after.lower().count(b'set shadowinstancing'), 1)
    self.assertIn(b'# explanation\nSET gxWindow', after)
    self.assertEqual(details[0]['before'], ['1', '1'])

  def test_shader_cache_only(self):
    data = b'# shaderCache.enable = true\ncolor.hdr.enable = true\nshaderCache.enable = true # reason\n'
    after, _ = config.update_settings(data, *config.PROFILE['mtld3d.conf'])
    self.assertEqual(after, data.replace(b' = true # reason', b' = false # reason'))

  def test_malformed_managed_values_rejected(self):
    for data, profile in [(b'SET shadowInstancing 1\n', 'WTF/Config.wtf'),
                           (b'shaderCache.enable =\n', 'mtld3d.conf'),
                           (b'\xff\xfeS\0E\0T\0', 'WTF/Config.wtf')]:
      with self.subTest(data=data), self.assertRaises(config.SettingsError):
        config.update_settings(data, *config.PROFILE[profile])

  def test_preview_check_no_writes_or_sensitive_output(self):
    self.wtf.write_bytes(b'SET accountName "PRIVATE"\nSET realmList "private.example"\n')
    for args, status in [((), 0), (('--check',), 1)]:
      code, output = self.run_cli(*args)
      self.assertEqual(code, status)
      self.assertNotIn('PRIVATE', output)
      self.assertNotIn('private.example', output)
      self.assertFalse((self.client / 'DisabledPatches').exists())
      self.assertFalse((self.client / 'mtld3d.conf').exists())
      self.assertNotIn(b'shadowInstancing', self.wtf.read_bytes())

  @patch.object(config, 'require_wow_closed')
  def test_apply_backups_and_idempotence(self, closed):
    original = b'SET accountName "PRIVATE"\nSET extShadowQuality "3"\nSET gxResolution "1920x1080"\n'
    self.wtf.write_bytes(original)
    self.wtf.chmod(0o640)
    self.assertEqual(self.run_cli('--apply')[0], 0)
    closed.assert_called_once()
    backup = next((self.client / 'DisabledPatches/ClientSettings').iterdir())
    self.assertEqual((backup / 'WTF/Config.wtf').read_bytes(), original)
    self.assertEqual((backup / 'WTF/Config.wtf').stat().st_mode & 0o777, 0o600)
    self.assertIn('"existed": false', (backup / 'manifest.json').read_text())
    self.assertTrue(self.wtf.read_bytes().startswith(original))
    self.assertEqual(self.wtf.stat().st_mode & 0o777, 0o640)
    stamp = self.wtf.stat().st_mtime_ns
    self.assertEqual(self.run_cli('--check')[0], 0)
    self.assertEqual(self.run_cli('--apply')[0], 0)
    self.assertEqual(self.wtf.stat().st_mtime_ns, stamp)
    self.assertEqual(len(list(backup.parent.iterdir())), 1)

  @patch.object(config, 'require_wow_closed')
  def test_create_missing_configuration(self, closed):
    (self.client / 'WTF').rmdir()
    self.assertEqual(self.run_cli('--apply')[0], 0)
    self.assertIn(b'SET gxWindow "0"', self.wtf.read_bytes())

  @patch.object(config, 'require_wow_closed')
  def test_stale_plan_rejected_without_backup(self, closed):
    changes = config.plan(self.client)
    self.wtf.write_bytes(b'SET gxWindow "1"\n')
    with self.assertRaises(config.SettingsError):
      config.apply_changes(self.client, changes)
    self.assertFalse((self.client / 'DisabledPatches').exists())

  def test_symlink_target_rejected(self):
    (self.client / 'other').write_bytes(b'untouched')
    self.wtf.symlink_to(self.client / 'other')
    self.assertEqual(self.run_cli('--apply')[0], 2)
    self.assertEqual((self.client / 'other').read_bytes(), b'untouched')

  @patch.object(config, 'require_wow_closed')
  def test_symlink_backup_rejected(self, closed):
    (self.client / 'DisabledPatches').symlink_to(self.client / 'Data')
    self.assertEqual(self.run_cli('--apply')[0], 2)
    self.assertFalse(self.wtf.exists())

  @patch.object(config, 'require_wow_closed', side_effect=config.SettingsError('Close WoW'))
  def test_running_game_refuses_writes(self, closed):
    self.assertEqual(self.run_cli('--apply')[0], 2)
    self.assertFalse(self.wtf.exists())
    self.assertFalse((self.client / 'DisabledPatches').exists())

  @patch.object(config.sys, 'platform', 'darwin')
  @patch.object(config.subprocess, 'run')
  def test_running_process_matching(self, run):
    for command in ['/Users/a/Downloads/WoTLK/Wow.exe -d3d9',
                    r'Z:\Users\a\Downloads\WoTLK\Wow.exe -d3d9',
                    'wine "C:\\Games\\WoTLK\\WoW.exe"', 'Wow.exe']:
      run.return_value.stdout = command
      with self.subTest(command=command), self.assertRaises(config.SettingsError):
        config.require_wow_closed()
    run.return_value.stdout = 'python3 tools/configure_client.py --apply\nwineserver\n'
    config.require_wow_closed()

  @patch.object(config.sys, 'platform', 'darwin')
  @patch.object(config.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ps'))
  def test_process_check_failure_is_fail_closed(self, run):
    with self.assertRaises(config.SettingsError):
      config.require_wow_closed()

  def test_invalid_client_rejected(self):
    (self.client / 'Wow.exe').write_bytes(b'not an executable')
    self.assertEqual(self.run_cli('--apply')[0], 2)
    self.assertFalse(self.wtf.exists())


if __name__ == '__main__':
  unittest.main()
