"""Resolve Human Male classic appearance selectors to Retail source texture layers.

This is a data crosswalk, not a claim that the resulting render is correct.
"""
import json
import struct
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
DATA = ROOT / 'assets/appearance'


def main():
  def table(name):
    return json.loads((DATA / (name + '.json')).read_text())
  options = {x['Name_lang']: x['ID'] for x in table('ChrCustomizationOption') if x['ChrModelID'] == 1}
  choices = table('ChrCustomizationChoice')
  materials = {x['ID']: x for x in table('ChrCustomizationMaterial')}
  files = {x['MaterialResourcesID']: x['FileDataID'] for x in table('TextureFileData') if x['UsageType'] == 0}
  elements = table('ChrCustomizationElement')
  layers = {x['ChrModelTextureTargetID'][0]: x for x in table('ChrModelTextureLayer') if x['CharComponentTextureLayoutsID'] == 103}

  def choice(name, order):
    matches = [x for x in choices if x['ChrCustomizationOptionID'] == options[name] and x['OrderIndex'] == order]
    if len(matches) != 1:
      raise ValueError(f'{name} {order}: ambiguous or absent choice')
    return matches[0]['ID']

  def resolve(selected):
    result = []
    for element in elements:
      if element['ChrCustomizationChoiceID'] not in selected or not element['ChrCustomizationMaterialID']:
        continue
      related = element['RelatedChrCustomizationChoiceID']
      if related and related not in selected:
        continue
      material = materials[element['ChrCustomizationMaterialID']]
      target = material['ChrModelTextureTargetID']
      layer = layers.get(target)
      if not layer:
        continue
      result.append({'file': files[material['MaterialResourcesID']], 'target': target, **layer})
    return sorted(result, key=lambda x: x['Layer'])

  data = dbc_path('CharSections.dbc').read_bytes()
  count, fields, stride, _ = struct.unpack_from('<4I', data, 4)
  assert data[:4] == b'WDBC' and fields == 10 and stride == 40
  strings = data[20 + count * stride:]
  result = []
  missing = []
  for index in range(count):
    row = struct.unpack_from('<10I', data, 20 + index * stride)
    if row[1:3] != (1, 0):
      continue
    kind, variation, color = row[3], row[8], row[9]
    paths = [strings[o:strings.index(0, o)].decode() if o else '' for o in row[4:7]]
    try:
      if kind in (0, 4):
        selected = [choice('Skin Color', color)]
      elif kind == 1:
        selected = [choice('Skin Color', color), choice('Face', variation)]
      elif kind == 3:
        selected = [choice('Hair Color', color), choice('Hair Style', variation)]
      elif kind == 2:
        selected = [choice('Hair Color', color), choice('Eyebrows', 0)]
      else:
        continue
      result.append({'row': index, 'id': row[0], 'kind': kind, 'variation': variation,
                     'color': color, 'paths': paths, 'layers': resolve(selected)})
    except ValueError as error:
      missing.append({'row': index, 'error': str(error)})
  # Visually inspected source 3484643: neutral grey iris (order1 is magenta).
  eyes = resolve([choice('Eye Color', 0), choice('Eyesight', 0)])
  eye_candidates = {str(order): resolve([choice('Eye Color', order), choice('Eyesight', 0)]) for order in range(12)}
  requested = sorted({layer['file'] for row in result for layer in row['layers']} | {x['file'] for group in eye_candidates.values() for x in group})
  (DATA / 'human-plan.json').write_text(json.dumps({'rows': result, 'eyes': eyes, 'unmapped': missing}, indent=2))
  (DATA / 'texture-requests.json').write_text(json.dumps(requested))
  (DATA / 'eye-candidates.json').write_text(json.dumps(eye_candidates, indent=2))
  print(f'{len(result)} rows, {len(requested)} source textures, {len(missing)} unmapped')


if __name__ == '__main__':
  main()
