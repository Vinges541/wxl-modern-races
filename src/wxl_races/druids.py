"""Explicit WotLK druid displays; clone model rows, never replace shared animals."""
from __future__ import annotations

import hashlib
import math
import struct

from .appearance import array
from .chunks import read_chunks, texture_records

BUILD_CONFIG = 'c9fa1a64b0170829cc5c5c98c71025c3'
NAMESPACE = 'WXL/DruidForms'
FORMS = {
    'cat-nightelf': (892, 29405, 29406, 29407, 29408),
    'cat-tauren': (8571, 29409, 29410, 29411, 29412),
    'bear-nightelf': (2281, 29413, 29414, 29415, 29416, 29417),
    'bear-tauren': (2289, 29418, 29419, 29420, 29421),
    'moonkin-nightelf': (15374,), 'moonkin-tauren': (15375,),
    'tree': (864,), 'travel': (918,), 'aquatic': (2428,),
    'flight-nightelf': (20857,), 'flight-tauren': (20872,),
    'swift-flight-nightelf': (21243,), 'swift-flight-tauren': (21244,),
}
DISPLAY_IDS = frozenset(i for ids in FORMS.values() for i in ids)


def bind_textures(model, texture_ids):
    """Bake a display's replaceable creature textures into its private model."""
    chunks = read_chunks(model)
    if chunks[0].tag != 'MD21':
        raise ValueError('Expected MD21 model')
    body = bytearray(chunks[0].payload)
    bindings = []
    for record in texture_records(body):
        kind = record['type']
        if kind == 0:
            if not record['name']:
                raise ValueError('Static texture still has no inline path')
            continue
        if not 11 <= kind <= 13 or len(texture_ids) <= kind - 11 or not texture_ids[kind - 11]:
            raise ValueError(f'Unresolved replaceable material type {kind}')
        file_id = texture_ids[kind - 11]
        name = f'{NAMESPACE}/Textures/{file_id}.blp'
        encoded = name.encode('ascii') + b'\0'
        offset = len(body)
        body.extend(encoded)
        struct.pack_into('<I', body, record['recordOffset'], 0)
        struct.pack_into('<II', body, record['recordOffset'] + 8, len(encoded), offset)
        bindings.append(file_id)
    return b'MD21' + struct.pack('<I', len(body)) + body + model[8 + chunks[0].size:], bindings


def select_sections(data, extra_geosets=None):
    """Apply wow.export's creature selection policy to draw AND shadow batches."""
    if len(data) < 64 or data[:4] != b'SKIN':
        raise ValueError('Expected modern SKIN')
    count, start = array(data, 28, 48)
    sections, mapping, removed = [], {}, []
    for i in range(count):
        row = bytearray(data[start + i*48:start + (i+1)*48])
        gid = struct.unpack_from('<H', row)[0]
        keep = (not 0 < gid < 900 or gid in extra_geosets) if extra_geosets is not None else (
            gid % 10 == 0 or gid % 100 == 1)
        if not keep:
            removed.append(gid)
            continue
        mapping[i] = len(sections)
        # All retained sections are intentional defaults, not client-toggleable.
        struct.pack_into('<H', row, 0, 0)
        sections.append(row)
    if not sections:
        raise ValueError('Geoset selection removed the entire model')
    if not removed and all(struct.unpack_from('<H', data, start+i*48)[0] == 0 for i in range(count)):
        return data, []
    result = bytearray(data)
    arrays = [(28, sections)]
    for at, stride in ((36, 24), (48, 12)):
        n, offset = array(data, at, stride)
        records = []
        for i in range(n):
            row = bytearray(data[offset+i*stride:offset+(i+1)*stride])
            old = struct.unpack_from('<H', row, 4)[0]
            if old >= count:
                raise ValueError('Batch section out of bounds')
            if old in mapping:
                struct.pack_into('<H', row, 4, mapping[old])
                records.append(row)
        arrays.append((at, records))
    for at, records in arrays:
        result.extend(b'\0' * (-len(result) % 16))
        offset = len(result)
        result.extend(b''.join(records))
        struct.pack_into('<II', result, at, len(records), offset)
    return bytes(result), removed


