from tests.fixture_paths import integration, fixture_root, client_root, dbc_root
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from patch_shadow_bone_budget import BUDGET, EXPECTED, RESULT, SITES, patch
from patch_wow import PatchError, Pe32


class ShadowBoneBudgetTests(unittest.TestCase):
  def test_rejects_unknown_or_truncated_module(self):
    for source in (b'', b'MZ', bytes(208384)):
      with self.assertRaises(PatchError):
        patch(source)

  def test_all_budget_consumers_covered(self):
    self.assertEqual(BUDGET, 21)
    self.assertEqual(len(SITES), 5)
    self.assertEqual(len({rva for rva, _ in SITES}), 5)
    for _, signature in SITES:
      self.assertEqual(bytes.fromhex(signature).count(75), 1)

  @integration
  def test_release_fixture_exact_delta(self):
    fixture = client_root() / 'DisabledPatches/ShadowDiagnostics/wxl-modern-m2-original.dll'
    if not fixture.exists():
      self.skipTest('Local release fixture unavailable')
    source = fixture.read_bytes()
    self.assertEqual(hashlib.sha256(source).hexdigest(), EXPECTED)
    result = patch(source)
    self.assertEqual(hashlib.sha256(result).hexdigest(), RESULT)
    self.assertEqual(len(source), len(result))
    pe = Pe32(bytearray(source))
    expected_offsets = {pe.va_to_offset(pe.image_base+rva)+bytes.fromhex(sig).index(75) for rva, sig in SITES}
    changed = {i for i, (a, b) in enumerate(zip(source, result)) if a != b}
    self.assertEqual(changed, expected_offsets)
    with self.assertRaises(PatchError):
      patch(result)
