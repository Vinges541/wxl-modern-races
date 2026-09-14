"""Build the freestanding x86 WarcraftXL extension using Clang and lld-link."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

from pack_mpq import no_links

ROOT = Path(__file__).resolve().parents[1]
DLL_PATH = 'Extensions/wxl-modern-races/wxl-modern-races.dll'
DLL_SHA256 = 'a0b853e41b7896733cd1447056309554cd58627ba933e4c304589370eea24185'
SDK_HASHES = {
    'PluginApi.h': '7421cc82c09382d25a91bf340c197dfd2470212bc761b1dac9fb711218bc37ed',
}


def build(sdk, clang='clang', linker='lld-link'):
    sdk = no_links(sdk)
    for name, expected in SDK_HASHES.items():
        if hashlib.sha256(no_links(sdk/'wxl'/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Use the pinned WarcraftXL SDK headers: ' + name)
    with tempfile.TemporaryDirectory(prefix='wxl-redirect-') as temporary:
        work = Path(temporary)
        subprocess.run([clang, '--target=i686-pc-windows-msvc', '-std=c11', '-Oz',
                        '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
                        '-fno-ident', '-mno-sse', '-mno-sse2', '-g0', '-Wall', '-Wextra', '-Werror',
                        '-I', str(sdk), '-c', str(ROOT/'runtime/appearance_redirect.c'),
                        '-o', str(work/'redirect.obj')], check=True)
        subprocess.run([linker, '/dll', '/noentry', '/nodefaultlib', '/machine:x86',
                        '/timestamp:0', '/opt:ref', '/opt:icf', '/safeseh:no',
                        '/out:wxl-modern-races.dll', 'redirect.obj'], cwd=work, check=True)
        return (work/'wxl-modern-races.dll').read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True, help='pinned wxl-core/include')
    parser.add_argument('--output', type=Path, required=True, help='new private DLL path')
    parser.add_argument('--clang', default='clang')
    parser.add_argument('--linker', default='lld-link')
    args = parser.parse_args()
    output = no_links(args.output)
    if output.exists() or not output.parent.is_dir():
        parser.error('Output must be new with an existing parent')
    data = build(args.sdk, args.clang, args.linker)
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != DLL_SHA256:
        parser.error('DLL differs from verified compiler profile: ' + checksum)
    with output.open('xb') as stream:
        stream.write(data)
    print(checksum)


if __name__ == '__main__':
    main()
