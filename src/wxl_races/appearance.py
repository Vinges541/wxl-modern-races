"""Bounded Human HD appearance conversion; never infer geometry from file names.

The 2048x1024 Retail sheet has the ordinary body in its left square and
the head in its right square. The Wrath sheet's head occupies the contiguous
face-lower/face-upper rectangle (0,640,512,384) of a 1024 square.
Only vertices actually bound to the character-body material may be remapped.
"""
import struct
import math
from .chunks import FormatError, read_chunks, texture_records


def human_uv(u, v):
  if not (math.isfinite(u) and math.isfinite(v)):
    raise FormatError(f'non-finite body UV: {(u, v)}')
  # The body texture has flags=0 (clamp). Preserve its edge sampling before
  # moving the head into an interior rectangle of the destination sheet.
  u, v = min(1, max(0, u)), min(1, max(0, v))
  if u < 0.5:
    return u * 2, v
  return u - 0.5, 0.625 + v * 0.375


def array(data, at, stride):
  count, offset = struct.unpack_from('<II', data, at)
  if count and (offset < 4 or offset + count * stride > len(data)):
    raise FormatError(f'array out of bounds at {at}')
  return count, offset


def repair_human(model, skins, eye_path, *, default_geosets=None, static_bindings=None):
  chunks = read_chunks(model)
  if chunks[0].tag != 'MD21':
    raise FormatError('expected assembled MD21')
  body = bytearray(chunks[0].payload)
  vertex_count, vertices = array(body, 0x3c, 48)
  lookup_count, lookup = array(body, 0x80, 2)
  textures = texture_records(body)
  body_vertices, other_vertices = set(), set()
  output = {}
  stats = {'removedGeosets': {}, 'defaultGeosets': {}, 'remappedVertices': 0, 'runtimeVerified': False}
  # Explicit Human Male default geometry; all other post-Wrath groups are
  # removed, not left permanently visible outside the client's 0..2000 hide.
  defaults = set(default_geosets) if default_geosets is not None else {2001, 2201, 3202, 3301, 5101}
  bindings = {19: eye_path, **(static_bindings or {})}
  for name, data in skins.items():
    skin = bytearray(data)
    if skin[:4] != b'SKIN':
      raise FormatError('expected SKIN')
    index_count, indices = array(skin, 4, 2)
    triangle_count, triangles = array(skin, 12, 2)
    section_count, sections = array(skin, 28, 48)
    batch_count, batches = array(skin, 36, 24)
    # LDV1-era skins use the former bone-count field as the base into the
    # model's concatenated LOD vertex arrays. Profile 0 has base zero.
    vertex_base = struct.unpack_from('<I', skin, 44)[0]
    kept, section_map, removed, default_ids = [], {}, [], []
    for i in range(section_count):
      section = bytearray(skin[sections + i * 48:sections + (i + 1) * 48])
      gid = struct.unpack_from('<H', section)[0]
      if gid >= 2000 and gid not in defaults:
        removed.append(gid)
        continue
      if gid in defaults:
        struct.pack_into('<H', section, 0, 0)
        default_ids.append(gid)
      section_map[i] = len(kept)
      kept.append(section)
    new_batches = []
    for i in range(batch_count):
      batch = bytearray(skin[batches + i * 24:batches + (i + 1) * 24])
      section_id = struct.unpack_from('<H', batch, 4)[0]
      if section_id >= section_count:
        raise FormatError('invalid batch section')
      if section_id not in section_map:
        continue
      texture_count, texture_start = struct.unpack_from('<HH', batch, 14)
      if texture_start + texture_count > lookup_count:
        raise FormatError('invalid texture combo')
      types = []
      for j in range(texture_count):
        texture_id = struct.unpack_from('<H', body, lookup + 2 * (texture_start + j))[0]
        if texture_id >= len(textures):
          raise FormatError('invalid texture index')
        types.append(textures[texture_id]['type'])
      if any(t > 14 and t not in bindings for t in types):
        if types[0] != 2:
          raise FormatError(f'unresolved modern material types {types}')
        # Retail cape passes add normal/specular/emissive bindings after the
        # dynamic cape diffuse. Wrath only supplies that first binding.
        struct.pack_into('<H', batch, 2, 0)
        struct.pack_into('<H', batch, 14, 1)
        types = types[:1]
      level = struct.unpack_from('<H', skin, sections + section_id * 48 + 2)[0]
      start, count = struct.unpack_from('<HH', skin, sections + section_id * 48 + 8)
      start += level << 16
      if start + count > triangle_count:
        raise FormatError('section triangles exceed skin')
      target = body_vertices if 1 in types else other_vertices
      for j in range(start, start + count):
        index = struct.unpack_from('<H', skin, triangles + j * 2)[0]
        if index >= index_count:
          raise FormatError('triangle exceeds skin vertex lookup')
        vertex = vertex_base + struct.unpack_from('<H', skin, indices + index * 2)[0]
        if vertex >= vertex_count:
          raise FormatError('skin vertex exceeds model')
        target.add(vertex)
      struct.pack_into('<H', batch, 4, section_map[section_id])
      new_batches.append(batch)
    for at, records in [(28, kept), (36, new_batches)]:
      skin.extend(b'\0' * (-len(skin) % 16))
      offset = len(skin)
      skin.extend(b''.join(records))
      struct.pack_into('<II', skin, at, len(records), offset)
    output[name] = bytes(skin)
    stats['removedGeosets'][name] = removed
    stats['defaultGeosets'][name] = default_ids
  if body_vertices & other_vertices:
    raise FormatError('body and other materials share vertices: split required')
  for vertex in body_vertices:
    offset = vertices + vertex * 48 + 32
    struct.pack_into('<2f', body, offset, *human_uv(*struct.unpack_from('<2f', body, offset)))
  stats['remappedVertices'] = len(body_vertices)
  for texture in textures:
    if texture['type'] in bindings:
      encoded = bindings[texture['type']].encode() + b'\0'
      offset = len(body)
      body.extend(encoded)
      struct.pack_into('<I', body, texture['recordOffset'], 0)
      struct.pack_into('<II', body, texture['recordOffset'] + 8, len(encoded), offset)
  result = b''.join(c.tag.encode() + struct.pack('<I', len(body) if i == 0 else c.size) +
                    (bytes(body) if i == 0 else c.payload) for i, c in enumerate(chunks))
  return result, output, stats
