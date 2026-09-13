# Changelog

## 0.1.0a1 — unreleased

- Preparation tools for all 20 WotLK race/sex variants and NPC appearance.
- Runtime patches for model visibility, shadows and animation loading.
- Locale-independent appearance DBC routing, a source-built WarcraftXL extension
  and verified no-backup migration from locale-specific patches. Asset preparation
  no longer takes `--locale`; runtime preparation requires `--appearance`.
- Hash-checked installation with backups and rollback.
- Wine/mtld3d compatibility settings.
- Tauren-only creation/selection framing correction; world and NPC scales unchanged.
- Synthetic tests, optional integration checks and source-only CI.
- Add lossless MPQ v2 packing for installed modern-race overlays, dual-reader
  verification and explicit no-backup deployment with private integrity reports.
