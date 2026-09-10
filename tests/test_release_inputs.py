import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_profile import BUILD_CONFIG, RACES, validate_models
from install_export_hook import ANCHOR, hook


class ReleaseInputTests(unittest.TestCase):
  def status(self):
    return {'build': {'BuildConfig': BUILD_CONFIG}, 'models': [
      {'race': race, 'sex': sex, 'modelPath': f'Character/{race}/{sex}/{race}{sex}_HD.m2',
       'fileDataId': 100 + i * 2 + j, 'state': 'complete'}
      for i, race in enumerate(RACES) for j, sex in enumerate(('Male', 'Female'))]}

  def test_exact_model_matrix(self):
    self.assertEqual(len(validate_models(self.status())), 20)
    for key, value in (('race', '../outside'), ('sex', []), ('modelPath', '/outside.m2'),
                       ('fileDataId', True), ('state', 'failed')):
      status = self.status()
      status['models'][0][key] = value
      with self.subTest(key=key), self.assertRaises(ValueError):
        validate_models(status)
    status = self.status()
    status['models'][1] = copy.deepcopy(status['models'][0])
    with self.assertRaises(ValueError):
      validate_models(status)
    status = self.status()
    status['build']['BuildConfig'] = '0' * 32
    with self.assertRaises(ValueError):
      validate_models(status)

  def test_export_hook_idempotence_and_relocated_source(self):
    path = Path('/tmp/synthetic-export-adapter.cjs')
    result = hook(ANCHOR, path)
    self.assertEqual(hook(result, path), result)
    for text, module in ((ANCHOR * 2, path), ('unknown', path),
                         ('WXL_AUTO_EXPORT_HUMAN_MALE', path),
                         (result, Path('/tmp/relocated-adapter.cjs'))):
      with self.assertRaises(ValueError):
        hook(text, module)
