"""Fit HD Tauren in GLUE previews without modifying models or world transforms.

Only two GLUE call sites are redirected. Their original target, used by the
world renderer too, is never patched. Each thunk preserves every register and
EFLAGS and changes only the by-value scale argument after checking the exact
preview instance, race and sex. The original function still builds the matrix.
"""
import hashlib
import struct

from patch_wow import Pe32, PatchError, align_up

EXPECTED = '50e16ecacac5ab77b083c2a56a2b92b4bac69a00749652756f9d3cc369491985'
RESULT = '59b9a6a173bee6836d11778192495e3bcbc50f1ea37194f102c52cdfd8d5b392'
TARGET = 0x8251D0
SITES = {'create': 0x4E0198, 'select': 0x4E2ED4}
CONTEXT = bytes.fromhex('d9e8d95c2404d91c24518b4838')
SCALES = {'male': 2 / 3, 'female': 0.8}


def rel32(source, target, opcode=b'\xe9'):
    return opcode + struct.pack('<i', target - source - 5)


def thunk(kind, address):
    """x86 thiscall tail thunk; entry stack is return, position*, facing, scale."""
    if kind not in SITES:
        raise PatchError('Unknown GLUE preview')
    code, labels, branches = bytearray(), {}, []

    def emit(value):
        code.extend(bytes.fromhex(value))

    def branch(opcode, label):
        code.extend(bytes.fromhex(opcode))
        branches.append((len(code), label))
        code.extend(b'\0' * 4)

    emit('9c 50 52')  # pushfd; push eax; push edx: scale now at esp+24.
    if kind == 'create':
        emit('a1 a0b1b600 85c0')  # current creation CCharModel, not a CGUnit
        branch('0f84', 'done')
        emit('394838')           # current preview CM2Model must equal ECX
        branch('0f85', 'done')
        emit('83781806')         # CCharModel.race == Tauren
        branch('0f85', 'done')
        emit('8b401c')           # CCharModel.sex, 0 male / 1 female
    else:
        emit('a1 6c43ac00 85c0')  # selected character index
        branch('0f88', 'done')   # reject negative indices before dereference
        emit('3b05 3cb2b600')
        branch('0f83', 'done')   # index >= character count
        emit('8b15 40b2b600 85d2')
        branch('0f84', 'done')
        emit('69c0 98010000 01d0 8b90 88010000 85d2')
        branch('0f84', 'done')
        emit('394a38')           # selected character's CM2Model == ECX
        branch('0f85', 'done')
        emit('80b8 78010000 06')  # character-list race byte
        branch('0f85', 'done')
        emit('0fb680 7a010000')   # character-list sex byte
    emit('85c0')
    branch('0f84', 'male')
    emit('83f801')
    branch('0f85', 'done')       # unknown/neutral sex is left untouched
    emit('c7442418')
    code.extend(struct.pack('<f', SCALES['female']))
    branch('e9', 'done')
    labels['male'] = len(code)
    emit('c7442418')
    code.extend(struct.pack('<f', SCALES['male']))
    labels['done'] = len(code)
    emit('5a 58 9d')
    code.extend(rel32(address + len(code), TARGET))
    for offset, label in branches:
        struct.pack_into('<i', code, offset, labels[label] - offset - 4)
    return bytes(code)


def patch(source):
    if hashlib.sha256(source).hexdigest() != EXPECTED:
        raise PatchError('Expected exact pre-preview runtime; unknown or already patched input')
    result = _patch_verified_image(source)
    if hashlib.sha256(result).hexdigest() != RESULT:
        raise PatchError('Preview output differs from the verified profile')
    return result


def _patch_verified_image(source):
    """Structural patcher also exercised on a synthetic PE; not an install entry point."""
    result = bytearray(source)
    pe = Pe32(result)
    if pe.image_base != 0x400000:
        raise PatchError('Unexpected image base')
    for kind, site in SITES.items():
        offset = pe.va_to_offset(site)
        context = CONTEXT if kind == 'create' else CONTEXT[:-2] + bytes.fromhex('4a38')
        if result[offset-len(context):offset] != context or result[offset:offset+5] != rel32(site, TARGET, b'\xe8'):
            raise PatchError('GLUE transform call/context mismatch')
    native = pe.va_to_offset(TARGET)
    if result[native:native+9] != bytes.fromhex('558becd9e856578bf9'):
        raise PatchError('Native transform entry mismatch')
    if result[native+0x83:native+0x86] != bytes.fromhex('c20c00'):
        raise PatchError('Native transform calling convention mismatch')
    last = pe.sections()[-1]
    # The verified image has no spare section header. Its last RX section has
    # 24 bytes of animation-loader code and 488 bytes of unused zero padding.
    # Retain those 24 bytes exactly; use only the existing padding for the thunks.
    if (last.name != '.wxlanim' or last.virtual_size != 24 or last.raw_size != 512
            or pe.u32(last.header_offset + 36) != 0x60000020
            or any(result[last.raw_offset+24:last.raw_offset+512])):
        raise PatchError('Expected unused padding after the verified animation-loader thunk')
    start = align_up(last.virtual_size, 16)
    code = bytearray()
    for kind, site in SITES.items():
        code.extend(b'\x90' * (align_up(len(code), 16) - len(code)))
        va = pe.image_base + last.virtual_address + start + len(code)
        pe.write_va(site, rel32(site, va, b'\xe8'))
        code.extend(thunk(kind, va))
    if start + len(code) > last.raw_size:
        raise PatchError('Preview thunks exceed available RX padding')
    result[last.raw_offset+start:last.raw_offset+start+len(code)] = code
    pe.set_u32(last.header_offset + 8, start + len(code))
    return bytes(result)
