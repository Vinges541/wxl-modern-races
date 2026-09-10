"""Read assets from immutable original MPQs through the existing StormLib build."""
import ctypes as c
import os
from pathlib import Path
from project_paths import client_path


def read_asset(name):
  library = os.environ.get('WXL_STORMLIB')
  if not library:
    raise ValueError('Set WXL_STORMLIB to a locally built StormLib shared library')
  lib = c.CDLL(library)
  lib.SFileOpenArchive.argtypes = [c.c_char_p, c.c_uint32, c.c_uint32, c.POINTER(c.c_void_p)]
  lib.SFileOpenFileEx.argtypes = [c.c_void_p, c.c_char_p, c.c_uint32, c.POINTER(c.c_void_p)]
  lib.SFileGetFileSize.argtypes = [c.c_void_p, c.c_void_p]
  lib.SFileGetFileSize.restype = c.c_uint32
  lib.SFileReadFile.argtypes = [c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32), c.c_void_p]
  lib.SFileCloseFile.argtypes = [c.c_void_p]
  lib.SFileCloseArchive.argtypes = [c.c_void_p]
  root = client_path() / 'Data'
  for archive in ['patch-3.MPQ', 'patch-2.MPQ', 'patch.MPQ', 'lichking.MPQ', 'expansion.MPQ', 'common-2.MPQ', 'common.MPQ']:
    handle = c.c_void_p()
    if not lib.SFileOpenArchive(str(root / archive).encode(), 0, 0x100, c.byref(handle)):
      continue
    try:
      file = c.c_void_p()
      if not lib.SFileOpenFileEx(handle, name.replace('/', '\\').encode(), 0, c.byref(file)):
        continue
      try:
        size = lib.SFileGetFileSize(file, None)
        if size > 64 * 1024 * 1024:
          raise ValueError('Asset exceeds diagnostic size bound')
        data, read = c.create_string_buffer(size), c.c_uint32()
        if not lib.SFileReadFile(file, data, size, c.byref(read), None) or read.value != size:
          raise ValueError('Incomplete MPQ read')
        return data.raw
      finally:
        lib.SFileCloseFile(file)
    finally:
      lib.SFileCloseArchive(handle)
  raise FileNotFoundError(name)


if __name__ == '__main__':
  import sys
  destination = Path(sys.argv[2])
  if destination.exists():
    raise FileExistsError(destination)
  destination.write_bytes(read_asset(sys.argv[1]))
