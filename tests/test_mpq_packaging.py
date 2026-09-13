import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import pack_mpq as pack
from mpq_format import LegacyMPQ, hash_name, decrypt, CRYPT, MASK


class SafetyTests(unittest.TestCase):
    def row(self, name):
        return {'path': name, 'size': 1, 'sha256': hashlib.sha256(b'a').hexdigest()}

    def test_case_and_hash_collision(self):
        with self.assertRaises(ValueError):
            pack.check_names([self.row('Character/a.blp'), self.row('character/A.BLP')])
        with patch.object(pack, 'hash_name', return_value=1), self.assertRaises(ValueError):
            pack.check_names([self.row('Character/a.blp'), self.row('Character/b.blp')])

    def test_unsafe_names(self):
        for name in ('../x', '/x', 'x//y', 'x/./y', 'C:x', 'x\\y', '(listfile)', 'x.', 'x/é'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pack.asset_name(name)
        self.assertEqual(pack.asset_name('Character/Male/Model.m2'), 'Character/Male/Model.m2')

    def test_classic_hash_case_and_slash(self):
        for kind in range(4):
            self.assertEqual(hash_name('Char/FOO.blp', kind), hash_name('CHAR\\foo.BLP', kind))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root/'actual').mkdir()
            (root/'link').symlink_to(root/'actual', target_is_directory=True)
            with self.assertRaises(ValueError):
                pack.no_links(root/'link'/'file')

    def test_manifest_destination_traversal(self):
        report = {'schemaVersion': 1, 'profile': pack.PROFILE, 'sourceBytes': 1,
                  'archives': [{'name': '../Wow.exe', 'size': 100, 'sha256': '0'*64,
                                'files': [self.row('Character/a')]}]}
        with self.assertRaises(ValueError):
            pack.validate_manifest(report)

    def test_reject_interleaving_other_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); (root/'Data').mkdir()
            (root/'Data'/pack.PATCH).mkdir()
            (root/'Data'/'Patch-ModernRaces-HD-0999.MPQ').write_bytes(b'peer')
            with self.assertRaises(ValueError):
                pack.check_destinations(root, [pack.archive_name(0)])


