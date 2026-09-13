"""Shared names and structural validation for locale-independent appearance tables."""
import struct

NAMESPACE = 'WXL/ModernRaces/DBFilesClient'
TABLES = {'CharSections.dbc': (10, (4, 5, 6)),
          'CreatureDisplayInfoExtra.dbc': (21, (20,))}


def validate(name, data):
    fields, strings = TABLES[name]
    if len(data) < 20 or data[:4] != b'WDBC':
        raise ValueError('Expected WDBC appearance table: ' + name)
    count, columns, stride, size = struct.unpack_from('<4I', data, 4)
    start = 20 + count * stride
    if (columns != fields or stride != fields * 4 or not 0 < count <= 1000000
            or size < 1 or len(data) != start + size or data[start] != 0 or data[-1] != 0):
        raise ValueError('Unsupported appearance table layout: ' + name)
    for row in range(count):
        for column in strings:
            offset = struct.unpack_from('<I', data, 20 + row * stride + column * 4)[0]
            if offset >= size:
                raise ValueError('Appearance string offset outside table: ' + name)
    return data
