"""Emulate both actual GLUE callers up to SetTransform, without running WoW/Wine."""
import argparse
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP
from patch_glue_preview import EXPECTED, RESULT, TARGET, SITES, patch
from patch_wow import Pe32, PatchError
import hashlib


def check(source):
    if hashlib.sha256(source).hexdigest() == EXPECTED:
        source = patch(source)
    if hashlib.sha256(source).hexdigest() != RESULT:
        raise PatchError('Expected a supported preview runtime')
    pe = Pe32(bytearray(source))
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(pe.image_base, 0x1000000)
    u.mem_write(pe.image_base, source[:pe.size_of_headers])
    for section in pe.sections():
        u.mem_write(pe.image_base+section.virtual_address,
                    source[section.raw_offset:section.raw_offset+section.raw_size])
    u.mem_map(0x20000000, 0x10000)
    u.mem_map(0x30000000, 0x10000)
    char, model, entries, sp = 0x20000000, 0x20001000, 0x20002000, 0x30008000

    def put(at, value):
        u.mem_write(at, struct.pack('<I', value))

    put(0xb6b1a0, char); put(char+0x38, model)
    put(0xb6b200, 1); put(0xb6b23c, 1); put(0xac436c, 0)
    put(0xb6b240, entries); put(entries+0x188, char)
    count = 0
    for kind, entry in [('create', 0x4e0160), ('select', 0x4e2e70)]:
        for race in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11):
            for sex in (0, 1):
                for class_id in (1, 6):
                    for angle in (-0.25, 0.0, 2.0):
                        put(char+0x18, race); put(char+0x1c, sex); put(char+0x20, class_id)
                        u.mem_write(entries+0x178, bytes([race, class_id, sex]))
                        u.mem_write(sp, struct.pack('<If', 0x900000, angle))
                        u.reg_write(UC_X86_REG_ESP, sp)
                        u.emu_start(entry, TARGET, count=200)
                        if u.reg_read(UC_X86_REG_EIP) != TARGET:
                            raise ValueError('GLUE caller did not reach the native transform')
                        current = u.reg_read(UC_X86_REG_ESP)
                        ret, xyz, facing, scale = struct.unpack('<IIff', u.mem_read(current, 16))
                        expected = (2/3 if sex == 0 else .8) if race == 6 else 1.0
                        if (ret != SITES[kind]+5 or facing != angle or abs(scale-expected) > 1e-6
                                or bytes(u.mem_read(xyz, 12)) != bytes(12)):
                            raise ValueError('Incorrect preview transform arguments')
                        count += 1
    return {'cases': count, 'screens': 2, 'races': 10, 'sexes': 2,
            'classes': ['warrior', 'death-knight'], 'facings': 3,
            'nativeCallArgumentsVerified': True, 'gameExecuted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    print(json.dumps(check(parser.parse_args().exe.read_bytes()), indent=2))
