from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from .bundle import BundleError, audit, load_target, stage
from .chunks import FormatError, inspect_asset
from .resolver import ExportIndex


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="wxl-races",
    description="Audit and stage wow.export player models for WarcraftXL.",
  )
  subparsers = parser.add_subparsers(dest="command", required=True)

  inspect_parser = subparsers.add_parser("inspect", help="inspect M2/SKEL/ANIM chunks")
  inspect_parser.add_argument("paths", nargs="+", type=Path)

  verify_parser = subparsers.add_parser("verify-client", help="verify a 3.3.5a build 12340 client")
  verify_parser.add_argument("client_root", type=Path)

  audit_parser = subparsers.add_parser("audit-export", help="audit a raw wow.export bundle")
  _add_export_arguments(audit_parser)
  audit_parser.add_argument("--report", type=Path, help="also write the JSON report to this path")

  stage_parser = subparsers.add_parser("stage", help="stage a named WarcraftXL patch directory")
  _add_export_arguments(stage_parser)
  stage_parser.add_argument(
    "--output",
    type=Path,
    default=Path("build/Patch-ModernRaces.MPQ"),
    help="output directory (default: build/Patch-ModernRaces.MPQ)",
  )
  return parser


def _add_export_arguments(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("target", type=Path, help="race target JSON, e.g. manifests/human_male.json")
  parser.add_argument("export_root", type=Path, help="root directory produced by wow.export raw export")
  parser.add_argument(
    "--manifest",
    action="append",
    default=[],
    type=Path,
    help="wow.export manifest JSON (repeatable)",
  )


def main(argv: list[str] | None = None) -> int:
  args = build_parser().parse_args(argv)
  try:
    if args.command == "inspect":
      payload: Any = [inspect_asset(path) for path in args.paths]
      if len(payload) == 1:
        payload = payload[0]
      _print_json(payload)
      return 0

    if args.command == "verify-client":
      executable = args.client_root / "Wow.exe"
      data = executable.read_bytes()
      markers = [b"World of WarCraft (build 12340)", b"3.3.5", b"WoW [Release] Build 12340"]
      report = {
        "clientRoot": str(args.client_root.resolve()),
        "executable": str(executable.resolve()),
        "peExecutable": data.startswith(b"MZ"),
        "build": 12340 if all(marker in data for marker in markers) else None,
        "sha256": hashlib.sha256(data).hexdigest(),
      }
      report["compatible"] = report["peExecutable"] and report["build"] == 12340
      _print_json(report)
      return 0 if report["compatible"] else 2

    target = load_target(args.target)
    manifest_paths = list(args.manifest)
    if not manifest_paths:
      manifest_paths = sorted(args.export_root.rglob("*.manifest.json"))
    index = ExportIndex(args.export_root, manifest_paths)

    if args.command == "audit-export":
      report = audit(target, index)
      _print_json(report)
      if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
      return 0 if report["readyToStage"] else 2

    report = stage(target, index, args.output)
    _print_json({
      "readyToStage": report["readyToStage"],
      "readyForCurrentWarcraftXL": report["readyForCurrentWarcraftXL"],
      "output": report["output"],
      "stagedFiles": len(report["staged"]),
      "warnings": report["warnings"],
    })
    return 0
  except (BundleError, OSError, FormatError, json.JSONDecodeError) as exc:
    print(f"error: {exc}", file=sys.stderr)
    return 2


def _print_json(value: Any) -> None:
  print(json.dumps(value, indent=2, ensure_ascii=False))


if __name__ == "__main__":
  raise SystemExit(main())
