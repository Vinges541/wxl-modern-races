from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Any

from .chunks import FormatError, inline_texture_paths, inspect_asset
from .resolver import ExportIndex


class BundleError(RuntimeError):
  """Raised when a required model dependency cannot be staged safely."""


def load_target(path: Path) -> dict[str, Any]:
  data = json.loads(path.read_text(encoding="utf-8"))
  if data.get("schemaVersion") != 1:
    raise BundleError("only target manifest schemaVersion 1 is supported")
  source = data.get("source", {})
  target = data.get("target", {})
  if not source.get("modelPath"):
    raise BundleError("source.modelPath is required")
  if not target.get("legacyPath"):
    raise BundleError("target.legacyPath is required")
  _game_path(target["legacyPath"])
  if target.get("clientBuild") != 12340:
    raise BundleError("this PoC only targets WoW 3.3.5a build 12340")
  file_data_id_paths = source.get("fileDataIdPaths", {})
  if not isinstance(file_data_id_paths, dict):
    raise BundleError("source.fileDataIdPaths must be an object")
  for file_id, game_path in file_data_id_paths.items():
    if not str(file_id).isdecimal() or not isinstance(game_path, str):
      raise BundleError("source.fileDataIdPaths must map decimal FileDataIDs to paths")
    _game_path(game_path)
  return data


