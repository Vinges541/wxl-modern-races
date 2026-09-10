"""Build a separate Human appearance candidate. Does not deploy to a client."""
import json
from pathlib import Path
import struct
import sys
import argparse
from PIL import Image

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.appearance import repair_human

DATA = ROOT / 'assets/appearance'
OUT = ROOT / 'build/human-appearance-candidate'


def direct_hair_blp(layer):
  """Hair is sampled directly by the GPU, not by the paletted body painter."""
  data = (DATA / 'textures' / f"{layer['file']}.blp").read_bytes()
  if len(data) >= 148 and data[:4] == b'BLP2' and data[8] == 1 and data[9] == 0:
    # Tauren fur is an opaque paletted source, unlike the Human DXT source.
    from build_npc_appearance import dxt1_blp
    return dxt1_blp(Image.open(DATA / 'textures' / f"{layer['file']}.blp"))
  if len(data) < 148 or data[:4] != b'BLP2' or data[8] != 2 or data[10] not in (0, 1, 7):
    raise ValueError('Hair source must use a legacy-compatible DXT encoding')
  offsets = struct.unpack_from('<16I', data, 20)
  lengths = struct.unpack_from('<16I', data, 84)
  if not offsets[0] or any(o + n > len(data) for o, n in zip(offsets, lengths)):
    raise ValueError('Hair mip data out of bounds')
  return data


