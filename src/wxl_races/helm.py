"""Align legacy helmet meshes to HD characters without altering their skeletons."""
import math
import struct
from .chunks import FormatError, read_chunks
from .appearance import array


def helmet_anchor(model):
  body = read_chunks(model)[0].payload if model[:4] == b'MD21' else model
  if body[:4] != b'MD20':
    raise FormatError('Unsupported model header')
  count, offset = array(body, 0xf0, 40)
  entries = [offset + i*40 for i in range(count) if struct.unpack_from('<I', body, offset+i*40)[0] == 11]
  if len(entries) != 1:
    raise FormatError('Expected exactly one helmet attachment')
  at = entries[0] + 8
  point = struct.unpack_from('<3f', body, at)
  if not all(math.isfinite(v) and abs(v) < 20 for v in point):
    raise FormatError('Invalid helmet anchor')
  return at, point


def head_parent_pivot(model):
  body = read_chunks(model)[0].payload if model[:4] == b'MD21' else model
  at, _ = helmet_anchor(model)
  bone = struct.unpack_from('<H', body, at-4)[0]
  count, offset = array(body, 0x2c, 88)
  if bone >= count:
    raise FormatError('Helmet bone outside skeleton')
  parent = struct.unpack_from('<h', body, offset+bone*88+8)[0]
  if parent < 0 or parent >= count:
    raise FormatError('Invalid helmet parent bone')
  return struct.unpack_from('<3f', body, offset+parent*88+76)


def adapt_helmet_anchor(modern, legacy, *, preserve_parent_offset=False):
  chunks = read_chunks(modern)
  if chunks[0].tag != 'MD21':
    raise FormatError('Expected converted MD21 model')
  at, before = helmet_anchor(modern)
  _, target = helmet_anchor(legacy)
  if preserve_parent_offset:
    # Tauren and Gnome bind poses move the head joint substantially. Preserve
    # the legacy helmet's offset from that joint, not its absolute world Z.
    old_pivot, new_pivot = head_parent_pivot(legacy), head_parent_pivot(modern)
    target = tuple(t+n-o for t, n, o in zip(target, new_pivot, old_pivot))
  body = bytearray(chunks[0].payload)
  struct.pack_into('<3f', body, at, *target)
  converted = b''.join(c.tag.encode() + struct.pack('<I', c.size) +
                       (bytes(body) if i == 0 else c.payload) for i, c in enumerate(chunks))
  return converted, {'attachment': 11, 'before': before, 'after': target,
                     'boneAndAnimationDataUnchanged': True, 'runtimeVerified': False,
                     'preserveParentOffset': preserve_parent_offset}
