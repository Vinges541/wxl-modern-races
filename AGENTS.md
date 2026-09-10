# Agent instructions

- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
  `<type>[optional scope][!]: <description>`, e.g. `fix(loader): validate offsets`.
  Mark breaking changes with `!` or a `BREAKING CHANGE:` footer.
- Read README.md, docs/BUILD.md and docs/COMPATIBILITY.md before pipeline changes.
- Keep game data, binaries, exports, logs, credentials and backups out of Git.
  `assets/`, `build/`, `cache/`, `vendor/` and `_local/` are private directories.
- Preparation writes only to a fresh workspace. Deploy packages with
  `install_release.py --apply`; manage settings with `configure_client.py --apply`.
  Preserve path/hash checks, process checks, backups and guarded rollback.
- Never bypass exact-build signatures or change world scale to fix camera framing.
- Follow the test and publication checks in CONTRIBUTING.md. Default tests must
  use synthetic data; private fixtures require explicit opt-in and paths.
- Distinguish offline checks from in-game validation. Keep documentation focused
  on current behavior and usage, without task history or unrelated projects.
- Do not push or publish without an explicit user request.