def paletted_blp(image):
  """BLP2 palette + 8-bit alpha, full mip chain, as required by Wrath's painter."""
  image = image.convert('RGBA')
  palette_image = image.convert('RGB').quantize(colors=256, method=Image.Quantize.MEDIANCUT)
  palette = palette_image.getpalette()
  palette += [0] * (768 - len(palette))
  palette_bytes = bytes(c for i in range(256) for c in (palette[3*i+2], palette[3*i+1], palette[3*i], 255))
  mipmaps = []
  current = image
  while True:
    indexed = current.convert('RGB').quantize(palette=palette_image, dither=Image.Dither.NONE)
    mipmaps.append(indexed.tobytes() + current.getchannel('A').tobytes())
    if current.size == (1, 1):
      break
    current = current.resize((max(1, current.width // 2), max(1, current.height // 2)), Image.Resampling.BOX)
  offsets, lengths = [0]*16, [0]*16
  cursor = 148 + 1024
  for i, mip in enumerate(mipmaps):
    offsets[i], lengths[i] = cursor, len(mip)
    cursor += len(mip)
  return (b'BLP2' + struct.pack('<I4BII', 1, 1, 8, 0, 1, image.width, image.height) +
          struct.pack('<16I', *offsets) + struct.pack('<16I', *lengths) + palette_bytes + b''.join(mipmaps))


def head_to_classic(head):
  return head.resize((512, 384), Image.Resampling.LANCZOS)


def main():
  global OUT
  parser = argparse.ArgumentParser()
  parser.add_argument('--legacy-resolution', action='store_true', help='Use native Wrath compositor source dimensions')
  args = parser.parse_args()
  if args.legacy_resolution:
    OUT = ROOT / 'build/human-appearance-v5'
  plan = json.loads((DATA / 'human-plan.json').read_text())
  sections = {x['SectionType']: x for x in json.loads((DATA / 'CharComponentTextureSections.json').read_text())
              if x['CharComponentTextureLayoutID'] == 103}
  OUT.mkdir(parents=True, exist_ok=True)
  def source(layer):
    return Image.open(DATA / 'textures' / f"{layer['file']}.blp").convert('RGBA')
  def compose(layers, targets=None):
    canvas = Image.new('RGBA', (2048, 1024))
    for layer in layers:
      if layer['TextureType'] != 1 or (targets is not None and layer['target'] not in targets):
        continue
      if layer['BlendMode'] not in (0, 1, 9, 15):
        raise ValueError(f"unimplemented blend mode {layer['BlendMode']}")
      mask = layer['TextureSectionTypeBitMask']
      if mask == -1:
        box = (0, 0, 2048, 1024)
      else:
        region = next(x for k, x in sections.items() if mask & (1 << k))
        box = (region['X'], region['Y'], region['Width'], region['Height'])
      image = source(layer).resize((box[2], box[3]), Image.Resampling.LANCZOS)
      canvas.alpha_composite(image, (box[0], box[1]))
    return canvas
  dbc = bytearray(dbc_path('CharSections.dbc').read_bytes())
  count, fields, stride, string_size = struct.unpack_from('<4I', dbc, 4)
  assert fields == 10 and stride == 40
  string_start = 20 + count * stride
  converted = 0
  for row in plan['rows']:
    kind, layers = row['kind'], row['layers']
    if kind == 0:
      canvas = compose(layers, {1})
      base = canvas.crop((0, 0, 1024, 1024))
      base.paste(head_to_classic(canvas.crop((1024, 0, 2048, 1024))), (0, 640))
      images = [base]
    elif kind in (1, 2):
      canvas = compose(layers, None if kind == 1 else {7, 8})
      face = head_to_classic(canvas.crop((1024, 0, 2048, 1024)))
      images = [face.crop((0, 128, 512, 384)), face.crop((0, 0, 512, 128))]
    elif kind == 3:
      hair = [x for x in layers if x['TextureType'] == 6]
      if len(hair) != 1:
        raise ValueError(f"ambiguous hair material for row {row['row']}")
      canvas = compose(layers)
      face = head_to_classic(canvas.crop((1024, 0, 2048, 1024)))
      images = [source(hair[0]), face.crop((0, 128, 512, 384)), face.crop((0, 0, 512, 128))]
    elif kind == 4:
      canvas = compose(layers, {13})
      images = [canvas.crop((512, 384, 1024, 640))]
    else:
      raise ValueError(kind)
    for slot, image in enumerate(images):
      if args.legacy_resolution:
        # Keep Retail artwork and the remapped HD mesh, but use the source
        # dimensions of the native 256-square character compositor. Large
        # paletted inputs overflowed the asynchronous loose-file read path.
        # DBC order is LOWER then UPPER, unlike atlas region order (8, 9).
        # Wrong aspect ratio makes the native mip selection loop never exit.
        sizes = {0: [(256, 256)], 1: [(128, 64), (128, 32)],
                 2: [(128, 64), (128, 32)], 3: [(256, 128), (128, 64), (128, 32)],
                 4: [(128, 64)]}
        image = image.resize(sizes[kind][slot], Image.Resampling.LANCZOS)
      # Unique per-row paths prevent male/female shared texture names colliding.
      relative = f"Character/Human/Male/Appearance/{row['id']}-{slot}.blp"
      dest = OUT / relative
      dest.parent.mkdir(parents=True, exist_ok=True)
      dest.write_bytes(direct_hair_blp(hair[0]) if kind == 3 and slot == 0 else paletted_blp(image))
      encoded = relative.replace('/', '\\').encode() + b'\0'
      struct.pack_into('<I', dbc, 20 + row['row'] * stride + (4 + slot) * 4, len(dbc) - string_start)
      dbc.extend(encoded)
      converted += 1
    if row['kind'] == 0 and row['color'] == 0:
      image = images[0]
      image.save(OUT / 'human-base-atlas.png')
  struct.pack_into('<I', dbc, 16, len(dbc) - string_start)
  (OUT / 'DBFilesClient').mkdir(exist_ok=True)
  (OUT / 'DBFilesClient/CharSections.dbc').write_bytes(dbc)
  eye_path = 'Character/Human/Male/HD-Eyes.blp'
  eyes = [x for x in plan['eyes'] if x['TextureType'] == 19]
  if len(eyes) != 1:
    raise ValueError('ambiguous eye texture')
  (OUT / eye_path).write_bytes((DATA / 'textures' / f"{eyes[0]['file']}.blp").read_bytes())
  original = ROOT / 'build/Patch-ModernRaces-HD.MPQ/Character/Human/Male'
  model, skins, report = repair_human((original / 'HumanMale.m2').read_bytes(),
                                    {p.name: p.read_bytes() for p in original.glob('*.skin')}, eye_path)
  target = OUT / 'Character/Human/Male'
  (target / 'HumanMale.m2').write_bytes(model)
  for name, data in skins.items():
    (target / name).write_bytes(data)
  report.update(textureCount=converted, unmapped=plan['unmapped'], experimental=True,
                nativeCompositorSourceDimensions=args.legacy_resolution,
                limitations=['Human Male only', 'Death Knight face variants 12..23 not yet mapped',
                             'Facial hair geometry presets and equipment toe selection need verification'])
  (OUT / 'appearance-report.json').write_text(json.dumps(report, indent=2))
  print(f'Prepared {converted} textures, {len(skins)} skins, {report["remappedVertices"]} UV vertices; NOT DEPLOYED')


if __name__ == '__main__':
  main()
