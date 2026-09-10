from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_publication import check_file


class PublicationTests(unittest.TestCase):
  def test_source_and_private_inventory(self):
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      source = root / 'source.py'
      source.write_text('print("synthetic")\n')
      self.assertIsNone(check_file(root, 'source.py'))
      for name in ('../outside.py', 'assets/export.json', 'game.MPQ', '.env.local'):
        self.assertIsNotNone(check_file(root, name))
      for data in (b'\0binary', b'gh' + b'p_' + b'a' * 30,
                   b'/Users/' + b'synthetic-private-user/file'):
        source.write_bytes(data)
        self.assertIsNotNone(check_file(root, 'source.py'))
      link = root / 'link.py'
      link.symlink_to(source)
      self.assertIsNotNone(check_file(root, 'link.py'))
