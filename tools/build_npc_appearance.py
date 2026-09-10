"""Repack matched Retail NPC baked atlases for the converted body UVs."""
import io
import json
import struct
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from PIL import Image

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
DATA = ROOT / 'assets/appearance'


def dxt1_blp(image):
  image = image.convert('RGB')
  width, height = image.size
  mips = []
  while True:
    stream = io.BytesIO()
    image.save(stream, format='DDS', pixel_format='DXT1')
    dds = stream.getvalue()
    if dds[:4] != b'DDS ' or dds[84:88] != b'DXT1':
      raise ValueError('Unexpected DDS encoder output')
    mips.append(dds[128:])
    if image.size == (1, 1):
      break
    image = image.resize((max(1, image.width // 2), max(1, image.height // 2)), Image.Resampling.BOX)
  offsets, lengths, cursor = [0] * 16, [0] * 16, 148
  for i, mip in enumerate(mips):
    offsets[i], lengths[i] = cursor, len(mip)
    cursor += len(mip)
  return (b'BLP2' + struct.pack('<I4BII', 1, 2, 0, 0, 1, width, height) +
          struct.pack('<16I', *offsets) + struct.pack('<16I', *lengths) + b''.join(mips))


def repack_atlas(image):
  if image.width != image.height * 2:
    raise ValueError(f'Not an HD 2:1 NPC atlas: {image.size}')
  image = image.convert('RGB').resize((512, 256), Image.Resampling.LANCZOS)
  body = image.crop((0, 0, 256, 256))
  body.paste(image.crop((256, 0, 512, 256)).resize((128, 96), Image.Resampling.LANCZOS), (0, 160))
  return body


def convert_one(args):
  row, directory = args
  try:
    name = f"wxl-npc-{row['id']}.blp"
    image = Image.open(DATA / f"textures/{row['file']}.blp")
    data = dxt1_blp(repack_atlas(image))
    (Path(directory) / name).write_bytes(data)
    return {**row, 'output': name, 'bytes': len(data)}
  except Exception as error:
    return {**row, 'error': str(error)}


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--all', action='store_true')
  args = parser.parse_args()
  if args.all:
    out = ROOT / 'build/npc-appearance-all-v1'
    output = out / 'Textures/BakedNpcTextures'
    output.mkdir(parents=True, exist_ok=True)
    plan = json.loads((DATA / 'npc-plan.json').read_text())
    dbc = bytearray(dbc_path('CreatureDisplayInfoExtra.dbc').read_bytes())
    count, _, stride, _ = struct.unpack_from('<4I', dbc, 4)
    string_start = 20 + count*stride
    done, failed = [], []
    with ProcessPoolExecutor(max_workers=4) as pool:
      for row in pool.map(convert_one, ((r, str(output)) for r in plan['matched']), chunksize=16):
        if 'error' in row:
          failed.append(row)
        else:
          struct.pack_into('<I', dbc, 20+row['row']*stride+80, len(dbc)-string_start)
          dbc.extend(row['output'].encode()+b'\0')
          done.append(row)
        if (len(done)+len(failed)) % 250 == 0:
          print('NPC processed:', len(done)+len(failed), 'failed:', len(failed), flush=True)
    struct.pack_into('<I', dbc, 16, len(dbc)-string_start)
    (out / 'DBFilesClient').mkdir(exist_ok=True)
    (out / 'DBFilesClient/CreatureDisplayInfoExtra.dbc').write_bytes(dbc)
    (out / 'report.json').write_text(json.dumps({'converted': done, 'failed': failed,
      'unmatched': plan['missing'], 'runtimeVerified': False}, indent=2))
    print('NPC done:', len(done), 'failed:', len(failed), 'unmatched:', len(plan['missing']))
    if failed:
      raise ValueError('NPC conversion incomplete; refusing a partial release')
    return
  out = ROOT / 'build/npc-appearance-v1'
  output = out / 'Textures/BakedNpcTextures'
  output.mkdir(parents=True, exist_ok=True)
  plan = json.loads((DATA / 'npc-plan.json').read_text())
  done = []
  for row in plan['matched']:
    # Only the already converted Human Male mesh is installed at this point.
    if (row['race'], row['sex']) != (1, 0):
      continue
    source = DATA / f"textures/{row['file']}.blp"
    if not source.exists():
      continue
    name = row['bakeName']
    if Path(name).name != name or not name.endswith('.blp'):
      raise ValueError('Unsafe baked texture name')
    packed = repack_atlas(Image.open(source))
    (output / name).write_bytes(dxt1_blp(packed))
    done.append(row)
    if row['id'] == 346:
      packed.save(out / 'guard-atlas.png')
  (out / 'report.json').write_text(json.dumps({'converted': done, 'runtimeVerified': False}, indent=2))
  print('NPC bakes prepared:', len(done), 'not deployed')


if __name__ == '__main__':
  main()
