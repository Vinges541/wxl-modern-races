import struct
import unittest
from wxl_races.chunks import FormatError, read_chunks
from wxl_races.skeleton import assemble, packed_chunk


def fixture():
  model = bytearray(0x138)
  model[:4] = b'MD20'
  struct.pack_into('<I', model, 4, 274)
  sequences = bytearray(160)
  struct.pack_into('<II', sequences, 8, 2, 32)
  struct.pack_into('<HHI', sequences, 32, 0, 0, 1000)
  struct.pack_into('<I', sequences, 44, 0x20)
  struct.pack_into('<HHI', sequences, 96, 66, 0, 1000)
  bones = bytearray(156)
  struct.pack_into('<II', bones, 0, 1, 16)
  # One bone, translation only. Other tracks are empty global-loop tracks.
  struct.pack_into('<h', bones, 16 + 16 + 2, -1)
  struct.pack_into('<II', bones, 16 + 16 + 4, 2, 104)
  struct.pack_into('<II', bones, 16 + 16 + 12, 2, 120)
  struct.pack_into('<IIII', bones, 104, 1, 136, 1, 0)
  struct.pack_into('<IIII', bones, 120, 1, 140, 1, 4)
  struct.pack_into('<Ifff', bones, 136, 123, 1, 2, 3)
  skel = b''.join([
    packed_chunk('SKS1', sequences), packed_chunk('SKB1', bones),
    packed_chunk('SKA1', bytes(16)), packed_chunk('AFID', struct.pack('<HHI', 66, 0, 999)),
  ])
  anim = packed_chunk('AFM2', b'event') + packed_chunk('AFSB', struct.pack('<Ifff', 456, 4, 5, 6))
  return packed_chunk('MD21', model) + packed_chunk('SKID', struct.pack('<I', 123)), skel, {999: anim}


class SkeletonTests(unittest.TestCase):
  def test_preserves_inline_and_external_keys(self):
    model, anims, _ = assemble(*fixture())
    chunks = read_chunks(model)
    self.assertNotIn('SKID', [c.tag for c in chunks])
    body = chunks[0].payload
    _, bone_offset = struct.unpack_from('<II', body, 0x2c)
    _, slots = struct.unpack_from('<II', body, bone_offset + 20)
    _, inline_offset = struct.unpack_from('<II', body, slots)
    _, external_offset = struct.unpack_from('<II', body, slots + 8)
    self.assertEqual(struct.unpack_from('<I', body, inline_offset)[0], 123)
    flattened = read_chunks(anims[999])[0].payload
    self.assertEqual(flattened[:5], b'event')
    self.assertEqual(struct.unpack_from('<I', flattened, external_offset)[0], 456)

  def test_missing_animation_rejected(self):
    model, skel, _ = fixture()
    with self.assertRaises(FormatError):
      assemble(model, skel, {})

  def test_truncated_bone_stream_rejected(self):
    model, skel, _ = fixture()
    with self.assertRaises(FormatError):
      assemble(model, skel, {999: packed_chunk('AFM2', b'event') + packed_chunk('AFSB', b'bad')})
