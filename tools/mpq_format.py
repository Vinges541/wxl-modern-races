"""Independent, deliberately narrow reader for our legacy zlib MPQ profile.

Adapted from wxl-equipment-textures (GPL-3.0-or-later).
Hash/table algorithms follow StormLib's documented legacy MPQ format. This is
not a general MPQ reader: encrypted files, delta patches, headers newer than v2
and extended offsets are refused. The 4 GiB bound is this profile's choice.
"""
import struct
import zlib

MASK = 0xffffffff
LIMIT = 4 * 1024**3
EXISTS, COMPRESS = 0x80000000, 0x200


def crypt_table():
    table = [0] * 0x500
    seed = 0x100001
    for low in range(256):
        for high in range(5):
            seed = (seed * 125 + 3) % 0x2aaaab
            a = (seed & 0xffff) << 16
            seed = (seed * 125 + 3) % 0x2aaaab
            table[high * 256 + low] = a | (seed & 0xffff)
    return table


CRYPT = crypt_table()


def hash_name(name, kind):
    a, b = 0x7fed7fed, 0xeeeeeeee
    for ch in name.replace('/', '\\').upper().encode('ascii'):
        a = (CRYPT[kind * 256 + ch] ^ (a + b)) & MASK
        b = (ch + a + b + (b << 5) + 3) & MASK
    return a


def decrypt(data, key):
    result = bytearray()
    seed = 0xeeeeeeee
    for (word,) in struct.iter_unpack('<I', data):
        seed = (seed + CRYPT[0x400 + (key & 255)]) & MASK
        value = word ^ ((key + seed) & MASK)
        key = (((~key << 21) + 0x11111111) | (key >> 11)) & MASK
        seed = (value + seed + (seed << 5) + 3) & MASK
        result.extend(struct.pack('<I', value))
    return result


class LegacyMPQ:
    def __init__(self, path):
        self.file = path.open('rb')
        try:
            self.size = path.stat().st_size
            magic, header, total, version, shift, hp, bp, hc, bc = struct.unpack('<4sIIHHIIII', self.file.read(32))
            if (magic, header, version, shift) != (b'MPQ\x1a', 44, 1, 3):
                raise ValueError('Expected MPQ v2 with 4096-byte sectors')
            if struct.unpack('<QHH', self.file.read(12)) != (0, 0, 0):
                raise ValueError('Extended offsets are outside this packing profile')
            if total != self.size or not 44 <= total < LIMIT or not 4 <= hc <= 65536 or hc & (hc - 1) or not 1 <= bc <= 60001:
                raise ValueError('Archive size/table limit exceeded')
            if not (44 <= hp and hp + hc * 16 <= bp and bp + bc * 16 == total):
                raise ValueError('Invalid table layout')
            self.file.seek(hp)
            self.hashes = list(struct.iter_unpack('<IIHHI', decrypt(self.file.read(hc * 16), hash_name('(hash table)', 3))))
            self.file.seek(bp)
            self.blocks = list(struct.iter_unpack('<IIII', decrypt(self.file.read(bc * 16), hash_name('(block table)', 3))))
            active = [h for h in self.hashes if h[4] != MASK]
            if len(active) != bc or {h[4] for h in active} != set(range(bc)) or any(h[2:4] != (0, 0) for h in active):
                raise ValueError('Non-neutral, duplicate or deleted hash entry')
            ends = []
            for pos, stored, size, flags in self.blocks:
                if flags != EXISTS | COMPRESS or not 0 < size <= 64 * 1024**2 or not 44 <= pos < pos + stored <= hp:
                    raise ValueError('Unsupported block or flags')
                ends.append((pos, pos + stored))
            ordered = sorted(ends)
            if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
                raise ValueError('Overlapping data blocks')
            self.header = dict(formatVersion=version, sectorBytes=4096, hashEntries=hc, blockEntries=bc)
        except BaseException:
            self.file.close()
            raise

    def close(self):
        self.file.close()

    def index(self, name):
        start = hash_name(name, 0) & (len(self.hashes) - 1)
        a, b = hash_name(name, 1), hash_name(name, 2)
        for i in range(len(self.hashes)):
            row = self.hashes[(start + i) & (len(self.hashes) - 1)]
            if row[4] == MASK:
                break
            if row[:2] == (a, b):
                return row[4]
        raise FileNotFoundError(name)

    def read(self, name):
        pos, stored, size, _ = self.blocks[self.index(name)]
        count = (size + 4095) // 4096
        self.file.seek(pos)
        data = self.file.read(stored)
        offsets = struct.unpack_from('<' + 'I' * (count + 1), data)
        if offsets[0] != (count + 1) * 4 or offsets[-1] != stored:
            raise ValueError('Invalid sector offset table')
        output = bytearray()
        for i, (lo, hi) in enumerate(zip(offsets, offsets[1:])):
            expected = min(4096, size - i * 4096)
            if not offsets[0] <= lo < hi <= stored:
                raise ValueError('Invalid sector bounds')
            chunk = data[lo:hi]
            if len(chunk) < expected:
                if chunk[0] != 2:
                    raise ValueError('Non-zlib compression mask')
                decoder = zlib.decompressobj()
                chunk = decoder.decompress(chunk[1:], expected + 1)
                if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise ValueError('Invalid zlib stream')
            if len(chunk) != expected:
                raise ValueError('Incorrect sector size')
            output.extend(chunk)
        return bytes(output)