@unittest.skipUnless(os.environ.get('WXL_MPQ_STORMLIB'), 'set WXL_MPQ_STORMLIB for synthetic native-library tests')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.client = self.root/'client'; self.source = self.client/'Data'/pack.PATCH
        self.source.mkdir(parents=True)
        self.work = self.root/'pack'; self.report = self.root/'result.json'
        self.lib = Path(os.environ['WXL_MPQ_STORMLIB']).resolve()
        self.fake_loader = patch.object(pack, 'loader', return_value={'synthetic': True})
        self.fake_loader.start(); self.addCleanup(self.fake_loader.stop)
        self.files = {'Character/Test.m2': b'MD20'+b'geometry'*2000,
                      'Textures/Face.blp': bytes(range(256))*40,
                      'bundle-report.json': b'{"synthetic":true}'}
        for name, data in self.files.items():
            target = self.source/name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def build(self):
        return pack.build(self.client, self.work, self.lib)

    def test_roundtrip_profile_and_lossless_install(self):
        result = self.build(); self.assertEqual(result['files'], 3)
        first = self.work/pack.archive_name(0)
        with first.open('rb') as stream:
            self.assertEqual(struct.unpack_from('<H', stream.read(16), 12)[0], 1)
        reader = LegacyMPQ(first)
        try:
            for name, data in self.files.items():
                self.assertEqual(reader.read(name.swapcase()), data)
        finally:
            reader.close()
        self.assertEqual(pack.install(self.client, self.work, self.lib)['state'], 'preview')
        self.assertTrue(self.source.is_dir())
        with patch.object(pack, 'require_wow_closed') as stopped:
            result = pack.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertGreaterEqual(stopped.call_count, 3)
        self.assertEqual(result['state'], 'installed-verified')
        self.assertFalse(self.source.exists()); self.assertFalse(self.work.exists())
        self.assertFalse((self.client/'DisabledPatches').exists())
        manifest = json.loads(self.report.with_name('result.manifest.json').read_text())
        self.assertEqual(pack.verify(self.client/'Data', self.lib, manifest)['files'], 3)

    def test_shards_cover_each_file_once(self):
        with patch.object(pack, 'MAX_FILES', 2):
            result = self.build()
            self.assertEqual(len(result['archives']), 2)
            manifest = json.loads((self.work/'manifest.json').read_text())
            self.assertEqual(pack.verify(self.work, self.lib, manifest)['files'], 3)

    def test_changed_source_not_deleted(self):
        self.build(); (self.source/'Character/Test.m2').write_bytes(b'new edit')
        with self.assertRaises(ValueError):
            pack.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertEqual((self.source/'Character/Test.m2').read_bytes(), b'new edit')

    def test_archive_corruption_keeps_source(self):
        self.build(); archive = self.work/pack.archive_name(0)
        with archive.open('r+b') as stream:
            stream.seek(60); stream.write(b'corrupt')
        with patch.object(pack, 'require_wow_closed'), self.assertRaises(ValueError):
            pack.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertTrue(self.source.is_dir())

    def test_process_check_blocks_mutation(self):
        self.build()
        with patch.object(pack, 'require_wow_closed', side_effect=RuntimeError('running')):
            with self.assertRaises(RuntimeError):
                pack.install(self.client, self.work, self.lib, True, True, self.report)
        self.assertTrue(self.source.is_dir())
        self.assertFalse((self.client/'Data'/pack.archive_name(0)).exists())

    def test_needs_explicit_discard(self):
        self.build()
        with self.assertRaises(ValueError):
            pack.install(self.client, self.work, self.lib, apply=True, report=self.report)
        self.assertTrue(self.source.is_dir())

    def test_unsigned_offsets_above_two_gib(self):
        # Sparse synthetic v2 archive: one resource and both tables above 3 GiB.
        small, large = self.root/'small.MPQ', self.root/'large.MPQ'
        storm = pack.Storm(self.lib)
        with patch.object(pack, 'MAX_FILES', 2):
            handle = storm.create(small)
            storm.add(handle, 'Character/Test.m2', b'MD20'+b'x'*10000)
            storm.close(handle)
        data = small.read_bytes()
        fields = list(struct.unpack_from('<4sIIHHIIII', data))
        hp, bp, hc, bc = fields[5:]
        blocks = list(struct.iter_unpack('<4I', decrypt(data[bp:bp+bc*16], hash_name('(block table)', 3))))
        shift = 3 * 1024**3
        modified = b''.join(struct.pack('<4I', pos+shift, stored, size, flags) for pos, stored, size, flags in blocks)
        key, seed, encrypted = hash_name('(block table)', 3), 0xeeeeeeee, bytearray()
        for (value,) in struct.iter_unpack('<I', modified):
            seed = (seed+CRYPT[0x400+(key&255)]) & MASK
            encrypted.extend(struct.pack('<I', value^((key+seed)&MASK)))
            key = (((~key<<21)+0x11111111)|(key>>11)) & MASK
            seed = (value+seed+(seed<<5)+3)&MASK
        fields[2] += shift; fields[5] += shift; fields[6] += shift
        with large.open('wb') as stream:
            stream.write(struct.pack('<4sIIHHIIII', *fields)+data[32:44])
            stream.seek(44+shift); stream.write(data[44:bp]); stream.write(encrypted)
        reader, native = LegacyMPQ(large), storm.open(large)
        try:
            self.assertEqual(reader.read('Character/Test.m2'), storm.read(native, 'CHARACTER/TEST.M2'))
        finally:
            reader.close(); storm.close(native)


if __name__ == '__main__':
    unittest.main()