def audit(target: dict[str, Any], index: ExportIndex) -> dict[str, Any]:
  model_path = _resolve_model(target, index)
  report: dict[str, Any] = {
    "structuralAuditOnly": True,
    "runtimeVerified": False,
    "race": target.get("race"),
    "sex": target.get("sex"),
    "sourceModel": str(model_path) if model_path else None,
    "targetModel": target["target"]["legacyPath"],
    "targetClientBuild": target["target"]["clientBuild"],
    "manifests": [str(path) for path in index.manifest_paths],
    "dependencies": {
      "skins": [],
      "lodSkins": [],
      "skeleton": None,
      "parentSkeleton": None,
      "animations": [],
      "bones": [],
      "textures": [],
    },
    "errors": [],
    "warnings": [],
    "warcraftXL": {
      "modelContainerSupported": False,
      "siblingSkeletonAliasRequired": False,
      "allResolvedAnimationsSupported": True,
      "externalSkeletonSupported": True,
      "externalBonePayloadsSupported": True,
      "parentSkeletonChainSupported": True,
    },
  }
  if not model_path:
    report["errors"].append(f"source model not found: {target['source']['modelPath']}")
    report["readyToStage"] = False
    report["readyForCurrentWarcraftXL"] = False
    return report

  try:
    model_info = inspect_asset(model_path)
  except (OSError, FormatError) as exc:
    report["errors"].append(f"cannot inspect source model: {exc}")
    report["readyToStage"] = False
    report["readyForCurrentWarcraftXL"] = False
    return report
  report["model"] = model_info
  report["warcraftXL"]["modelContainerSupported"] = model_info.get("container") in {"MD20", "MD21"}
  if not report["warcraftXL"]["modelContainerSupported"]:
    report["errors"].append(f"unsupported model container: {model_info.get('container')}")

  skin_ids = model_info.get("sfid", [])
  skin_count = min(model_info.get("skinProfileCount", len(skin_ids)), len(skin_ids))
  for position, file_id in enumerate(skin_ids):
    kind = "skins" if position < skin_count else "lodSkins"
    resolved = index.resolve_fdid(file_id)
    report["dependencies"][kind].append(_dependency(file_id, resolved, required=position < skin_count))
    if position < skin_count and not resolved:
      report["errors"].append(f"required skin FileDataID {file_id} is unresolved")

  skeleton_id = model_info.get("skid")
  if skeleton_id:
    resolved = index.resolve_fdid(skeleton_id)
    skeleton = _dependency(skeleton_id, resolved, required=True)
    if resolved:
      try:
        skeleton["inspection"] = inspect_asset(resolved)
        parent_id = skeleton["inspection"].get("parentSkeletonFileDataId")
        if parent_id:
          parent_path = index.resolve_fdid(parent_id)
          report["dependencies"]["parentSkeleton"] = _dependency(parent_id, parent_path, required=True)
          report["warcraftXL"]["parentSkeletonChainSupported"] = False
          if not parent_path:
            report["errors"].append(
              f"required parent skeleton FileDataID {parent_id} is unresolved"
            )
          report["warnings"].append(
            f"skeleton has parent FileDataID {parent_id}; current WarcraftXL does not follow SKPD chains"
          )
      except (OSError, FormatError) as exc:
        skeleton["inspectionError"] = str(exc)
        report["errors"].append(f"cannot inspect skeleton FileDataID {skeleton_id}: {exc}")
    else:
      report["errors"].append(f"required skeleton FileDataID {skeleton_id} is unresolved")
    report["dependencies"]["skeleton"] = skeleton
    report["warcraftXL"]["siblingSkeletonAliasRequired"] = True
    report["warcraftXL"]["externalSkeletonSupported"] = False
    report["warnings"].append(
      "model uses an external SKID skeleton; current wxl-modern-m2 rejects split-skeleton models"
    )

  bone_ids = list(model_info.get("bfid", []))
  skeleton_info = (report["dependencies"]["skeleton"] or {}).get("inspection", {})
  for file_id in skeleton_info.get("bfid", []):
    if file_id not in bone_ids:
      bone_ids.append(file_id)
  for file_id in bone_ids:
    resolved = index.resolve_fdid(file_id)
    report["dependencies"]["bones"].append(_dependency(file_id, resolved, required=False))
    if not resolved:
      report["warnings"].append(
        f"optional FacePose .bone FileDataID {file_id} is unresolved"
      )
  if bone_ids:
    report["warcraftXL"]["externalBonePayloadsSupported"] = False
    report["warnings"].append(
      "BFID .bone files are FacePose 808 variants; current wxl-modern-m2 drops them, "
      "so facial poses may be reduced while the base rig remains usable"
    )

  animation_records: list[dict[str, int]] = []
  seen_animations: set[tuple[int, int, int]] = set()
  animation_sources = [model_info, skeleton_info]
  parent = report["dependencies"]["parentSkeleton"]
  if parent and parent["path"]:
    try:
      parent["inspection"] = inspect_asset(Path(parent["path"]))
      animation_sources.append(parent["inspection"])
    except (OSError, FormatError) as exc:
      parent["inspectionError"] = str(exc)
      report["errors"].append(f"cannot inspect parent skeleton FileDataID {parent['fileDataId']}: {exc}")
  for source_info in animation_sources:
    for record in source_info.get("afid", []):
      key = (record["animationId"], record["subAnimationId"], record["fileDataId"])
      if key not in seen_animations:
        animation_records.append(record)
        seen_animations.add(key)

  for record in animation_records:
    file_id = record["fileDataId"]
    resolved = index.resolve_fdid(file_id)
    dependency = {**record, **_dependency(file_id, resolved, required=bool(file_id))}
    if resolved:
      try:
        animation_info = inspect_asset(resolved)
        dependency["inspection"] = animation_info
        if animation_info.get("animationLayout") == "split":
          report["warcraftXL"]["allResolvedAnimationsSupported"] = False
          report["warnings"].append(
            f"animation {record['animationId']}:{record['subAnimationId']} uses AFSA/AFSB; "
            "current WarcraftXL only unwraps AFM2"
          )
      except (OSError, FormatError) as exc:
        dependency["inspectionError"] = str(exc)
        report["warnings"].append(f"cannot inspect animation FileDataID {file_id}: {exc}")
    elif file_id:
      report["errors"].append(f"animation FileDataID {file_id} is unresolved")
    report["dependencies"]["animations"].append(dependency)

  configured_paths = _file_data_id_paths(target)
  texture_records = model_info.get("textureRecords", [])
  for position, file_id in enumerate(model_info.get("txid", [])):
    record = texture_records[position] if position < len(texture_records) else {}
    static_texture = record.get("type", 0) == 0
    resolved = index.resolve_fdid(file_id)
    inline_path = configured_paths.get(file_id)
    if resolved and not inline_path:
      inline_path = str(_safe_relative(resolved, index.root))
    dependency = _dependency(file_id, resolved, required=bool(file_id and static_texture))
    dependency.update({
      "textureIndex": position,
      "textureType": record.get("type"),
      "inlineName": record.get("name"),
      "inlinePath": inline_path,
      "providedByTargetClient": bool(inline_path and not resolved),
    })
    report["dependencies"]["textures"].append(dependency)
    has_inline_name = bool(record.get("name"))
    if file_id and static_texture and not resolved and not inline_path and not has_inline_name:
      report["errors"].append(f"texture FileDataID {file_id} is unresolved")

  if not skin_ids:
    report["warnings"].append("model has no SFID chunk; skin aliases cannot be derived from FileDataIDs")
  report["readyToStage"] = not report["errors"]
  report["readyForCurrentWarcraftXL"] = (
    report["readyToStage"]
    and report["warcraftXL"]["modelContainerSupported"]
    and report["warcraftXL"]["allResolvedAnimationsSupported"]
    and report["warcraftXL"]["externalSkeletonSupported"]
    and report["warcraftXL"]["parentSkeletonChainSupported"]
  )
  return report


