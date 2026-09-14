import copy
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from wxl_races.druids import BUILD_CONFIG, DBC, DISPLAY_IDS, make_plan, patch_tables, bind_textures, select_sections
from wxl_races.chunks import read_chunks, texture_records
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import druid_forms as installer


def encode(rows, fields, strings=b'\0'):
    return b'WDBC' + struct.pack('<4I', len(rows), fields, fields*4, len(strings)) + b''.join(
        struct.pack('<'+'I'*fields, *row) for row in rows) + strings


class DruidFormsTests(unittest.TestCase):
    def setUp(self):
        self.displays = []
        self.retail = []
        for identifier in sorted(DISPLAY_IDS | {100, 50000}):
            row = [0]*16
            row[0:2] = [identifier, 25]
            row[4] = 0x3f800000
            self.displays.append(row)
            self.retail.append({'ID': identifier, 'ModelID': 30, 'TextureVariationFileDataID': [300, 0, 0, 0]})
        model = [0]*28
        model[0:4] = [25, 128, 1, 0x3f800000]
        self.a = encode(self.displays, 16)
        self.b = encode([model], 28, b'\0Creature\\Tiger\\Tiger.mdx\0')
        self.models = [{'ID':30, 'FileDataID':200, 'CreatureGeosetDataID':0}]
        self.build = {'Product':'wow', 'BuildConfig':BUILD_CONFIG}

    def plan(self):
        return make_plan(self.a, self.b, self.retail, self.models, self.build)

    def test_only_explicit_display_model_references_change(self):
        result = patch_tables(self.a, self.b, self.plan())
        a, b = DBC(result['CreatureDisplayInfo.dbc'],16), DBC(result['CreatureModelData.dbc'],28)
        self.assertEqual(b.rows[0], DBC(self.b,28).rows[0])
        self.assertEqual(len(b.rows), len(DISPLAY_IDS)+1)
        for old in self.displays:
            new = a.by_id[old[0]]
            if old[0] not in DISPLAY_IDS:
                self.assertEqual(old,new)
            else:
                self.assertNotEqual(new[1],old[1])
                self.assertEqual(new[:1]+new[2:],old[:1]+old[2:])
                model = b.by_id[new[1]]
                self.assertEqual(model[1],128)
                self.assertEqual(model[3:], b.rows[0][3:])
                self.assertEqual(b.string(model[2]), f'WXL\\DruidForms\\Models\\{old[0]}\\Form.m2')

    def test_plan_rejects_changed_build_and_conditionals(self):
        self.build['BuildConfig'] = '0'*32
        with self.assertRaises(ValueError): self.plan()
        self.build['BuildConfig'] = BUILD_CONFIG
        next(r for r in self.retail if r['ID'] in DISPLAY_IDS)['ConditionalCreatureModelID'] = 1
        with self.assertRaises(ValueError): self.plan()

    def test_staging_rejects_drift_and_path_injection(self):
        plan = self.plan()
        for change in ('hash','path','duplicate'):
            bad = copy.deepcopy(plan)
            if change == 'hash': bad['sourceHashes']['CreatureModelData.dbc'] = '0'*64
            if change == 'path': bad['displays'][0]['modelPath'] = '../Character/Human.m2'
            if change == 'duplicate': bad['displays'].append(bad['displays'][0])
            with self.assertRaises(ValueError): patch_tables(self.a,self.b,bad)

    def test_dbc_bounds_duplicates_and_trailing_bytes(self):
        for data in (self.a[:-1], self.a+b'\0', encode([self.displays[0]]*2,16)):
            with self.assertRaises(ValueError): DBC(data,16)
        with self.assertRaises(ValueError): DBC(self.b,28,(2,)).string(100000)

    def test_creature_materials_are_baked_without_uv_changes(self):
        body = bytearray(0x150)
        body[:4] = b'MD20'
        struct.pack_into('<II',body,0x50,1,0x140)
        struct.pack_into('<4I',body,0x140,11,3,0,0)
        model = b'MD21'+struct.pack('<I',len(body))+body
        converted,ids = bind_textures(model,[12345,0,0])
        b = read_chunks(converted)[0].payload
        self.assertEqual(ids,[12345])
        self.assertEqual(b[:0x140],body[:0x140])
        self.assertEqual(texture_records(b)[0]['name'],'WXL/DruidForms/Textures/12345.blp')
        self.assertEqual(texture_records(b)[0]['flags'],3)
        for values in ([],[0,0,0]):
            with self.assertRaises(ValueError): bind_textures(model,values)

    def test_tree_selection_reindexes_shadows_and_draws(self):
        skin = bytearray(64)
        skin[:4] = b'SKIN'
        sections = []
        for gid in (0,101,102):
            row = bytearray(48);struct.pack_into('<H',row,0,gid);sections.append(row)
        records = [(28,sections)]
        for at,stride in ((36,24),(48,12)):
            batches=[]
            for i in range(3):
                row=bytearray(stride);struct.pack_into('<H',row,4,i);batches.append(row)
            records.append((at,batches))
        for at, rows in records:
            struct.pack_into('<II',skin,at,len(rows),len(skin));skin.extend(b''.join(rows))
        selected,removed=select_sections(bytes(skin),{102})
        self.assertEqual(removed,[101])
        for at,stride in ((36,24),(48,12)):
            count,offset=struct.unpack_from('<II',selected,at)
            self.assertEqual(count,2)
            self.assertEqual([struct.unpack_from('<H',selected,offset+i*stride+4)[0] for i in range(count)],[0,1])
        _,removed=select_sections(bytes(skin),set())
        self.assertEqual(removed,[101,102])


class DruidInstallTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.client=self.root/'client';self.package=self.root/'package'
        self.client.mkdir();self.package.mkdir();(self.client/'WTF').mkdir()
        (self.client/'WTF/Config.wtf').write_text('synthetic settings')
        self.rows=[]
        for name in (installer.ARCHIVE,installer.DLL_PATH):
            p=self.package/name;p.parent.mkdir(parents=True);p.write_bytes(name.encode())
            self.rows.append({'path':name,'size':p.stat().st_size,'sha256':installer.digest(p)})
        for replacement in (patch.object(installer,'loader'),patch.object(installer,'original_table',return_value=b'synthetic'),
                            patch.object(installer,'verify',return_value={'files':self.rows})):
            replacement.start();self.addCleanup(replacement.stop)

    def test_preview_no_backup_apply_and_idempotence(self):
        preview=installer.install(self.package,self.client,self.root/'unused')
        self.assertEqual(len(preview['newFiles']),2)
        self.assertFalse((self.client/'Data').exists())
        with patch.object(installer,'require_wow_closed'):
            installer.install(self.package,self.client,self.root/'unused',True,True,self.root/'report.json')
        self.assertEqual((self.client/'WTF/Config.wtf').read_text(),'synthetic settings')
        self.assertFalse((self.client/'DisabledPatches').exists())
        self.assertEqual(installer.install(self.package,self.client,self.root/'unused')['newFiles'],[])

    def test_unknown_destination_running_game_and_unsafe_report_refused(self):
        with self.assertRaises(ValueError):
            installer.install(self.package,self.client,self.root/'unused',True,False,self.root/'report.json')
        with self.assertRaises(ValueError):
            installer.install(self.package,self.client,self.root/'unused',True,True,self.client/'report.json')
        with patch.object(installer,'require_wow_closed',side_effect=ValueError('running')):
            with self.assertRaises(ValueError):
                installer.install(self.package,self.client,self.root/'unused',True,True,self.root/'report.json')
        target=self.client/installer.ARCHIVE;target.parent.mkdir();target.write_bytes(b'preserve')
        with self.assertRaises(ValueError): installer.install(self.package,self.client,self.root/'unused')
        self.assertEqual(target.read_bytes(),b'preserve')

    def test_conflicting_loose_table_patch_is_preserved(self):
        root=self.client/'Data/Patch-Other.MPQ/DBFilesClient'
        root.mkdir(parents=True)
        (root/'CreatureModelData.dbc').write_bytes(b'another project')
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            installer.install(self.package,self.client,self.root/'unused')
        self.assertEqual((root/'CreatureModelData.dbc').read_bytes(),b'another project')


@unittest.skipUnless(os.environ.get('WXL_DRUID_DLL'), 'optional source-built x86 druid extension')
class DruidExtensionTests(unittest.TestCase):
    def test_native_abi_and_relocation(self):
        results=installer.verify_extension(Path(os.environ['WXL_DRUID_DLL']).read_bytes())
        self.assertEqual([r['cases'] for r in results],[212,212])


if __name__ == '__main__': unittest.main()
