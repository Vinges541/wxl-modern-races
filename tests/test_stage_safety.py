import json
from pathlib import Path
import unittest

from tests import test_pipeline
from wxl_races.bundle import BundleError, load_target, stage
from wxl_races.resolver import ExportIndex


class StageSafetyTests(unittest.TestCase):
  setUp = test_pipeline.PipelineTests.setUp
  tearDown = test_pipeline.PipelineTests.tearDown
  _write_export = test_pipeline.PipelineTests._write_export

  def test_unsafe_manifest_paths(self):
    original = json.loads(self.target_path.read_text())
    for value in ('../outside.m2', '/outside.m2', 'C:\\outside.m2',
                  '\\\\server\\share\\x.m2', 'a/../x.m2', '.', 'a//x.m2', 42):
      with self.subTest(value=value):
        original['target']['legacyPath'] = value
        self.target_path.write_text(json.dumps(original))
        with self.assertRaises(BundleError):
          load_target(self.target_path)

  def test_stage_direct_call_rejects_traversal(self):
    index = ExportIndex(self.export_root, [self._write_export()])
    target = load_target(self.target_path)
    before = self.target_path.read_bytes()
    target['target']['legacyPath'] = '../human_male.json'
    with self.assertRaises(BundleError):
      stage(target, index, self.root / 'output')
    self.assertEqual(self.target_path.read_bytes(), before)

  def test_file_directory_and_root_symlinks(self):
    index = ExportIndex(self.export_root, [self._write_export()])
    target = load_target(self.target_path)
    outside = self.root / 'outside'
    outside.mkdir()
    sentinel = outside / 'sentinel'
    sentinel.write_bytes(b'unchanged')
    for kind in ('root', 'directory', 'file', 'report'):
      with self.subTest(kind=kind):
        output = self.root / kind
        if kind == 'root':
          output.symlink_to(outside, target_is_directory=True)
        else:
          output.mkdir()
          if kind == 'directory':
            (output / 'Character').symlink_to(outside, target_is_directory=True)
          elif kind == 'file':
            dest = output / target['target']['legacyPath']
            dest.parent.mkdir(parents=True)
            dest.symlink_to(sentinel)
          else:
            (output / 'bundle-report.json').symlink_to(sentinel)
        with self.assertRaises(BundleError):
          stage(target, index, output)
        self.assertEqual(sentinel.read_bytes(), b'unchanged')
