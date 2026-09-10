from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable


ID_KEYS = {"filedataid", "fileid"}
PATH_KEYS = {
  "file",
  "filename",
  "filenameinternal",
  "filenameexternal",
  "filepath",
  "path",
  "modelpath",
}
NUMERIC_TOKEN = re.compile(r"(?<!\d)(\d{4,})(?!\d)")


def normalize_path(value: str) -> str:
  return str(PurePosixPath(value.replace("\\", "/"))).lstrip("./").lower()


class ExportIndex:
  def __init__(self, root: Path, manifest_paths: Iterable[Path] = ()) -> None:
    self.root = root.resolve()
    self.by_relative: dict[str, Path] = {}
    self.by_basename: dict[str, list[Path]] = defaultdict(list)
    self.by_fdid: dict[int, list[Path]] = defaultdict(list)
    self.manifest_fdid_paths: dict[int, list[str]] = defaultdict(list)
    self.manifest_paths: list[Path] = []
    self._scan_files()
    for path in manifest_paths:
      self.add_manifest(path)

  def _scan_files(self) -> None:
    if not self.root.is_dir():
      raise FileNotFoundError(f"export root is not a directory: {self.root}")
    for path in sorted(self.root.rglob("*")):
      if path.is_symlink():
        raise ValueError(f"symbolic links are not accepted in an export: {path}")
      if not path.is_file():
        continue
      relative = normalize_path(str(path.relative_to(self.root)))
      self.by_relative[relative] = path
      self.by_basename[path.name.lower()].append(path)
      for token in NUMERIC_TOKEN.findall(path.name):
        self.by_fdid[int(token)].append(path)

  def add_manifest(self, path: Path) -> None:
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    self.manifest_paths.append(path)
    for file_id, file_path in _collect_manifest_pairs(data):
      candidate = path.parent / file_path
      if candidate.is_file():
        try:
          file_path = str(candidate.resolve().relative_to(self.root))
        except ValueError:
          continue
      normalized = normalize_path(file_path)
      if normalized not in self.manifest_fdid_paths[file_id]:
        self.manifest_fdid_paths[file_id].append(normalized)

  def resolve_path(self, requested: str) -> Path | None:
    normalized = normalize_path(requested)
    if normalized in self.by_relative:
      return self.by_relative[normalized]

    suffix_matches = [
      path for relative, path in self.by_relative.items()
      if relative.endswith("/" + normalized) or normalized.endswith("/" + relative)
    ]
    if len(suffix_matches) == 1:
      return suffix_matches[0]

    basename_matches = self.by_basename.get(PurePosixPath(normalized).name, [])
    if len(basename_matches) == 1:
      return basename_matches[0]
    return None

  def resolve_fdid(self, file_id: int) -> Path | None:
    if not file_id:
      return None
    candidates: list[Path] = []
    for manifest_path in self.manifest_fdid_paths.get(file_id, []):
      resolved = self.resolve_path(manifest_path)
      if resolved and resolved not in candidates:
        candidates.append(resolved)
    for path in self.by_fdid.get(file_id, []):
      if path not in candidates:
        candidates.append(path)
    return candidates[0] if len(candidates) == 1 else None

  def manifest_candidates(self, suffix: str = ".manifest.json") -> list[Path]:
    return [path for path in self.by_relative.values() if path.name.lower().endswith(suffix)]


def _collect_manifest_pairs(value: Any) -> list[tuple[int, str]]:
  pairs: list[tuple[int, str]] = []

  def visit(node: Any) -> None:
    if isinstance(node, dict):
      ids = [_as_int(v) for k, v in node.items() if k.lower() in ID_KEYS]
      paths = [v for k, v in node.items() if k.lower() in PATH_KEYS and isinstance(v, str)]
      for file_id in ids:
        if file_id is not None:
          pairs.extend((file_id, path) for path in paths)

      for key, child in node.items():
        key_lower = key.lower()
        if key_lower in {"animfileids", "animationfileids", "filedataidmap"} and isinstance(child, dict):
          for map_key, map_value in child.items():
            key_id = _as_int(map_key)
            if key_id is not None and isinstance(map_value, str):
              pairs.append((key_id, map_value))
            elif isinstance(map_value, dict):
              value_id = _first_id(map_value) or key_id
              value_paths = [
                item for name, item in map_value.items()
                if name.lower() in PATH_KEYS and isinstance(item, str)
              ]
              if value_id is not None:
                pairs.extend((value_id, path) for path in value_paths)
        visit(child)
    elif isinstance(node, list):
      for child in node:
        visit(child)

  visit(value)
  return pairs


def _first_id(value: dict[str, Any]) -> int | None:
  for key, item in value.items():
    if key.lower() in ID_KEYS:
      parsed = _as_int(item)
      if parsed is not None:
        return parsed
  return None


def _as_int(value: Any) -> int | None:
  if isinstance(value, bool):
    return None
  if isinstance(value, int):
    return value
  if isinstance(value, str) and value.isdecimal():
    return int(value)
  return None
