import importlib.util
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import patch_glue_preview as preview
from patch_wow import Pe32, PatchError


def synthetic_pe():
    data = bytearray(0x500000)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x14c, 2)
    struct.pack_into('<H', data, 0x94, 224)
    struct.pack_into('<H', data, 0x98, 0x10b)
    for offset, value in [(28, 0x400000), (32, 0x1000), (36, 0x200), (60, 0x400)]:
        struct.pack_into('<I', data, 0x98 + offset, value)
    data[0x178:0x1a0] = struct.pack('<8sIIIIIIHHI', b'.text', len(data)-0x400,
                                    0x1000, len(data)-0x400, 0x400, 0, 0, 0, 0, 0x60000020)
    data[0x1a0:0x1c8] = struct.pack('<8sIIIIIIHHI', b'.wxlanim', 24,
                                    0x501000, 512, len(data), 0, 0, 0, 0, 0x60000020)
    data.extend(b'\xcc' * 24 + b'\0' * 488)
    pe = Pe32(data)
    for kind, site in preview.SITES.items():
        context = preview.CONTEXT if kind == 'create' else preview.CONTEXT[:-2] + bytes.fromhex('4a38')
        pe.write_va(site - len(context), context + preview.rel32(site, preview.TARGET, b'\xe8'))
    pe.write_va(preview.TARGET, bytes.fromhex('558becd9e856578bf9'))
    pe.write_va(preview.TARGET + 0x83, bytes.fromhex('c20c00'))
    return bytes(data)


class PreviewStructureTests(unittest.TestCase):
    def test_reject_unknown_and_already_patched(self):
        for source in (b'', b'MZ', synthetic_pe()):
            with self.assertRaises(PatchError):
                preview.patch(source)
        source = preview._patch_verified_image(synthetic_pe())
        with self.assertRaises(PatchError):
            preview._patch_verified_image(source)

    def test_only_two_existing_call_sites_change(self):
        source = synthetic_pe()
        result = preview._patch_verified_image(source)
        old, new = Pe32(bytearray(source)), Pe32(bytearray(result))
        section = new.sections()[-1]
        self.assertEqual(section.name, '.wxlanim')
        self.assertEqual(new.section_count, old.section_count)
        self.assertEqual(len(source), len(result))
        self.assertEqual(struct.unpack_from('<I', result, section.header_offset+36)[0], 0x60000020)
        before = bytearray(source)
        for site in preview.SITES.values():
            offset = old.va_to_offset(site)
            before[offset:offset+5] = result[offset:offset+5]
            target = site + 5 + struct.unpack_from('<i', result, offset+1)[0]
            self.assertTrue(new.image_base+section.virtual_address <= target < new.image_base+section.virtual_address+section.virtual_size)
        before[section.header_offset+8:section.header_offset+12] = result[section.header_offset+8:section.header_offset+12]
        begin, end = section.raw_offset+32, section.raw_offset+section.virtual_size
        before[begin:end] = result[begin:end]
        self.assertEqual(bytes(before), result)
        self.assertEqual(source[section.raw_offset:section.raw_offset+24], result[section.raw_offset:section.raw_offset+24])
        native = old.va_to_offset(preview.TARGET)
        self.assertEqual(source[native:native+0x86], result[native:native+0x86])

    def test_context_mismatch_refused(self):
        source = bytearray(synthetic_pe())
        pe = Pe32(source)
        source[pe.va_to_offset(preview.SITES['select'])-4] ^= 1
        with self.assertRaises(PatchError):
            preview._patch_verified_image(bytes(source))

    def test_thunk_kind_refused(self):
        with self.assertRaises(PatchError):
            preview.thunk('world', 0x10000000)


@unittest.skipUnless(importlib.util.find_spec('unicorn'), 'optional Unicorn x86 emulation')
class PreviewEmulationTests(unittest.TestCase):
    def run_thunk(self, kind, race, sex, issue=None):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
            UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP,
            UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in [(0x400000, 0x800000), (0x10000000, 0x1000),
                           (0x20000000, 0x10000), (0x30000000, 0x10000)]:
            u.mem_map(base, size)
        addr, model, char, entries, sp = 0x10000000, 0x20000000, 0x20001000, 0x20002000, 0x30008000
        u.mem_write(addr, preview.thunk(kind, addr))

        def put(at, value):
            u.mem_write(at, struct.pack('<I', value & 0xffffffff))

        put(0xb6b1a0, 0 if issue == 'null-character' else char)
        put(char+0x18, race); put(char+0x1c, sex)
        put(char+0x38, model+4 if issue == 'wrong-instance' else model)
        put(0xac436c, -1 if issue == 'negative-index' else 1 if issue == 'large-index' else 0)
        put(0xb6b23c, 0 if issue == 'empty-list' else 1)
        put(0xb6b240, 0 if issue == 'null-list' else entries)
        put(entries+0x188, 0 if issue == 'null-character' else char)
        u.mem_write(entries+0x178, bytes([race, 6, sex]))  # class deliberately DK
        args = struct.pack('<IIfI', 0x900000, model+0x100, 0.25, 0x3f800000)
        u.mem_write(sp, args)
        registers = {UC_X86_REG_EAX: 0x12345678, UC_X86_REG_EBX: 0x23456789,
                     UC_X86_REG_ECX: model, UC_X86_REG_EDX: 0x34567890,
                     UC_X86_REG_ESI: 0x45678901, UC_X86_REG_EDI: 0x56789012,
                     UC_X86_REG_EBP: sp+0x100, UC_X86_REG_ESP: sp,
                     UC_X86_REG_EFLAGS: 0x246}
        for reg, value in registers.items():
            u.reg_write(reg, value)
        memory_before = bytes(u.mem_read(0x20000000, 0x10000))
        globals_before = bytes(u.mem_read(0xac0000, 0xb0000))
        u.emu_start(addr, preview.TARGET, count=100)
        self.assertEqual(u.reg_read(UC_X86_REG_EIP), preview.TARGET)
        for reg, value in registers.items():
            self.assertEqual(u.reg_read(reg), value)
        self.assertEqual(bytes(u.mem_read(sp, 12)), args[:12])
        self.assertEqual(bytes(u.mem_read(0x20000000, 0x10000)), memory_before)
        self.assertEqual(bytes(u.mem_read(0xac0000, 0xb0000)), globals_before)
        return struct.unpack('<f', u.mem_read(sp+12, 4))[0]

    def test_all_races_and_sexes_only_tauren_changes(self):
        for kind in preview.SITES:
            for race in range(1, 12):
                for sex in (0, 1, 2):
                    with self.subTest(kind=kind, race=race, sex=sex):
                        want = (2/3 if sex == 0 else .8) if race == 6 and sex < 2 else 1
                        self.assertAlmostEqual(self.run_thunk(kind, race, sex), want)

    def test_invalid_preview_context_left_unchanged(self):
        for kind in preview.SITES:
            issues = ['null-character', 'wrong-instance']
            if kind == 'select':
                issues += ['negative-index', 'large-index', 'empty-list', 'null-list']
            for issue in issues:
                with self.subTest(kind=kind, issue=issue):
                    self.assertEqual(self.run_thunk(kind, 6, 0, issue), 1)
