"""Validate raw-export metadata before using any metadata-derived output paths."""
RACES = ('Human', 'Orc', 'Dwarf', 'NightElf', 'Scourge', 'Tauren', 'Gnome', 'Troll', 'BloodElf', 'Draenei')
BUILD_CONFIG = 'c9fa1a64b0170829cc5c5c98c71025c3'


def validate_models(status):
  if status.get('build', {}).get('BuildConfig') != BUILD_CONFIG:
    raise ValueError('Raw export differs from the supported pinned BuildConfig')
  models = status.get('models')
  if not isinstance(models, list) or len(models) != 20:
    raise ValueError('Expected exactly 20 race/sex models')
  expected = {(race, sex) for race in RACES for sex in ('Male', 'Female')}
  seen, ids = set(), set()
  for model in models:
    if not isinstance(model, dict):
      raise ValueError('Invalid model metadata')
    race, sex = model.get('race'), model.get('sex')
    if not isinstance(race, str) or not isinstance(sex, str) or (race, sex) not in expected:
      raise ValueError('Unknown race/sex pair')
    pair, file_id = (race, sex), model.get('fileDataId')
    if pair in seen or type(file_id) is not int or file_id <= 0 or file_id in ids:
      raise ValueError('Duplicate model or invalid FileDataID')
    if model.get('modelPath') != f'Character/{race}/{sex}/{race}{sex}_HD.m2':
      raise ValueError('Non-canonical model path in raw export')
    if model.get('state') != 'complete':
      raise ValueError('Raw model export is incomplete')
    seen.add(pair)
    ids.add(file_id)
  return models
