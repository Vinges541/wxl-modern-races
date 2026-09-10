"""Audit all twenty appearance crosswalks, preserving unmapped rows explicitly."""
import json
import struct
from collections import defaultdict
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
DATA = ROOT / 'assets/appearance'
RACES = {1: 'Human', 2: 'Orc', 3: 'Dwarf', 4: 'NightElf', 5: 'Scourge',
         6: 'Tauren', 7: 'Gnome', 8: 'Troll', 10: 'BloodElf', 11: 'Draenei'}


def main():
  table = lambda name: json.loads((DATA / f'{name}.json').read_text())
  models = {r['ID']: r for r in table('ChrModel')}
  options = defaultdict(dict)
  for r in table('ChrCustomizationOption'):
    options[r['ChrModelID']][r['Name_lang']] = r['ID']
  choices = defaultdict(dict)
  for r in table('ChrCustomizationChoice'):
    choices[r['ChrCustomizationOptionID']].setdefault(r['OrderIndex'], []).append(r['ID'])
  elements = defaultdict(list)
  for r in table('ChrCustomizationElement'):
    elements[r['ChrCustomizationChoiceID']].append(r)
  materials = {r['ID']: r for r in table('ChrCustomizationMaterial')}
  files = {r['MaterialResourcesID']: r['FileDataID'] for r in table('TextureFileData') if r['UsageType'] == 0}
  geosets = {r['ID']: r for r in table('ChrCustomizationGeoset')}
  all_layers = table('ChrModelTextureLayer')
  dbc = dbc_path('CharSections.dbc').read_bytes()
  count, fields, stride, _ = struct.unpack_from('<4I', dbc, 4)
  assert fields == 10 and stride == 40
  strings = dbc[20 + count * stride:]
  by_race = defaultdict(list)
  for index in range(count):
    r = struct.unpack_from('<10I', dbc, 20 + index * stride)
    by_race[r[1:3]].append((index, r))
  plans = []
  requests = set(json.loads((DATA / 'texture-requests.json').read_text()))
  for link in table('ChrRaceXChrModel'):
    race, sex, mid = link['ChrRacesID'], link['Sex'], link['ChrModelID']
    if race not in RACES or mid > 22 or sex not in (0, 1):
      continue
    model = models[mid]
    layout = model['CharComponentTextureLayoutID']
    layers = {r['ChrModelTextureTargetID'][0]: r for r in all_layers if r['CharComponentTextureLayoutsID'] == layout}
    opts = options[mid]
    def choice(name, order):
      found = choices[opts[name]].get(order, []) if name in opts else []
      if len(found) != 1:
        raise ValueError(f'{name}: no unique order {order}')
      return found[0]
    defaults = {name: choice(name, min(choices[oid])) for name, oid in opts.items() if choices[oid]}
    def resolve(selected, emit=None):
      result, geometry = [], set()
      selected = set(selected)
      for cid in (selected if emit is None else set(emit)):
        for e in elements[cid]:
          if e['RelatedChrCustomizationChoiceID'] and e['RelatedChrCustomizationChoiceID'] not in selected:
            continue
          gid = e.get('ChrCustomizationGeosetID', 0)
          if gid:
            g = geosets[gid]
            geometry.add(g['GeosetType'] * 100 + g['GeosetID'])
          mat = materials.get(e['ChrCustomizationMaterialID'])
          if mat and mat['ChrModelTextureTargetID'] in layers:
            layer = layers[mat['ChrModelTextureTargetID']]
            fid = files.get(mat['MaterialResourcesID'])
            if fid is None:
              raise ValueError(f"unresolved material {mat['ID']}")
            entry = {'file': fid, 'target': mat['ChrModelTextureTargetID'], **layer}
            if entry not in result:
              result.append(entry)
      return sorted(result, key=lambda r: (r['Layer'], r['ID'], r['file'])), sorted(geometry)
    rows, missing = [], []
    for index, r in by_race[race, sex]:
      kind, variation, color = r[3], r[8], r[9]
      if kind not in range(5):
        continue
      try:
        selected = dict(defaults)
        emit_names = set()
        if kind in (0, 4):
          selected['Skin Color'] = choice('Skin Color', color)
          emit_names = {'Skin Color'}
        elif kind == 1:
          selected['Skin Color'] = choice('Skin Color', color)
          selected['Face'] = choice('Face', variation)
          emit_names = {'Skin Color', 'Face'}
        elif kind == 3:
          style, tint = ('Horn Style', 'Horn Color') if race == 6 else ('Hair Style', 'Hair Color')
          selected[style], selected[tint] = choice(style, variation), choice(tint, color)
          emit_names = {style, tint}
          if race == 6:
            emit_names.update(name for name in ('Hair', 'Skin Color') if name in selected)
        elif kind == 2 and 'Hair Color' in opts:
          selected['Hair Color'] = choice('Hair Color', color)
          emit_names = {'Hair Color'}
          if 'Eyebrows' in selected:
            emit_names.add('Eyebrows')
          if race == 4 and sex == 1:
            selected['Markings'] = choice('Markings', variation)
            emit_names.add('Markings')
        resolved, geometry = resolve(selected.values(), [selected[name] for name in emit_names])
        paths = [strings[o:strings.index(0, o)].decode() if o else '' for o in r[4:7]]
        rows.append({'row': index, 'id': r[0], 'kind': kind, 'variation': variation, 'color': color,
                     'paths': paths, 'flags': r[7], 'layers': resolved})
        requests.update(x['file'] for x in resolved)
      except (ValueError, KeyError) as error:
        missing.append({'row': index, 'id': r[0], 'kind': kind, 'flags': r[7], 'error': str(error)})
    default_layers, geometry = resolve(defaults.values())
    eyes = [r for r in default_layers if r['TextureType'] == 19]
    plan = {'raceId': race, 'race': RACES[race], 'sex': 'Female' if sex else 'Male', 'sexId': sex,
            'modelId': mid, 'layout': layout, 'rows': rows, 'unmapped': missing,
            'defaultGeosets': geometry, 'eyes': eyes, 'defaultLayers': default_layers,
            'selectionPolicy': 'legacy OrderIndex crosswalk; modern-only options default; runtime unverified'}
    plans.append(plan)
    print(RACES[race], sex, len(rows), 'mapped', len(missing), 'unmapped', 'defaults', geometry, flush=True)
  assert len(plans) == 20
  (DATA / 'all-appearance-plan.json').write_text(json.dumps(plans, indent=2))
  (DATA / 'texture-requests.json').write_text(json.dumps(sorted(requests)))
  print('Sources requested:', len(requests))


if __name__ == '__main__':
  main()
