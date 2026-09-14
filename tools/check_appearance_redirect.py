"""Execute the actual x86 extension against a synthetic WarcraftXL ABI with Unicorn."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_EIP
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP
from build_appearance_redirect import DLL_SHA256
from appearance_tables import NAMESPACE, TABLES
from patch_wow import Pe32


def check(data, delta=0, *, expected_hash=DLL_SHA256, namespace=NAMESPACE,
          tables=TABLES, plugin_name='wxl-modern-races'):
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('Expected the verified appearance extension')
    pe = Pe32(bytearray(data))
    if pe.u16(pe.file_header) != 0x14c or pe.u32(pe.file_header+4) != 0:
        raise ValueError('Expected reproducible x86 PE')
    if pe.data_directory(1) != (0, 0) or pe.u32(pe.optional+16) != 0 or pe.data_directory(9) != (0, 0):
        raise ValueError('Extension must have no imports, entry point or TLS')
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    base = pe.image_base + delta
    u.mem_map(base, 0x10000)
    u.mem_write(base, data[:pe.size_of_headers])
    for s in pe.sections():
        u.mem_write(base+s.virtual_address, data[s.raw_offset:s.raw_offset+s.raw_size])

    def read(at):
        return struct.unpack('<I', u.mem_read(at, 4))[0]

    def put(at, value):
        u.mem_write(at, struct.pack('<I', value))

    def string(at):
        if not at:
            return None
        return bytes(u.mem_read(at, 260)).split(b'\0', 1)[0].decode('ascii')

    if delta:
        rva, size = pe.data_directory(5)
        pos, end = base+rva, base+rva+size
        while pos < end:
            page, block = struct.unpack('<II', u.mem_read(pos, 8))
            for (entry,) in struct.iter_unpack('<H', u.mem_read(pos+8, block-8)):
                if entry >> 12 == 3:
                    at = base+page+(entry & 4095)
                    put(at, read(at)+delta)
                elif entry >> 12:
                    raise ValueError('Unsupported relocation')
            pos += block
    er = base+pe.data_directory(0)[0]
    count, functions, names, ordinals = (read(er+x) for x in (24, 28, 32, 36))
    exports = {}
    for index in range(count):
        name = string(base+read(base+names+4*index))
        ordinal = struct.unpack('<H', u.mem_read(base+ordinals+2*index, 2))[0]
        exports[name] = base+read(base+functions+4*ordinal)
    if set(exports) != {'WXL_Query', 'WXL_Load'}:
        raise ValueError('Unexpected DLL exports')
    arena, stack, stop = 0x30000000, 0x31000000, 0x32000000
    for start in (arena, stack, stop):
        u.mem_map(start, 0x10000)
    api, hook, log, native = arena, arena+0x1000, arena+0x1100, arena+0x1200
    u.mem_write(hook, b'\xc3'); u.mem_write(log, b'\xc3')
    u.mem_write(native, b'\xc2\x10\x00')
    put(api, 28); put(api+4, 1); put(api+8, log); put(api+24, hook)
    callbacks, calls, logs = {}, [], []
    fail_hook = [False]

    def intercept(uc, at, size, unused):
        sp = uc.reg_read(UC_X86_REG_ESP)
        if at == hook:
            name, detour, original, priority = (read(sp+x) for x in (4, 8, 12, 16))
            if priority != 0:
                raise ValueError('Unexpected hook chain priority')
            if not fail_hook[0]:
                callbacks[string(name)] = detour
                put(original, native)
            uc.reg_write(UC_X86_REG_EAX, int(not fail_hook[0]))
        elif at == log:
            logs.append(string(read(sp+12)))
        elif at == native:
            archive, name, flags, out = (read(sp+x) for x in (4, 8, 12, 16))
            calls.append((archive, name, string(name), flags, out))
            if out:
                put(out, 0xc0ffee)
            uc.reg_write(UC_X86_REG_EAX, 0x55)
    u.hook_add(UC_HOOK_CODE, intercept)

    def invoke(address, args=(), stdcall=False):
        sp = stack+0x8000
        u.mem_write(sp, struct.pack('<'+'I'*(len(args)+1), stop, *args))
        preserved = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
        for reg in preserved:
            u.reg_write(reg, 0x13579bdf)
        u.reg_write(UC_X86_REG_ESP, sp)
        u.emu_start(address, stop, count=20000)
        if (u.reg_read(UC_X86_REG_EIP) != stop or
                u.reg_read(UC_X86_REG_ESP) != sp+4+(4*len(args) if stdcall else 0) or
                any(u.reg_read(reg) != 0x13579bdf for reg in preserved)):
            raise ValueError('Extension ABI/register/stack contract failed')
        return u.reg_read(UC_X86_REG_EAX)

    info = invoke(exports['WXL_Query'])
    if (read(info), read(info+4), string(read(info+8)), read(info+16)) != (20, 1, plugin_name, 12340):
        raise ValueError('Plugin query mismatch')
    for pointer, size, version, hook_value in ((0,28,1,hook), (api,24,1,hook),
                                             (api,28,2,hook), (api,28,1,0)):
        put(api,size); put(api+4,version); put(api+24,hook_value)
        if invoke(exports['WXL_Load'], (pointer,)) or callbacks:
            raise ValueError('Invalid ABI must not register hooks')
    put(api,28); put(api+4,1); put(api+24,hook)
    fail_hook[0] = True
    if invoke(exports['WXL_Load'], (api,)) or callbacks:
        raise ValueError('Hook failure must be reported')
    fail_hook[0] = False
    if invoke(exports['WXL_Load'], (api,)) != 1 or set(callbacks) != {'Io.FileOpen'}:
        raise ValueError('Early hooks not registered')
    if invoke(exports['WXL_Load'], (api,)) != 1:
        raise ValueError('Load must be idempotent')
    cases = 0
    positive = [f'DBFilesClient/{name}' for name in tables]
    negative = ['', 'DBFilesClient', 'DBFilesClient/ChrRaces.dbc',
                *[f'DBFilesClient/{name}' for name in ('CharSections.dbc', 'CreatureDisplayInfo.dbc',
                  'CreatureDisplayInfoExtra.dbc', 'CreatureModelData.dbc') if name not in tables],
                '../DBFilesClient/CharSections.dbc',
                'DBFilesClient/CharSections.dbc.old', 'XDBFilesClient/CharSections.dbc',
                'Character/Human/Male/HumanMale.m2', *(f'{namespace}/{name}' for name in tables)]
    for callback in callbacks.values():
        for source in [None, *positive, *negative]:
            variants = [source] if source is None else [source, source.upper(), source.lower(), source.replace('/', '\\')]
            for variant in variants:
                for archive in (0, 0x1234):
                    for flags in (0, 0x20000):
                        name_ptr, out = arena+0x2000 if variant is not None else 0, arena+0x3000
                        if name_ptr:
                            u.mem_write(name_ptr, variant.encode()+b'\0')
                        expected = (f'{namespace}/{source.split("/")[-1]}'.replace('/', '\\')
                                    if source in positive and not archive else variant)
                        if invoke(callback, (archive, name_ptr, flags, out), True) != 0x55:
                            raise ValueError('Native return value changed')
                        call = calls[-1]
                        if (call[0], call[2], call[3], call[4]) != (archive, expected, flags, out) or read(out) != 0xc0ffee:
                            raise ValueError('Incorrect redirect/native arguments')
                        if expected == variant and call[1] != name_ptr:
                            raise ValueError('Unmatched names must retain the original pointer')
                        cases += 1
    return {'cases': cases, 'relocated': bool(delta), 'nativeReadPreserved': True,
            'stackAndRegistersVerified': True, 'noImports': True, 'gameExecuted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dll', type=Path)
    data = parser.parse_args().dll.read_bytes()
    print(json.dumps([check(data), check(data, 0x08000000)], indent=2))
