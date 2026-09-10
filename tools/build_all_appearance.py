"""Build all-race candidates without touching the installed client.

Human Male v5 is preserved byte-for-byte. Failed variants are reported, never
silently installed with a mixture of remapped geometry and original textures.
"""
import argparse
import json
import shutil
import struct
import sys
from functools import lru_cache
from pathlib import Path
from PIL import Image
from build_human_appearance import paletted_blp, direct_hair_blp

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
DATA = ROOT / 'assets/appearance'
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.appearance import repair_human


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--race', help='Build only one named race for diagnosis')
  parser.add_argument('--resume', action='store_true', help='Preserve successful variants and retry failed ones')
  args = parser.parse_args()
  plans = json.loads((DATA / 'all-appearance-plan.json').read_text())
  sections = json.loads((DATA / 'CharComponentTextureSections.json').read_text())
  layouts = {r['ID']: r for r in json.loads((DATA / 'CharComponentTextureLayouts.json').read_text())}
  out = ROOT / 'build/all-appearance-v1'
  out.mkdir(parents=True, exist_ok=True)
  # Begin with the verified Human Male DBC, not the unmodified original.
  dbc = bytearray((ROOT / 'build/human-appearance-v5/DBFilesClient/CharSections.dbc').read_bytes())
  count, _, stride, _ = struct.unpack_from('<4I', dbc, 4)
  string_start = 20 + count * stride
  report = {'models': [], 'runtimeVerified': False, 'experimental': True}
  if args.resume:
    report = json.loads((out / 'report.json').read_text())
    dbc = bytearray((out / 'DBFilesClient/CharSections.dbc').read_bytes())
  @lru_cache(maxsize=160)
  def source(fid):
    return Image.open(DATA / f'textures/{fid}.blp').convert('RGBA')
  encoded = {}
  def encode(image):
    key = (image.size, image.tobytes())
    if key not in encoded:
      encoded[key] = paletted_blp(image)
    return encoded[key]
  for plan in plans:
    race, sex = plan['race'], plan['sex']
    if args.race and race != args.race:
      continue
    if args.resume:
      previous = next((r for r in report['models'] if (r['race'], r['sex']) == (race, sex)), None)
      if previous and previous['state'] != 'failed':
        continue
      report['models'] = [r for r in report['models'] if (r['race'], r['sex']) != (race, sex)]
    result = {'race': race, 'sex': sex, 'unmapped': plan['unmapped']}
    report['models'].append(result)
    if (race, sex) == ('Human', 'Male'):
      shutil.copytree(ROOT / 'build/human-appearance-v5/Character/Human/Male', out / 'Character/Human/Male', dirs_exist_ok=True)
      result['state'] = 'preserved-v5'
      continue
    dbc_before = bytes(dbc)
    try:
      layout = layouts[plan['layout']]
      if (layout['Width'], layout['Height']) != (2048, 1024):
        raise ValueError(f'Unsupported body atlas: {layout}')
      regions = {r['SectionType']: r for r in sections if r['CharComponentTextureLayoutID'] == plan['layout']}
      def compose(layers, targets=None):
        canvas = Image.new('RGBA', (512, 256))
        for layer in layers:
          if layer['TextureType'] != 1 or targets is not None and layer['target'] not in targets:
            continue
          if layer['BlendMode'] not in (0, 1, 9, 15):
            raise ValueError(f"Unsupported compositor blend {layer['BlendMode']}")
          mask = layer['TextureSectionTypeBitMask']
          if mask == -1:
            boxes = [(0, 0, 512, 256)]
          else:
            boxes = [(r['X']//4, r['Y']//4, r['Width']//4, r['Height']//4)
                     for k, r in regions.items() if mask & (1 << k)]
            if not boxes:
              raise ValueError(f'Unknown section mask {mask}')
          for x, y, w, h in boxes:
            canvas.alpha_composite(source(layer['file']).resize((w, h), Image.Resampling.LANCZOS), (x, y))
        return canvas
      def face(canvas):
        return canvas.crop((256, 0, 512, 256)).resize((128, 96), Image.Resampling.LANCZOS)
      prefix = f'Character/{race}/{sex}'
      target = out / prefix
      (target / 'Appearance').mkdir(parents=True, exist_ok=True)
      converted = 0
      for row in plan['rows']:
        kind, layers = row['kind'], row['layers']
        if kind == 0:
          canvas = compose(layers, {1})
          base = canvas.crop((0, 0, 256, 256))
          base.paste(face(canvas), (0, 160))
          images = [base]
        elif kind in (1, 2):
          head = face(compose(layers))
          images = [head.crop((0, 32, 128, 96)), head.crop((0, 0, 128, 32))]
        elif kind == 3:
          hairs = [r for r in layers if r['TextureType'] == 6]
          if len(hairs) != 1:
            raise ValueError(f"Hair row {row['id']}: expected one diffuse, got {len(hairs)}")
          hair = direct_hair_blp(hairs[0])
          head = face(compose(layers))
          images = [None, head.crop((0, 32, 128, 96)), head.crop((0, 0, 128, 32))]
        elif kind == 4:
          images = [compose(layers, {13}).crop((128, 96, 256, 160))]
        for slot, image in enumerate(images):
          rel = f'{prefix}/Appearance/{row["id"]}-{slot}.blp'
          (out / rel).write_bytes(hair if image is None else encode(image))
          path = rel.replace('/', '\\').encode() + b'\0'
          struct.pack_into('<I', dbc, 20 + row['row'] * stride + (4 + slot) * 4, len(dbc)-string_start)
          dbc.extend(path)
          converted += 1
      eyes = plan['eyes']
      if len(eyes) != 1:
        raise ValueError(f'Expected one default eye texture, got {len(eyes)}')
      eye_path = prefix + '/HD-Eyes.blp'
      shutil.copy2(DATA / f"textures/{eyes[0]['file']}.blp", out / eye_path)
      bindings = {}
      for layer in plan['defaultLayers']:
        typ = layer['TextureType']
        if typ in (0, 1, 2, 6, 19):
          continue
        rel = f'{prefix}/HD-Material-{typ}.blp'
        if typ in bindings:
          raise ValueError(f'Ambiguous default material type {typ}')
        bindings[typ] = rel
        shutil.copy2(DATA / f"textures/{layer['file']}.blp", out / rel)
      original = ROOT / 'build/Patch-ModernRaces-HD.MPQ' / prefix
      selected = {g for g in plan['defaultGeosets'] if g >= 2000 and g % 100}
      # Baseline modern body/feet/face/eyes, not extra jewelry or DH geometry.
      for group in (20, 22, 23, 32, 33, 51):
        if not any(g//100 == group for g in selected):
          selected.add(group*100 + (2 if group == 32 else 1))
      model, skins, stats = repair_human((original / f'{race}{sex}.m2').read_bytes(),
        {p.name: p.read_bytes() for p in original.glob('*.skin')}, eye_path,
        default_geosets=selected, static_bindings=bindings)
      (target / f'{race}{sex}.m2').write_bytes(model)
      for name, data in skins.items():
        (target / name).write_bytes(data)
      result.update(state='prepared', textures=converted, geometry=stats, defaults=sorted(selected),
                    staticBindings=bindings, limitations=['unmapped rows retain original textures',
                      'modern-only features use a fixed default', 'helmets and facial geoset crosswalk need runtime checks'])
    except Exception as error:
      dbc = bytearray(dbc_before)
      result.update(state='failed', error=str(error))
    encoded.clear()
    print(race, sex, result['state'], result.get('error', ''), flush=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2))
  struct.pack_into('<I', dbc, 16, len(dbc)-string_start)
  for directory in ('DBFilesClient', 'locale/DBFilesClient'):
    (out / directory).mkdir(parents=True, exist_ok=True)
    (out / directory / 'CharSections.dbc').write_bytes(dbc)
  (out / 'report.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
  main()
