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

Synthetic MPQ readback/installation tests can additionally use a local StormLib
shared library, without private game assets:

```sh
WXL_MPQ_STORMLIB=/path/to/libstorm.dylib python -m unittest discover -s tests -p test_mpq_packaging.py -v
```

Optional x86 loader emulation:

```sh
python -m pip install '.[emulation]'
WXL_CLIENT=/path/to/client python tools/check_anim_loader.py /path/to/runtime/Wow.exe
python tools/check_glue_preview.py /path/to/runtime/Wow.exe
python tools/check_appearance_redirect.py /path/to/wxl-modern-races.dll
```

Set `WXL_REDIRECT_DLL` to that built extension to include its ABI/relocation
checks in the test suite. MPQ migration tests use synthetic DBCs and the same
optional `WXL_MPQ_STORMLIB` setting. Emulation may require JIT permissions.
For gameplay changes, record the runtime,
source build and reproduction steps; check all affected race/sex variants,
animations, equipment and NPCs. Structural checks alone do not verify rendering.

## Safety and source publication

Keep preparation separate from deployment. Preserve path/hash validation,
explicit apply, backups and guarded rollback. Changes to supported builds or
binary signatures need new verification, not bypassed checks.

Review the Git diff and publication-check output before pushing. Do not commit
game data, executables, runtime DLLs, exports, logs, credentials or backups.
Publish source files only, not generated packages or an archive of the workspace.