def stage(target: dict[str, Any], index: ExportIndex, output: Path) -> dict[str, Any]:
  report = audit(target, index)
  if not report["readyToStage"]:
    raise BundleError("audit failed:\n- " + "\n- ".join(report["errors"]))

  legacy_model = _game_path(target["target"]["legacyPath"])
  if output.is_symlink():
    raise BundleError("output directory must not be a symbolic link")
  output.mkdir(parents=True, exist_ok=True)
  legacy_stem = legacy_model.with_suffix("")
  staged: list[dict[str, Any]] = []

  texture_paths = {
    dependency["fileDataId"]: dependency["inlinePath"]
    for dependency in report["dependencies"]["textures"]
    if dependency.get("fileDataId") and dependency.get("inlinePath")
  }
  _stage_model(
    Path(report["sourceModel"]), _destination(output, legacy_model), texture_paths, staged
  )
  for position, dependency in enumerate(report["dependencies"]["skins"]):
    destination = _destination(output, f"{legacy_stem}{position:02d}.skin")
    _copy(Path(dependency["path"]), destination, "skin", staged, dependency["fileDataId"])
  for position, dependency in enumerate(report["dependencies"]["lodSkins"]):
    if not dependency["path"]:
      continue
    destination = _destination(output, f"{legacy_stem}_lod{position + 1:02d}.skin")
    _copy(Path(dependency["path"]), destination, "lodSkin", staged, dependency["fileDataId"])

  skeleton = report["dependencies"]["skeleton"]
  if skeleton and skeleton["path"]:
    destination = _destination(output, legacy_stem.with_suffix(".skel"))
    _copy(Path(skeleton["path"]), destination, "skeleton", staged, skeleton["fileDataId"])

  for position, bone in enumerate(report["dependencies"]["bones"]):
    if not bone["path"]:
      continue
    destination = _destination(output, f"{legacy_stem}_{position}.bone")
    _copy(Path(bone["path"]), destination, "bone", staged, bone["fileDataId"])

  for animation in report["dependencies"]["animations"]:
    if not animation["path"]:
      continue
    destination = _destination(output,
      f"{legacy_stem}{animation['animationId']:04d}-{animation['subAnimationId']:02d}.anim"
    )
    _copy(Path(animation["path"]), destination, "animation", staged, animation["fileDataId"])

  for texture in report["dependencies"]["textures"]:
    if not texture["path"] or not texture.get("inlinePath"):
      continue
    source = Path(texture["path"])
    _copy(
      source,
      _destination(output, texture["inlinePath"]),
      "texture",
      staged,
      texture["fileDataId"],
    )

  report["output"] = str(output.resolve())
  report["staged"] = staged
  report_path = _destination(output, "bundle-report.json")
  report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
  return report


def _resolve_model(target: dict[str, Any], index: ExportIndex) -> Path | None:
  source = target["source"]
  model = index.resolve_path(source["modelPath"])
  if model:
    return model
  file_id = source.get("fileDataId")
  return index.resolve_fdid(file_id) if isinstance(file_id, int) else None


def _dependency(file_id: int, path: Path | None, required: bool) -> dict[str, Any]:
  return {"fileDataId": file_id, "path": str(path) if path else None, "required": required}


def _file_data_id_paths(target: dict[str, Any]) -> dict[int, str]:
  return {
    int(file_id): str(_game_path(game_path))
    for file_id, game_path in target["source"].get("fileDataIdPaths", {}).items()
  }


def _game_path(value: str) -> PurePosixPath:
  if not isinstance(value, str):
    raise BundleError("game path must be a string")
  parts = value.replace("\\", "/").split("/")
  if any(part in {"", ".", ".."} or ':' in part or '\0' in part for part in parts):
    raise BundleError(f"unsafe game path: {value}")
  return PurePosixPath(*parts)


def _destination(output: Path, relative: str | PurePosixPath) -> Path:
  """Confine writes even when an existing output subtree contains symlinks."""
  path = output
  if output.is_symlink():
    raise BundleError("output directory must not be a symbolic link")
  for part in _game_path(str(relative)).parts:
    path = path / part
    if path.is_symlink():
      raise BundleError(f"refusing symbolic link in destination: {path}")
  if not path.resolve().is_relative_to(output.resolve()):
    raise BundleError("destination escapes output directory")
  return path


def _stage_model(
  source: Path,
  destination: Path,
  texture_paths: dict[int, str],
  staged: list[dict[str, Any]],
) -> None:
  destination.parent.mkdir(parents=True, exist_ok=True)
  transformed, changes = inline_texture_paths(source.read_bytes(), texture_paths)
  destination.write_bytes(transformed)
  shutil.copystat(source, destination)
  staged.append({
    "kind": "model",
    "source": str(source),
    "destination": str(destination),
    "size": destination.stat().st_size,
    "sha256": _sha256(destination),
    "transforms": {"inlinedTexturePaths": changes},
  })


def _copy(
  source: Path,
  destination: Path,
  kind: str,
  staged: list[dict[str, Any]],
  file_id: int | None = None,
) -> None:
  destination.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(source, destination)
  entry: dict[str, Any] = {
    "kind": kind,
    "source": str(source),
    "destination": str(destination),
    "size": destination.stat().st_size,
    "sha256": _sha256(destination),
  }
  if file_id is not None:
    entry["fileDataId"] = file_id
  staged.append(entry)


def _safe_relative(path: Path, root: Path) -> PurePosixPath:
  try:
    relative = path.resolve().relative_to(root.resolve())
  except ValueError as exc:
    raise BundleError(f"dependency is outside export root: {path}") from exc
  if any(part in {"", ".", ".."} for part in relative.parts):
    raise BundleError(f"unsafe dependency path: {relative}")
  return PurePosixPath(*relative.parts)


def _sha256(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()