def validate_geometry(model, skin):
    chunks = read_chunks(model)
    if chunks[0].tag != 'MD21' or skin[:4] != b'SKIN':
        raise ValueError('Expected MD21/SKIN')
    body = chunks[0].payload
    nv, vertices = array(body, 0x3c, 48)
    textures = texture_records(body)
    if not nv or any(t['type'] != 0 or not t['name'] or not t['name'].startswith(NAMESPACE+'/') for t in textures):
        raise ValueError('Model has no geometry or unresolved/outside texture bindings')
    for i in range(nv):
        for at, count in ((0,3),(20,7)):
            if not all(math.isfinite(v) for v in struct.unpack_from('<'+'f'*count, body, vertices+i*48+at)):
                raise ValueError('Non-finite vertex data')
    ni, indices = array(skin,4,2)
    nt, triangles = array(skin,12,2)
    ns, sections = array(skin,28,48)
    if nt % 3 or not ns:
        raise ValueError('Invalid triangle/section count')
    base = struct.unpack_from('<I',skin,44)[0] if any(c.tag == 'LDV1' for c in chunks) else 0
    for i in range(ni):
        if base + struct.unpack_from('<H',skin,indices+i*2)[0] >= nv:
            raise ValueError('Skin vertex outside M2 vertex buffer')
    for i in range(nt):
        if struct.unpack_from('<H',skin,triangles+i*2)[0] >= ni:
            raise ValueError('Triangle outside skin index buffer')
    for i in range(ns):
        at = sections+i*48
        level = struct.unpack_from('<H',skin,at+2)[0]
        start, count = struct.unpack_from('<HH',skin,at+8)
        if start + (level << 16) + count > nt:
            raise ValueError('Section triangle range outside skin')
    for header, stride in ((36,24),(48,12)):
        n, at = array(skin,header,stride)
        for i in range(n):
            if struct.unpack_from('<H',skin,at+i*stride+4)[0] >= ns:
                raise ValueError('Draw/shadow batch references a removed section')
    return {'vertices':nv, 'skinVertices':ni, 'triangles':nt//3, 'sections':ns}


class DBC:
    def __init__(self, data: bytes, fields: int, string_columns=()):
        if len(data) < 20 or data[:4] != b'WDBC':
            raise ValueError('Expected WDBC')
        count, columns, stride, size = struct.unpack_from('<4I', data, 4)
        end = 20 + count * stride
        if (columns != fields or stride != fields * 4 or not 0 < count < 1000000
                or size < 1 or end + size != len(data) or data[end] != 0 or data[-1] != 0):
            raise ValueError('Unsupported DBC layout')
        self.fields = fields
        self.rows = [list(r) for r in struct.iter_unpack('<' + 'I' * fields, data[20:end])]
        self.strings = bytearray(data[end:])
        self.by_id = {r[0]: r for r in self.rows}
        if len(self.by_id) != count:
            raise ValueError('Duplicate DBC IDs')
        for r in self.rows:
            for col in string_columns:
                self.string(r[col])

    def string(self, offset):
        if not 0 <= offset < len(self.strings):
            raise ValueError('String offset out of bounds')
        return self.strings[offset:self.strings.index(0, offset)].decode('utf-8')

    def add_string(self, value):
        if not isinstance(value, str) or '\0' in value:
            raise ValueError('Invalid string')
        offset = len(self.strings)
        self.strings.extend(value.encode('utf-8') + b'\0')
        return offset

    def encode(self):
        return (b'WDBC' + struct.pack('<4I', len(self.rows), self.fields, self.fields * 4, len(self.strings))
                + b''.join(struct.pack('<' + 'I' * self.fields, *r) for r in self.rows) + self.strings)


def make_plan(display_data, model_data, retail_displays, retail_models, build):
    if build.get('BuildConfig') != BUILD_CONFIG or build.get('Product') != 'wow':
        raise ValueError('Expected pinned Retail build')
    displays = DBC(display_data, 16, (6, 7, 8, 9))
    models = DBC(model_data, 28, (2,))
    def index(rows):
        result = {r['ID']: r for r in rows}
        if len(result) != len(rows):
            raise ValueError('Duplicate Retail IDs')
        return result
    rd, rm = index(retail_displays), index(retail_models)
    result = []
    for form, ids in FORMS.items():
        for display_id in ids:
            old = displays.by_id[display_id]
            original = models.by_id[old[1]]
            new = rd[display_id]
            model = rm[new['ModelID']]
            file_id = model['FileDataID']
            textures = new['TextureVariationFileDataID']
            if (type(file_id) is not int or file_id <= 0 or len(textures) < 3
                    or any(type(i) is not int or i < 0 for i in textures)):
                raise ValueError('Invalid Retail model/texture IDs')
            if new.get('ExtendedDisplayInfoID') or new.get('ConditionalCreatureModelID'):
                raise ValueError('Customizable/conditional display requires a separate adapter')
            result.append({'form': form, 'displayId': display_id, 'fileDataId': file_id,
                           'textureFileDataIds': textures, 'legacyModelId': old[1],
                           'legacyPath': models.string(original[2]),
                           'modelGeosetDataId': model.get('CreatureGeosetDataID', 0),
                           'modelPath': f'{NAMESPACE}/Models/{display_id}/Form.m2'})
    return {'schemaVersion': 1, 'kind': 'wxl-druid-forms-plan', 'build': build,
            'sourceHashes': {'CreatureDisplayInfo.dbc': hashlib.sha256(display_data).hexdigest(),
                             'CreatureModelData.dbc': hashlib.sha256(model_data).hexdigest()},
            'displays': result}


def patch_tables(display_data, model_data, plan):
    if (plan.get('kind') != 'wxl-druid-forms-plan' or plan.get('schemaVersion') != 1
            or plan.get('build', {}).get('BuildConfig') != BUILD_CONFIG):
        raise ValueError('Unknown druid plan')
    entries = plan['displays']
    if len(entries) != len(DISPLAY_IDS) or {r['displayId'] for r in entries} != DISPLAY_IDS:
        raise ValueError('Incomplete/duplicate/unexpected druid display set')
    for name, data in [('CreatureDisplayInfo.dbc', display_data), ('CreatureModelData.dbc', model_data)]:
        if hashlib.sha256(data).hexdigest() != plan['sourceHashes'][name]:
            raise ValueError('Original DBC changed since planning')
    displays, models = DBC(display_data, 16, (6, 7, 8, 9)), DBC(model_data, 28, (2,))
    next_id = max(models.by_id) + 1
    for item in sorted(entries, key=lambda r: r['displayId']):
        display_id = item['displayId']
        path = f'{NAMESPACE}/Models/{display_id}/Form.m2'
        if item['modelPath'] != path or displays.by_id[display_id][1] != item['legacyModelId']:
            raise ValueError('Noncanonical druid destination or source model')
        original = models.by_id[item['legacyModelId']]
        row = original.copy()
        row[0], row[2] = next_id, models.add_string(path.replace('/', '\\'))
        models.rows.append(row)
        displays.by_id[display_id][1] = next_id
        next_id += 1
    # Original models, scales, collision data and unrelated display rows are intact.
    return {'CreatureDisplayInfo.dbc': displays.encode(), 'CreatureModelData.dbc': models.encode()}
