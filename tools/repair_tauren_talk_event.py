"""Relocate a valid external timestamp away from offset zero (Wrath null sentinel)."""
import hashlib
import json
import struct
import sys
from pathlib import Path

from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.chunks import read_chunks


def repair(model, animation):
  chunks = read_chunks(model)
  streams = read_chunks(animation)
  assert chunks[0].tag == 'MD21' and len(streams) == 1 and streams[0].tag == 'AFM2'
  body = bytearray(chunks[0].payload)
  count, sequences = struct.unpack_from('<II', body, 0x1c)
  assert count > 127
  seq = struct.unpack_from('<HHII', body, sequences + 127*64)
  assert seq[:2] == (60, 0) and not seq[3] & (0x20 | 0x40)
  count, events = struct.unpack_from('<II', body, 0x100)
  assert count > 16
  event = events + 16*36
  assert body[event:event+4] == b'$BTH'
  assert struct.unpack_from('<h', body, event+26)[0] == -1
  slots, entries = struct.unpack_from('<II', body, event+28)
  assert slots > 127
  descriptor = entries + 127*8
  assert struct.unpack_from('<II', body, descriptor) == (1, 0)
  payload = streams[0].payload
  timestamp = struct.unpack_from('<I', payload)[0]
  assert timestamp == 2067 and timestamp <= seq[2]
  # Append an identical timestamp; existing bone/attachment offsets remain valid.
  struct.pack_into('<I', body, descriptor+4, len(payload))
  new_model = b'MD21' + struct.pack('<I', len(body)) + body + model[8+len(body):]
  new_animation = b'AFM2' + struct.pack('<I', len(payload)+4) + payload + payload[:4]
  assert new_animation[8:-4] == animation[8:]
  changed = {i for i,(a,b) in enumerate(zip(model,new_model)) if a != b}
  assert changed <= set(range(8+descriptor+4, 8+descriptor+8))
  assert struct.unpack_from('<I', new_animation, 8+len(payload))[0] == timestamp
  return new_model, new_animation


def main():
  client = client_path()
  prefix = Path('Data/Patch-ModernRaces-HD.MPQ/Character/Tauren/Male')
  names = ['TaurenMale.m2', 'TaurenMale0060-00.anim']
  inputs = [(client/prefix/name).read_bytes() for name in names]
  outputs = repair(*inputs)
  out = ROOT / 'build/tauren-talk-event-v1'
  manifest = []
  for name, old, new in zip(names, inputs, outputs):
    target = out/prefix/name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(new)
    manifest.append({'path': str(prefix/name).replace('/', '\\'), 'before': hashlib.sha256(old).hexdigest(), 'sha256': hashlib.sha256(new).hexdigest(), 'size': len(new)})
  (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
  print('Prepared two-file event fix; timestamp2067 preserved, existing animation bytes unchanged.')


if __name__ == '__main__':
  main()
