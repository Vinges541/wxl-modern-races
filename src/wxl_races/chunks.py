from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Any


class FormatError(ValueError):
  """Raised when a chunked asset is truncated or malformed."""


@dataclass(frozen=True)
class Chunk:
  tag: str
  offset: int
  size: int
  payload: bytes


def read_chunks(data: bytes, start: int = 0) -> list[Chunk]:
  chunks: list[Chunk] = []
  offset = start
  while offset < len(data):
    if len(data) - offset < 8:
      raise FormatError(f"trailing {len(data) - offset} bytes at 0x{offset:x}")
    raw_tag = data[offset:offset + 4]
    try:
      tag = raw_tag.decode("ascii")
    except UnicodeDecodeError as exc:
      raise FormatError(f"non-ASCII chunk tag at 0x{offset:x}") from exc
    if any(ord(char) < 0x20 or ord(char) > 0x7e for char in tag):
      raise FormatError(f"invalid chunk tag {raw_tag!r} at 0x{offset:x}")
    size = struct.unpack_from("<I", data, offset + 4)[0]
    payload_start = offset + 8
    payload_end = payload_start + size
    if payload_end > len(data):
      raise FormatError(
        f"chunk {tag} at 0x{offset:x} declares {size} bytes, "
        f"but only {len(data) - payload_start} remain"
      )
    chunks.append(Chunk(tag, offset, size, data[payload_start:payload_end]))
    offset = payload_end
  return chunks


def u32_array(payload: bytes) -> list[int]:
  if len(payload) % 4:
    raise FormatError(f"u32 chunk size {len(payload)} is not divisible by 4")
  return list(struct.unpack(f"<{len(payload) // 4}I", payload)) if payload else []


def afid_records(payload: bytes) -> list[dict[str, int]]:
  if len(payload) % 8:
    raise FormatError(f"AFID chunk size {len(payload)} is not divisible by 8")
  return [
    {"animationId": animation_id, "subAnimationId": sub_id, "fileDataId": file_id}
    for animation_id, sub_id, file_id in struct.iter_unpack("<HHI", payload)
  ]


def texture_records(payload: bytes) -> list[dict[str, Any]]:
  """Read the fixed-size M2Texture array from an MD20 body."""
  if not payload.startswith(b"MD20"):
    raise FormatError("texture records require an MD20 body")
  count = _u32_at(payload, 0x50)
  offset = _u32_at(payload, 0x54)
  end = offset + count * 16
  if count and (offset < 0x58 or end > len(payload)):
    raise FormatError(
      f"texture array at 0x{offset:x} with {count} records exceeds the MD20 body"
    )

  records: list[dict[str, Any]] = []
  for index in range(count):
    record_offset = offset + index * 16
    texture_type, flags, name_length, name_offset = struct.unpack_from(
      "<IIII", payload, record_offset
    )
    name = None
    if name_length:
      name_end = name_offset + name_length
      if name_offset >= len(payload) or name_end > len(payload):
        raise FormatError(
          f"texture {index} name at 0x{name_offset:x} with {name_length} bytes "
          "exceeds the MD20 body"
        )
      raw_name = payload[name_offset:name_end]
      if raw_name.endswith(b"\0"):
        raw_name = raw_name[:-1]
      try:
        name = raw_name.decode("utf-8")
      except UnicodeDecodeError as exc:
        raise FormatError(f"texture {index} name is not UTF-8") from exc
    records.append({
      "index": index,
      "type": texture_type,
      "flags": flags,
      "nameLength": name_length,
      "nameOffset": name_offset,
      "name": name,
      "recordOffset": record_offset,
    })
  return records


