# Contributing

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/),
such as `fix(loader): validate animation offsets` or `docs: clarify setup`.
Keep changes focused and add synthetic regression tests for code changes.

## Tests

```sh
python -m pip install '.[test]'
python -m unittest discover -s tests -v
python tools/check_publication.py
git diff --check
```

The default suite uses synthetic data. Private integration tests are skipped
unless `WXL_INTEGRATION=1` is set. They also require `WXL_WORKSPACE` (input/build
fixtures), `WXL_CLIENT` and `WXL_DBC_DIR`; binary tests may require the original
EXE/DLL backups referenced in those tests.

Optional x86 loader emulation:

```sh
python -m pip install '.[emulation]'
WXL_CLIENT=/path/to/client python tools/check_anim_loader.py /path/to/runtime/Wow.exe
```

Emulation may require JIT permissions. For gameplay changes, record the runtime,
source build and reproduction steps; check all affected race/sex variants,
animations, equipment and NPCs. Structural checks alone do not verify rendering.

## Safety and source publication

Keep preparation separate from deployment. Preserve path/hash validation,
explicit apply, backups and guarded rollback. Changes to supported builds or
binary signatures need new verification, not bypassed checks.

Review the Git diff and publication-check output before pushing. Do not commit
game data, executables, runtime DLLs, exports, logs, credentials or backups.
Publish source files only, not generated packages or an archive of the workspace.
