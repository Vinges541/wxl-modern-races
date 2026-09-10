# Build and installation

Run commands from the repository root after [setup](../README.md#setup).
Replace example paths with your own. Use a private workspace separate from
the source checkout and installed client; preparation does not modify the client.

## 1. Inputs

Use the versions and hashes in [dependencies.lock.json](../dependencies.lock.json).
You need raw Retail exports, original WotLK MPQs, locale-matched
`CharSections.dbc` and `CreatureDisplayInfoExtra.dbc`, and a StormLib shared library.
Extract the DBCs from the original client using an MPQ extraction tool.

Build StormLib from `deps/stormlib` in the pinned wxl-core checkout:

```sh
cmake -S /path/to/wxl-core/deps/stormlib -B /private/work/stormlib-build -DBUILD_SHARED_LIBS=ON
cmake --build /private/work/stormlib-build
```

The resulting library is `libstorm.dylib` on macOS or `libstorm.so` on Linux.
Keep the original MPQs unmodified; installed overlays are not source inputs.

## 2. Export assets

Export raw models with skins, skeletons, animations, textures and FileDataID
manifests. OBJ/glTF exports are not supported. Required workspace layout:

```text
work/assets/
  all_races_hd/status.json     complete 20-model export and build metadata
  all_races_hd/raw/            raw files and FileDataID manifests
  appearance/build.json       matching BuildConfig
  appearance/*.json           customization and NPC tables
  appearance/textures/*.blp   textures requested by the planners
```

The export adapter supports the bundled `app.nw` layout of wow.export 0.2.19:

```sh
python tools/install_export_hook.py --app-dir /path/to/app.nw
# Close wow.export before applying:
python tools/install_export_hook.py --app-dir /path/to/app.nw --apply
```

The adapter modifies the application bootstrap and saves `app.js.before-wxl-races`.
It is not an upstream plugin API. Unsupported bundles or conflicting hooks are
rejected. To remove the adapter, close wow.export and restore that backup.

Launch the exporter executable from a shell with these variables; Finder
launches may not inherit them:

```sh
export WXL_WORKSPACE=/private/work
export WXL_BUILD_CONFIG=c9fa1a64b0170829cc5c5c98c71025c3
export WXL_AUTO_EXPORT_HUMAN_MALE=1
```

Run the following passes, closing the exporter and clearing the previous
mode variables between launches. The adapter generates the manifests and IDs.

1. Set `WXL_EXPORT_ALL_RACES=1` to export all 20 model bundles.
2. Set `WXL_EXPORT_APPEARANCE=1` to export customization tables.
3. Set `WXL_EXPORT_APPEARANCE=1` and `WXL_NPC_TABLES=1` to export the NPC table.
4. Generate the texture request list:

   ```sh
   export WXL_DBC_DIR=/private/original-dbc
   python tools/plan_human_appearance.py
   python tools/plan_all_appearance.py
   python tools/plan_npc_appearance.py --all
   ```

5. Set `WXL_EXPORT_APPEARANCE=1` and `WXL_APPEARANCE_FILES=1` to export textures.

Every pass must use the same pinned BuildConfig. If it is no longer available
online, supply a matching saved export; the adapter will not substitute another
build. Legacy DBCs must match the installation locale; ruRU is the validated
profile, and other locales require testing.

## 3. Prepare models and textures

```sh
python tools/prepare_release.py --workspace /private/work \
  --client /path/to/client --dbc-dir /private/original-dbc \
  --stormlib /private/work/stormlib-build/libstorm.dylib --locale ruRU
```

This validates inputs and prints the plan. Add `--build` to execute.
`work/build/` must not already exist; after a failed attempt inspect its reports
and retry in a fresh workspace. Do not use Python `-O` or `PYTHONOPTIMIZE`, which
disable conversion checks.

Output: `work/build/release/`, including `release-manifest.json`. The pipeline
prepares models, player/NPC textures, helmet attachments and animation/shadow
compatibility changes. It does not generate world-scale overrides.

## 4. Prepare runtime patches

Supply the original game executable and the pinned WarcraftXL DLLs:

```sh
python tools/build_runtime.py --original-exe /private/original/Wow.exe \
  --core /private/upstream/WarcraftXL.dll --module /private/upstream/wxl-modern-m2.dll \
  --output /private/work/runtime
```

The output directory must be new. Input signatures and final hashes are checked
against the supported profile. This output contains a game executable; do not
publish it or the generated asset package.

## 5. Install and restore

Preview both packages:

```sh
python tools/install_release.py --client /path/to/client --package /private/work/runtime
python tools/install_release.py --client /path/to/client --package /private/work/build/release
```

Close WoW, then repeat each command with `--apply`. Applying is supported on
macOS/Linux hosts. For Wine + mtld3d, apply the [client settings](../CLIENT-SETTINGS.md).
The installer does not configure or launch Wine.

Use a client without conflicting higher-priority character overlays; the
installer leaves unknown patches in place. It verifies package paths and hashes,
backs up originals before writing and verifies the result. Reapplying an identical
package is a no-op.

Backups are kept under `client/DisabledPatches/ReleaseBackups/`. Installation
is not a multi-file transaction; use the reported checkpoint after a failure:

```sh
python tools/install_release.py --client /path/to/client --rollback /path/to/checkpoint
# Close WoW, then repeat with --apply to restore originals and remove new files.
```

Rollback refuses to overwrite later user changes and retains the backup.
