import unittest
from wxl_races.appearance import human_uv, array, repair_human
from wxl_races.chunks import FormatError
import struct


class AppearanceTests(unittest.TestCase):
  def fixture(self):
    body = bytearray(0x140)
    body[:4] = b'MD20'
    struct.pack_into('<I', body, 4, 274)
    struct.pack_into('<II', body, 0x3c, 6, len(body))
    for i in range(6):
      vertex = bytearray(48)
      struct.pack_into('<2f', vertex, 32, 0.25, 0.5)
      body.extend(vertex)
    struct.pack_into('<II', body, 0x50, 2, len(body))
    body.extend(struct.pack('<8I', 1, 0, 0, 0, 6, 0, 0, 0))
    struct.pack_into('<II', body, 0x80, 2, len(body))
    body.extend(struct.pack('<2H', 0, 1))
    def skin(base, reverse=False):
      data = bytearray(64)
      data[:4] = b'SKIN'
      struct.pack_into('<I', data, 44, base)
      struct.pack_into('<II', data, 4, 3, len(data))
      data.extend(struct.pack('<3H', 0, 1, 2))
      struct.pack_into('<II', data, 12, 6, len(data))
      data.extend(struct.pack('<6H', 0, 0, 0, 1, 1, 1))
      struct.pack_into('<II', data, 28, 2, len(data))
      for i in range(2):
        section = bytearray(48)
        struct.pack_into('<6H', section, 0, i, 0, i, 1, i*3, 3)
        data.extend(section)
      struct.pack_into('<II', data, 36, 2, len(data))
      for i in range(2):
        batch = bytearray(24)
        struct.pack_into('<H', batch, 4, i)
        struct.pack_into('<HH', batch, 14, 1, 1-i if reverse else i)
        data.extend(batch)
      return bytes(data)
    return b'MD21' + struct.pack('<I', len(body)) + body, {'base': skin(0), 'lod': skin(3, True)}

  def test_lod_vertices_do_not_alias_base(self):
    from wxl_races.chunks import read_chunks
    model, skins = self.fixture()
    output, _, report = repair_human(model, skins, 'eye.blp')
    body = read_chunks(output)[0].payload
    _, at = array(body, 0x3c, 48)
    self.assertEqual(report['remappedVertices'], 2)
    self.assertEqual(struct.unpack_from('<f', body, at+32)[0], 0.5)
    self.assertEqual(struct.unpack_from('<f', body, at+48+32)[0], 0.25)
    self.assertEqual(struct.unpack_from('<f', body, at+4*48+32)[0], 0.5)

  def test_body_region(self):
    self.assertEqual(human_uv(0.25, 0.5), (0.5, 0.5))

  def test_face_region(self):
    self.assertEqual(human_uv(0.5, 0), (0, 0.625))
    self.assertEqual(human_uv(1, 1), (0.5, 1))
    self.assertEqual(human_uv(0.75, 1 / 3), (0.25, 0.75))

  def test_invalid_uv(self):
    with self.assertRaises(FormatError):
      human_uv(float('nan'), 0)

  def test_clamped_source_edge(self):
    self.assertEqual(human_uv(0.75, -0.01), (0.25, 0.625))

  def test_truncated_array(self):
    with self.assertRaises(FormatError):
      array(struct.pack('<II', 2, 8), 0, 16)
