from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from wxl_races.bundle import BundleError, audit, load_target, stage
from wxl_races.chunks import FormatError, inspect_asset, read_chunks
from wxl_races.resolver import ExportIndex


def chunk(tag: str, payload: bytes = b"") -> bytes:
  return tag.encode("ascii") + struct.pack("<I", len(payload)) + payload


def modern_m2(*, missing_skin: bool = False) -> bytes:
  md20 = bytearray(0x138)
  md20[0:4] = b"MD20"
  struct.pack_into("<I", md20, 4, 274)
  struct.pack_into("<I", md20, 0x44, 2)
  struct.pack_into("<II", md20, 0x50, 1, 0x100)
  struct.pack_into("<IIII", md20, 0x100, 0, 0, 0, 0)
  second_skin = 1999 if missing_skin else 1002
  return b"".join([
    chunk("MD21", bytes(md20)),
    chunk("SFID", struct.pack("<III", 1001, second_skin, 1099)),
    chunk("SKID", struct.pack("<I", 2001)),
    chunk("AFID", struct.pack("<HHIHHI", 0, 0, 3001, 4, 2, 3002)),
    chunk("TXID", struct.pack("<I", 4001)),
  ])


class ChunkTests(unittest.TestCase):
  def test_rejects_truncated_chunk(self) -> None:
    with self.assertRaises(FormatError):
      read_chunks(b"AFM2\x10\x00\x00\x00short")

  def test_inspects_afid_and_split_animation(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
      root = Path(temporary)
      model = root / "model.m2"
      model.write_bytes(modern_m2())
      info = inspect_asset(model)
      self.assertEqual(info["container"], "MD21")
      self.assertEqual(info["skinProfileCount"], 2)
      self.assertEqual(info["afid"][1], {
        "animationId": 4,
        "subAnimationId": 2,
        "fileDataId": 3002,
      })

      animation = root / "split.anim"
      animation.write_bytes(chunk("AFM2", b"events") + chunk("AFSA", b"attachments"))
      animation_info = inspect_asset(animation)
      self.assertEqual(animation_info["animationLayout"], "split")
      self.assertFalse(animation_info["warcraftXLAnimationCompatible"])


class PipelineTests(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.root = Path(self.temporary.name)
    self.export_root = self.root / "export"
    self.export_root.mkdir()
    self.target_path = self.root / "human_male.json"
    self.target_path.write_text(json.dumps({
      "schemaVersion": 1,
      "race": "Human",
      "sex": "Male",
      "source": {
        "modelPath": "character/human/male/humanmale_hd.m2",
        "fileDataId": 5001,
      },
      "target": {
        "clientBuild": 12340,
        "legacyPath": "Character/Human/Male/HumanMale.m2",
      },
    }), encoding="utf-8")

  def tearDown(self) -> None:
    self.temporary.cleanup()

  def _write_export(self, *, missing_skin: bool = False) -> Path:
    files = {
      5001: ("character/human/male/humanmale_hd.m2", modern_m2(missing_skin=missing_skin)),
      1001: ("shared/skin/human_hd_00.skin", b"SKIN-one"),
      1002: ("shared/skin/human_hd_01.skin", b"SKIN-two"),
      1099: ("shared/skin/human_hd_lod.skin", b"SKIN-lod"),
      2001: (
        "shared/skeleton/humanmale.skel",
        chunk("SKS1")
        + chunk("SKB1")
        + chunk("SKA1")
        + chunk("AFID", struct.pack("<HHIHHI", 0, 0, 3001, 4, 2, 3002)),
      ),
      3001: ("shared/animation/stand.anim", chunk("AFM2", b"stand")),
      3002: (
        "shared/animation/walk.anim",
        chunk("AFM2", b"events") + chunk("AFSA", b"attachments") + chunk("AFSB", b"bones"),
      ),
      4001: ("character/human/male/humanmale_hd.blp", b"BLP2texture"),
    }
    manifest_files = []
    for file_id, (relative, content) in files.items():
      path = self.export_root / relative
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(content)
      manifest_files.append({"fileDataID": file_id, "file": relative})
    manifest = self.export_root / "humanmale_hd.manifest.json"
    manifest.write_text(json.dumps({"files": manifest_files}), encoding="utf-8")
    return manifest

  def test_audit_and_stage_complete_bundle(self) -> None:
    manifest = self._write_export()
    target = load_target(self.target_path)
    index = ExportIndex(self.export_root, [manifest])
    report = audit(target, index)
    self.assertTrue(report["readyToStage"])
    self.assertFalse(report["readyForCurrentWarcraftXL"])
    self.assertFalse(report["warcraftXL"]["allResolvedAnimationsSupported"])
    self.assertFalse(report["warcraftXL"]["externalSkeletonSupported"])
    self.assertEqual(len(report["warnings"]), 2)

    output = self.root / "Patch-ModernRaces.MPQ"
    staged = stage(target, index, output)
    self.assertEqual(len(staged["staged"]), 8)
    expected = [
      "Character/Human/Male/HumanMale.m2",
      "Character/Human/Male/HumanMale00.skin",
      "Character/Human/Male/HumanMale01.skin",
      "Character/Human/Male/HumanMale_lod01.skin",
      "Character/Human/Male/HumanMale.skel",
      "Character/Human/Male/HumanMale0000-00.anim",
      "Character/Human/Male/HumanMale0004-02.anim",
      "character/human/male/humanmale_hd.blp",
      "bundle-report.json",
    ]
    for relative in expected:
      self.assertTrue((output / relative).is_file(), relative)
    model_info = inspect_asset(output / "Character/Human/Male/HumanMale.m2")
    self.assertEqual(
      model_info["textureRecords"][0]["name"],
      "character/human/male/humanmale_hd.blp",
    )

  def test_native_texture_mapping_and_optional_face_pose_bone(self) -> None:
    manifest = self._write_export()
    model = modern_m2().replace(
      chunk("TXID", struct.pack("<I", 4001)),
      chunk("TXID", struct.pack("<I", 9999)) + chunk("BFID", struct.pack("<I", 8888)),
    )
    source_path = self.export_root / "character/human/male/humanmale_hd.m2"
    source_path.write_bytes(model)
    target_data = json.loads(self.target_path.read_text(encoding="utf-8"))
    target_data["source"]["fileDataIdPaths"] = {
      "9999": "Character/Human/Male/native.blp",
    }
    self.target_path.write_text(json.dumps(target_data), encoding="utf-8")

    target = load_target(self.target_path)
    index = ExportIndex(self.export_root, [manifest])
    report = audit(target, index)
    self.assertTrue(report["readyToStage"])
    self.assertTrue(report["dependencies"]["textures"][0]["providedByTargetClient"])
    self.assertFalse(report["dependencies"]["bones"][0]["required"])

    output = self.root / "native-output"
    staged = stage(target, index, output)
    model_info = inspect_asset(output / "Character/Human/Male/HumanMale.m2")
    self.assertEqual(
      model_info["textureRecords"][0]["name"],
      "Character/Human/Male/native.blp",
    )
    self.assertEqual(len(staged["staged"]), 7)

  def test_missing_required_skin_fails_closed(self) -> None:
    manifest = self._write_export(missing_skin=True)
    target = load_target(self.target_path)
    index = ExportIndex(self.export_root, [manifest])
    report = audit(target, index)
    self.assertFalse(report["readyToStage"])
    self.assertIn("required skin FileDataID 1999 is unresolved", report["errors"])
    with self.assertRaises(BundleError):
      stage(target, index, self.root / "output")


if __name__ == "__main__":
  unittest.main()