def inline_texture_paths(data: bytes, paths_by_file_id: dict[int, str]) -> tuple[bytes, list[dict[str, Any]]]:
  """Inline known type-0 TXID paths into an MD20/MD21 model.

  wxl-modern-m2 preserves inline names and therefore does not need a DB2
  FileDataID resolver for these entries.
  """
  chunks: list[Chunk] | None = None
  if data.startswith(b"MD20"):
    inner = bytearray(data)
  else:
    chunks = read_chunks(data)
    if not chunks or chunks[0].tag != "MD21" or not chunks[0].payload.startswith(b"MD20"):
      raise FormatError("texture path inlining requires an MD20 or MD21 model")
    inner = bytearray(chunks[0].payload)

  records = texture_records(bytes(inner))
  txids: list[int] = []
  if chunks:
    txid_chunk = next((chunk for chunk in chunks if chunk.tag == "TXID"), None)
    if txid_chunk:
      txids = u32_array(txid_chunk.payload)

  changes: list[dict[str, Any]] = []
  for record in records:
    index = record["index"]
    if record["type"] != 0 or index >= len(txids):
      continue
    file_id = txids[index]
    path = paths_by_file_id.get(file_id)
    if not path:
      continue
    if record["name"] == path:
      continue
    encoded = path.encode("utf-8") + b"\0"
    name_offset = len(inner)
    inner.extend(encoded)
    struct.pack_into("<II", inner, record["recordOffset"] + 8, len(encoded), name_offset)
    changes.append({
      "textureIndex": index,
      "fileDataId": file_id,
      "path": path,
      "nameOffset": name_offset,
    })

  if chunks is None:
    return bytes(inner), changes
  rebuilt = bytearray()
  for index, chunk in enumerate(chunks):
    payload = bytes(inner) if index == 0 else chunk.payload
    rebuilt.extend(chunk.tag.encode("ascii"))
    rebuilt.extend(struct.pack("<I", len(payload)))
    rebuilt.extend(payload)
  return bytes(rebuilt), changes


def inspect_asset(path: Path) -> dict[str, Any]:
  data = path.read_bytes()
  result: dict[str, Any] = {
    "path": str(path),
    "size": len(data),
    "kind": path.suffix.lower().lstrip(".") or "unknown",
  }
  if data.startswith(b"MD20"):
    result.update({"container": "MD20", "innerVersion": _u32_at(data, 4)})
    if len(data) >= 0x48:
      result["skinProfileCount"] = _u32_at(data, 0x44)
    result["textureRecords"] = texture_records(data)
    result["chunks"] = []
    return result

  chunks = read_chunks(data)
  result["container"] = chunks[0].tag if chunks else "empty"
  result["chunks"] = [
    {"tag": chunk.tag, "offset": chunk.offset, "size": chunk.size}
    for chunk in chunks
  ]
  by_tag = {chunk.tag: chunk for chunk in chunks}

  if chunks and chunks[0].tag == "MD21":
    inner = chunks[0].payload
    if not inner.startswith(b"MD20"):
      raise FormatError("MD21 payload does not begin with MD20")
    result["innerVersion"] = _u32_at(inner, 4)
    if len(inner) >= 0x48:
      result["skinProfileCount"] = _u32_at(inner, 0x44)
    result["textureRecords"] = texture_records(inner)

  for tag in ("TXID", "SFID", "BFID"):
    if tag in by_tag:
      result[tag.lower()] = u32_array(by_tag[tag].payload)
  for tag in ("SKID", "PFID"):
    if tag in by_tag:
      values = u32_array(by_tag[tag].payload)
      if len(values) != 1:
        raise FormatError(f"{tag} must contain exactly one FileDataID")
      result[tag.lower()] = values[0]
  if "AFID" in by_tag:
    result["afid"] = afid_records(by_tag["AFID"].payload)

  tags = {chunk.tag for chunk in chunks}
  if path.suffix.lower() == ".anim" or tags & {"AFM2", "AFSA", "AFSB"}:
    result["animationLayout"] = (
      "split" if tags & {"AFSA", "AFSB"} else "afm2" if "AFM2" in tags else "unknown"
    )
    result["warcraftXLAnimationCompatible"] = result["animationLayout"] == "afm2"
  if path.suffix.lower() == ".skel":
    result["skeletonSections"] = [tag for tag in ("SKS1", "SKB1", "SKA1") if tag in tags]
    if "SKPD" in by_tag:
      values = u32_array(by_tag["SKPD"].payload)
      if len(values) != 4:
        raise FormatError("SKPD does not contain a parent skeleton FileDataID")
      result["parentSkeletonFileDataId"] = values[2]
  return result


def _u32_at(data: bytes, offset: int) -> int:
  if len(data) < offset + 4:
    raise FormatError(f"missing u32 at 0x{offset:x}")
  return struct.unpack_from("<I", data, offset)[0]
