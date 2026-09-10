"""Offline assembly of split Retail skeletons and animation streams.

SKEL array offsets are relative to their owning chunk payload. Split ANIM
offsets refer to AFM2 (model), AFSA (attachments), or AFSB (bones).
The output retains MD21/version 274 for wxl-modern-m2's record normalizers.
"""
from __future__ import annotations

import struct
from .chunks import FormatError, afid_records, read_chunks


def packed_chunk(tag: str, payload: bytes) -> bytes:
  return tag.encode('ascii') + struct.pack('<I', len(payload)) + payload


def array(data: bytes, at: int, stride: int) -> tuple[int, int]:
  if at < 0 or at + 8 > len(data):
    raise FormatError(f'truncated array descriptor at {at}')
  count, offset = struct.unpack_from('<II', data, at)
  if count and (offset > len(data) or count * stride > len(data) - offset):
    raise FormatError(f'array {at}: {count} x {stride} at {offset} outside {len(data)} bytes')
  return count, offset


def assemble(model: bytes, skeleton: bytes, animations: dict[int, bytes]) -> tuple[bytes, dict[int, bytes], dict]:
  chunks = read_chunks(model)
  if not chunks or chunks[0].tag != 'MD21':
    raise FormatError('assembly requires MD21')
  body = bytearray(chunks[0].payload)
  if body[:4] != b'MD20' or len(body) < 0x138:
    raise FormatError('invalid embedded M2 header')
  sk = {chunk.tag: chunk.payload for chunk in read_chunks(skeleton)}
  if 'SKPD' in sk and struct.unpack_from('<I', sk['SKPD'], 8)[0]:
    raise FormatError('parent skeleton composition is not implemented')
  if not all(tag in sk for tag in ('SKS1', 'SKB1', 'SKA1')):
    raise FormatError('skeleton lacks SKS1/SKB1/SKA1')
  if any(struct.unpack_from('<I', body, at)[0] for at in (0x1c, 0x2c, 0xf0)):
    raise FormatError('refusing to replace nonempty model sequences/bones/attachments')

  sequence_count, sequence_offset = array(sk['SKS1'], 8, 64)
  sequences = []
  for i in range(sequence_count):
    at = sequence_offset + i * 64
    anim, sub = struct.unpack_from('<HH', sk['SKS1'], at)
    flags = struct.unpack_from('<I', sk['SKS1'], at + 12)[0]
    alias = struct.unpack_from('<H', sk['SKS1'], at + 62)[0]
    sequences.append((anim, sub, flags, alias))
  records = afid_records(sk.get('AFID', b''))
  by_key = {(r['animationId'], r['subAnimationId']): r['fileDataId'] for r in records}
  flattened = {}
  stream_ranges = {}
  for file_id in set(by_key.values()) - {0}:
    if file_id not in animations:
      raise FormatError(f'missing animation {file_id}')
    parts = read_chunks(animations[file_id])
    if any(part.tag not in ('AFM2', 'AFSA', 'AFSB') for part in parts):
      raise FormatError(f'unknown animation layout for {file_id}')
    streams = {part.tag: part.payload for part in parts}
    if len(streams) != len(parts):
      raise FormatError(f'duplicate animation chunks for {file_id}')
    blob = bytearray()
    ranges = {}
    for tag in ('AFM2', 'AFSA', 'AFSB'):
      if tag in streams:
        blob.extend(b'\0' * (-len(blob) % 16))
        ranges[tag] = (len(blob), len(streams[tag]))
        blob.extend(streams[tag])
    if 'AFM2' not in streams:
      ranges['AFM2'] = (0, 0)
    flattened[file_id] = packed_chunk('AFM2', bytes(blob))
    stream_ranges[file_id] = ranges

  def effective_sequence(index: int) -> tuple:
    seen = set()
    while True:
      if index >= len(sequences) or index in seen:
        raise FormatError('invalid sequence alias chain')
      seen.add(index)
      seq = sequences[index]
      if not seq[2] & 0x40:
        return seq
      index = seq[3]

  relocated = 0
  for tag, fields in (
    ('SKS1', ((0, 0x14, 4), (8, 0x1c, 64), (16, 0x24, 2))),
    ('SKB1', ((0, 0x2c, 88), (8, 0x34, 2))),
    ('SKA1', ((0, 0xf0, 40), (8, 0xf8, 2))),
  ):
    payload = sk[tag]
    body.extend(b'\0' * (-len(body) % 16))
    base = len(body)
    body.extend(payload)
    for source_at, header_at, stride in fields:
      count, offset = array(payload, source_at, stride)
      struct.pack_into('<II', body, header_at, count, base + offset if count else 0)
    if tag == 'SKS1':
      continue
    count, offset = array(payload, 0, 88 if tag == 'SKB1' else 40)
    track_layout = ((16, 12), (36, 8), (56, 12)) if tag == 'SKB1' else ((20, 1),)
    stride = 88 if tag == 'SKB1' else 40
    for i in range(count):
      for track_at, value_size in track_layout:
        at = offset + i * stride + track_at
        global_loop = struct.unpack_from('<h', payload, at + 2)[0]
        for half, element_size in ((4, 4), (12, value_size)):
          slots, entries = array(payload, at + half, 8)
          struct.pack_into('<II', body, base + at + half, slots, base + entries if slots else 0)
          for slot in range(slots):
            count_keys, key_offset = struct.unpack_from('<II', payload, entries + slot * 8)
            if not count_keys:
              struct.pack_into('<II', body, base + entries + slot * 8, 0, 0)
              continue
            inline = global_loop >= 0
            seq = None
            if not inline:
              seq = effective_sequence(slot)
              inline = bool(seq[2] & 0x20)
            if inline:
              origin, limit = base, len(payload)
            else:
              file_id = by_key.get(seq[:2])
              if not file_id or file_id not in stream_ranges:
                raise FormatError(f'no animation for sequence {seq[:2]}')
              ranges = stream_ranges[file_id]
              wanted = 'AFSB' if tag == 'SKB1' else 'AFSA'
              if wanted not in ranges and any(t in ranges for t in ('AFSA', 'AFSB')):
                raise FormatError(f'{file_id} lacks nonempty {wanted} track payload')
              origin, limit = ranges.get(wanted, ranges['AFM2'])
            if key_offset > limit or count_keys * element_size > limit - key_offset:
              raise FormatError(f'{tag} track {i}/{slot} data exceeds its stream')
            struct.pack_into('<I', body, base + entries + slot * 8 + 4, origin + key_offset)
            relocated += 1

  trailing = [packed_chunk(c.tag, c.payload) for c in chunks[1:] if c.tag not in ('SKID', 'AFID', 'BFID')]
  trailing.append(packed_chunk('AFID', sk.get('AFID', b'')))
  # FacePose is intentionally absent: it is not the character's animation rig.
  output = packed_chunk('MD21', bytes(body)) + b''.join(trailing)
  return output, flattened, {
    'sequenceCount': sequence_count, 'relocatedTrackArrays': relocated,
    'externalAnimations': len(flattened), 'parentSkeletonSupported': False,
    'runtimeVerified': False,
  }
