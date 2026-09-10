#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 WarcraftXL
# Python adaptation and modifications: wxl-modern-races contributors, 2026.
# See THIRD-PARTY-NOTICES.md for the pinned upstream files and modification scope.
"""Cross-platform port of wxl-patcher for the verified 3.3.5a client.

The byte edits and PE import layout mirror WarcraftXL/wxl-core v1.1.245.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile


EXPECTED_WOW_SHA256 = "aa63a5750d60ef16746c686b3d5e26876d98953eab08b1c026cd0faf78e88cb8"
IMAGE_FILE_LARGE_ADDRESS_AWARE = 0x20
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x40
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000


class PatchError(RuntimeError):
  pass


@dataclass(frozen=True)
class Section:
  header_offset: int
  name: str
  virtual_size: int
  virtual_address: int
  raw_size: int
  raw_offset: int


def align_up(value: int, alignment: int) -> int:
  if alignment <= 0 or alignment & (alignment - 1):
    raise PatchError(f"invalid PE alignment: {alignment}")
  return (value + alignment - 1) & ~(alignment - 1)


class Pe32:
  def __init__(self, data: bytearray) -> None:
    self.data = data
    if len(data) < 0x40 or data[:2] != b"MZ":
      raise PatchError("not an MZ executable")
    self.nt = self.u32(0x3C)
    if self.nt + 24 > len(data) or data[self.nt:self.nt + 4] != b"PE\0\0":
      raise PatchError("not a PE executable")
    self.file_header = self.nt + 4
    self.optional = self.nt + 24
    if self.u16(self.optional) != 0x10B:
      raise PatchError("WarcraftXL requires a 32-bit PE executable")
    self.optional_size = self.u16(self.file_header + 16)
    if self.optional + self.optional_size > len(data):
      raise PatchError("truncated PE optional header")
    self.section_table = self.optional + self.optional_size
    self._validate_sections()

  def u16(self, offset: int) -> int:
    return struct.unpack_from("<H", self.data, offset)[0]

  def u32(self, offset: int) -> int:
    return struct.unpack_from("<I", self.data, offset)[0]

  def set_u16(self, offset: int, value: int) -> None:
    struct.pack_into("<H", self.data, offset, value)

  def set_u32(self, offset: int, value: int) -> None:
    struct.pack_into("<I", self.data, offset, value)

  @property
  def section_count(self) -> int:
    return self.u16(self.file_header + 2)

  @property
  def image_base(self) -> int:
    return self.u32(self.optional + 28)

  @property
  def section_alignment(self) -> int:
    return self.u32(self.optional + 32)

  @property
  def file_alignment(self) -> int:
    return self.u32(self.optional + 36)

  @property
  def size_of_headers(self) -> int:
    return self.u32(self.optional + 60)

  def sections(self) -> list[Section]:
    result = []
    for index in range(self.section_count):
      offset = self.section_table + index * 40
      raw_name = bytes(self.data[offset:offset + 8]).split(b"\0", 1)[0]
      result.append(Section(
        header_offset=offset,
        name=raw_name.decode("ascii", errors="replace"),
        virtual_size=self.u32(offset + 8),
        virtual_address=self.u32(offset + 12),
        raw_size=self.u32(offset + 16),
        raw_offset=self.u32(offset + 20),
      ))
    return result

  def _validate_sections(self) -> None:
    end = self.section_table + self.section_count * 40
    if end > len(self.data) or end > self.size_of_headers:
      raise PatchError("truncated or invalid PE section table")

  def has_section(self, name: str) -> bool:
    return any(section.name == name for section in self.sections())

  def va_to_offset(self, va: int) -> int:
    rva = va - self.image_base
    for section in self.sections():
      span = max(section.virtual_size, section.raw_size)
      if section.virtual_address <= rva < section.virtual_address + span:
        offset = rva - section.virtual_address + section.raw_offset
        if offset >= len(self.data):
          break
        return offset
    raise PatchError(f"virtual address 0x{va:08x} is not backed by the PE")

  def write_va(self, va: int, payload: bytes) -> None:
    offset = self.va_to_offset(va)
    if offset + len(payload) > len(self.data):
      raise PatchError(f"write at 0x{va:08x} exceeds the PE")
    self.data[offset:offset + len(payload)] = payload

  def set_large_address_aware(self) -> None:
    characteristics = self.u16(self.file_header + 18)
    self.set_u16(self.file_header + 18, characteristics | IMAGE_FILE_LARGE_ADDRESS_AWARE)

  def data_directory(self, index: int) -> tuple[int, int]:
    offset = self.optional + 96 + index * 8
    return self.u32(offset), self.u32(offset + 4)

  def set_data_directory(self, index: int, rva: int, size: int) -> None:
    offset = self.optional + 96 + index * 8
    self.set_u32(offset, rva)
    self.set_u32(offset + 4, size)

  def add_import(self, dll: str, function: str, section_name: str = ".wxl") -> None:
    if self.has_section(section_name):
      return
    import_rva, _ = self.data_directory(1)
    import_offset = self.va_to_offset(self.image_base + import_rva)
    original_count = 0
    while import_offset + (original_count + 1) * 20 <= len(self.data):
      descriptor = import_offset + original_count * 20
      if self.u32(descriptor + 12) == 0 and self.u32(descriptor + 16) == 0:
        break
      original_count += 1
    else:
      raise PatchError("unterminated PE import descriptor table")

    descriptor_bytes = (original_count + 2) * 20
    int_offset = descriptor_bytes
    iat_offset = int_offset + 8
    ibn_offset = iat_offset + 8
    ibn_length = align_up(2 + len(function.encode("ascii")) + 1, 2)
    dll_offset = ibn_offset + ibn_length
    blob_size = dll_offset + len(dll.encode("ascii")) + 1

    last = self.sections()[-1]
    section_rva = align_up(
      last.virtual_address + last.virtual_size, self.section_alignment
    )
    section_raw = align_up(len(self.data), self.file_alignment)
    blob = bytearray(blob_size)
    blob[:original_count * 20] = self.data[
      import_offset:import_offset + original_count * 20
    ]
    struct.pack_into(
      "<IIIII",
      blob,
      original_count * 20,
      section_rva + int_offset,
      0,
      0,
      section_rva + dll_offset,
      section_rva + iat_offset,
    )
    struct.pack_into("<I", blob, int_offset, section_rva + ibn_offset)
    struct.pack_into("<I", blob, iat_offset, section_rva + ibn_offset)
    function_bytes = function.encode("ascii") + b"\0"
    dll_bytes = dll.encode("ascii") + b"\0"
    blob[ibn_offset + 2:ibn_offset + 2 + len(function_bytes)] = function_bytes
    blob[dll_offset:dll_offset + len(dll_bytes)] = dll_bytes

    new_header = self.section_table + self.section_count * 40
    if new_header + 40 > self.size_of_headers:
      raise PatchError("the new .wxl section header does not fit in PE header padding")
    raw_size = align_up(blob_size, self.file_alignment)
    name_bytes = section_name.encode("ascii")
    if len(name_bytes) > 8:
      raise PatchError("PE section name exceeds 8 bytes")
    self.data[new_header:new_header + 40] = b"\0" * 40
    self.data[new_header:new_header + len(name_bytes)] = name_bytes
    struct.pack_into(
      "<IIIIIIHHI",
      self.data,
      new_header + 8,
      blob_size,
      section_rva,
      raw_size,
      section_raw,
      0,
      0,
      0,
      0,
      IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE,
    )
    self.set_data_directory(1, section_rva, descriptor_bytes)
    self.set_data_directory(11, 0, 0)
    self.set_u32(
      self.optional + 56,
      align_up(section_rva + blob_size, self.section_alignment),
    )
    self.set_u16(self.file_header + 2, self.section_count + 1)

    self.data.extend(b"\0" * (section_raw - len(self.data)))
    self.data.extend(blob)
    self.data.extend(b"\0" * (section_raw + raw_size - len(self.data)))

  def report(self) -> dict[str, object]:
    import_rva, import_size = self.data_directory(1)
    return {
      "sections": [section.name for section in self.sections()],
      "largeAddressAware": bool(
        self.u16(self.file_header + 18) & IMAGE_FILE_LARGE_ADDRESS_AWARE
      ),
      "importDirectory": {"rva": import_rva, "size": import_size},
      "hasWarcraftXLSection": self.has_section(".wxl"),
    }


PATCHES = {
  "glue-unlock": [
    (0x5F4DBF, b"\xEB"),
    (0x816625, b"\xEB"),
    (0x81663F, b"\x03"),
    (0x816695, b"\x03"),
    (0x816746, b"\xEB"),
    (0x81675F, b"\xB8\x03\x00\x00\x00\xEB\xED"),
  ],
  "named-patch-archives": [
    (0x9E2709, b"*"),
    (0x9E2716, b"*"),
  ],
}


def patched_bytes(source: bytes) -> tuple[bytes, dict[str, object]]:
  data = bytearray(source)
  pe = Pe32(data)
  pe.set_large_address_aware()
  already_patched = pe.has_section(".wxl")
  if not already_patched:
    for edits in PATCHES.values():
      for va, payload in edits:
        pe.write_va(va, payload)
    pe.add_import("WarcraftXL.dll", "WarcraftXL")
  report = pe.report()
  report["alreadyPatched"] = already_patched
  report["patchScripts"] = list(PATCHES)
  return bytes(data), report


def atomic_write(path: Path, payload: bytes) -> None:
  original_mode = stat.S_IMODE(path.stat().st_mode)
  descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".wxltmp", dir=path.parent)
  temporary = Path(temporary_name)
  try:
    with os.fdopen(descriptor, "wb") as stream:
      stream.write(payload)
      stream.flush()
      os.fsync(stream.fileno())
    os.chmod(temporary, original_mode)
    os.replace(temporary, path)
  except BaseException:
    temporary.unlink(missing_ok=True)
    raise


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("target", type=Path, help="isolated Wow.exe to patch")
  parser.add_argument("--check", action="store_true", help="inspect without writing")
  args = parser.parse_args()

  try:
    source = args.target.read_bytes()
    original_hash = hashlib.sha256(source).hexdigest()
    pe = Pe32(bytearray(source))
    already_patched = pe.has_section(".wxl")
    if not already_patched and original_hash != EXPECTED_WOW_SHA256:
      raise PatchError(
        f"refusing unverified client SHA-256 {original_hash}; expected {EXPECTED_WOW_SHA256}"
      )
    output, report = patched_bytes(source)
    report.update({
      "target": str(args.target.resolve()),
      "originalSha256": original_hash,
      "patchedSha256": hashlib.sha256(output).hexdigest(),
      "originalSize": len(source),
      "patchedSize": len(output),
    })
    if not args.check:
      backup = Path(str(args.target) + ".orig")
      if not already_patched:
        if backup.exists():
          backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
          if backup_hash != original_hash:
            raise PatchError(
              f"existing backup {backup} does not match the target; refusing to overwrite"
            )
        else:
          shutil.copy2(args.target, backup)
          with backup.open("rb") as stream:
            os.fsync(stream.fileno())
      atomic_write(args.target, output)
      report["backup"] = str(backup.resolve())
      report["written"] = True
    else:
      report["written"] = False
    print(json.dumps(report, indent=2))
    return 0
  except (OSError, PatchError, struct.error, UnicodeError) as exc:
    print(f"error: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
