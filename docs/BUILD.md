# Build and installation

Run commands from the repository root after [setup](../README.md#setup).
Replace example paths with your own. Use a private workspace separate from
the source checkout and installed client; preparation does not modify the client.

## 1. Inputs

Use the versions and hashes in [dependencies.lock.json](../dependencies.lock.json).
You need raw Retail exports, original WotLK build-12340 MPQs,
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
build. Appearance DBCs must match client build 12340. These two tables contain
texture paths and appearance values, not translated text. The package has no
locale-specific destination; ruRU is the in-game-tested locale.

## 3. Prepare models and textures

```sh
python tools/prepare_release.py --workspace /private/work \
  --client /path/to/client --dbc-dir /private/original-dbc \
  --stormlib /private/work/stormlib-build/libstorm.dylib
```

This validates inputs and prints the plan. Add `--build` to execute.
`work/build/` must not already exist; after a failed attempt inspect its reports
and retry in a fresh workspace. Do not use Python `-O` or `PYTHONOPTIMIZE`, which
disable conversion checks.

Output: `work/build/release/`, including `release-manifest.json`. The pipeline
prepares models, player/NPC textures, helmet attachments and animation/shadow
compatibility changes. It does not generate world-scale overrides.
The two appearance DBCs are stored under `WXL/ModernRaces/DBFilesClient/`
inside the shared patch. There is no `--locale` option or locale patch output.

## 4. Prepare runtime patches

First build the appearance extension using Clang and `lld-link`, with the
pinned wxl-core `include/` directory. No Windows SDK, CRT or DLL imports are
needed. The verified compiler versions are recorded in the lockfile; another
toolchain's differing output is refused until separately verified. The output
file must be new and its parent directory must already exist:

```sh
python tools/build_appearance_redirect.py --sdk /private/upstream/wxl-core/include \
  --output /private/work/wxl-modern-races.dll
```

Supply that extension, the original game executable and pinned WarcraftXL DLLs:

```sh
python tools/build_runtime.py --original-exe /private/original/Wow.exe \
  --core /private/upstream/WarcraftXL.dll --module /private/upstream/wxl-modern-m2.dll \
  --appearance /private/work/wxl-modern-races.dll \
  --output /private/work/runtime
```

The output directory must be new. Input signatures and final hashes are checked
against the supported profile. This output contains a game executable; do not
publish it or the generated asset package.

The extension registers exact-name redirects for `CharSections.dbc` and
`CreatureDisplayInfoExtra.dbc` on the verified `Io.FileOpen` hook point. WarcraftXL
loads and arms these hooks synchronously before engine initialisation. This
does not depend on the pinned core's deferred storage-service thread. The native
reader still handles archives, compression, flags and file handles. Explicit
archive requests and every other path are passed through unchanged.

The runtime includes a Tauren-only creation/selection preview correction. For
an existing installation of the previous verified runtime, upgrade just this
fix without rebuilding assets:

```sh
python tools/install_glue_preview.py --client /path/to/client
# Close WoW; deliberately replace only Wow.exe without a rollback copy:
python tools/install_glue_preview.py --client /path/to/client \
  --apply --no-backup --report /private/reports/tauren-preview.json
```

The report directory must exist. Unknown EXEs or runtime DLLs are refused;
reapplying is a no-op. This changes two GLUE-only transform calls, not the shared
world transform function, M2 geometry, DBC scales, animation code or settings.

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

## 6. Lossless MPQ packing

To compress an already installed loose `Data/Patch-ModernRaces-HD.MPQ/`
without changing any file bytes, use a fresh private workspace and StormLib
9.30. No game or Wine process is launched:

```sh
python tools/pack_mpq.py build --client /path/to/client \
  --workspace /private/work/races-mpq --stormlib /path/to/libstorm.dylib
python tools/pack_mpq.py install --client /path/to/client \
  --workspace /private/work/races-mpq --stormlib /path/to/libstorm.dylib
```

The second command previews installation. The supported runtime must match the
verified hashes in `dependencies.lock.json`, including the named-patch wildcard
edit. Every input path, file size and SHA-256 is checked against both StormLib
readback and an independent MPQ decoder. This includes case-insensitive lookup,
classic hash collisions, exact listfile coverage, sector bounds and compression.

The profile uses MPQ v2 (header version 1), as the original WotLK archives do:
4096-byte sectors, lossless zlib, neutral locale, no file encryption or delta
patches. Archives may exceed 2 GiB. Parts are split only to keep offsets below
4 GiB or the tool's 60,000-resource limit. These are conservative profile bounds,
not a claim about the largest archive the game can read. All parts are named
`Patch-ModernRaces-HD-001.MPQ`, `-002.MPQ`, etc.; each resource occurs once.
Installation rejects another patch interleaving this group and its original
name, so the group's position relative to other patches is preserved.

Close WoW before applying. To deliberately discard the replaced loose files
without keeping a rollback copy, create a private report directory and run:

```sh
python tools/pack_mpq.py install --client /path/to/client \
  --workspace /private/work/races-mpq --stormlib /path/to/libstorm.dylib \
  --apply --discard-loose --report /private/reports/modern-races.json
```

This operation is intentionally irreversible. It verifies the source again,
creates the parts exclusively on the same filesystem, checks them in place,
then removes only the replaced loose directory and temporary build. The report
and adjacent `modern-races.manifest.json` retain hashes, not game resources.
If installation is interrupted, keep the loose directory and build workspace
until the reported state is inspected; do not launch a partially installed game.
Recheck installed archives later with:

```sh
python tools/pack_mpq.py verify --client /path/to/client \
  --manifest /private/reports/modern-races.manifest.json \
  --stormlib /path/to/libstorm.dylib
```

This tool packs only the root modern-races overlay. Locale, equipment and other
patches, executables, runtime and settings are not changed. Do not direct the
loose-package installer into compressed archives; prepare future asset changes
in a fresh private tree and verify/repack them. Offline verification does not
replace an in-game load/rendering check.

## 7. Migrate an existing locale patch

For an already installed client, build a small shared appearance archive instead
of repacking the large HD archives. Build the extension as above, then use the
existing patched DBC directory as input (not original unmodified DBCs):

```sh
python tools/install_appearance_redirect.py build \
  --tables /path/to/client/Data/ruRU/patch-ruRU-ModernRaces.MPQ/DBFilesClient \
  --extension /private/work/wxl-modern-races.dll \
  --workspace /private/work/appearance-package --stormlib /path/to/libstorm.dylib
python tools/install_appearance_redirect.py install --client /path/to/client \
  --workspace /private/work/appearance-package --stormlib /path/to/libstorm.dylib
```

The input path above is an example; neither the extension nor the output package
uses a locale. The package contains `Data/Patch-ModernRaces-Appearance.MPQ` and
`Extensions/wxl-modern-races/wxl-modern-races.dll`. Close WoW, then repeat the
install command with `--apply --no-backup --report /private/reports/appearance.json`.
The report parent must exist. No EXE, existing HD archive, configuration or other
extension is replaced. Only known locale patch directories containing exactly
the same two tables are removed, after native and independent archive readback.
Unknown contents, changed files, symlinks and occupied differing destinations
are refused. Interrupted multi-file installations require inspecting the private
report before launching; no rollback copy is created. A matching completed
installation is a no-op. The verified package can be removed after deployment.

Old standard-path DBC entries inside existing HD archives may remain: redirected
requests use only the unique namespaced copies. New full builds omit those old
entries entirely. The migration does not claim other client locales have been
tested in-game.

## 8. Druid forms

This optional package is separate from the 20 player-race models. It preserves
WotLK form/display IDs and color selection, using corresponding displays in the
pinned Retail build. It does not unlock Retail-only artifact or barber options.
NPCs using those same form display IDs also receive the new appearance; other
display records and original model paths are unchanged.

Export `CreatureDisplayInfo.json` and `CreatureModelData.json` with the existing
appearance adapter (`WXL_EXPORT_APPEARANCE=1`, `WXL_SCALE_TABLES=1`). Keep the
matching `build.json` beside them. Then create a fresh private workspace:

```sh
python tools/plan_druid_forms.py --client /path/to/client \
  --retail-tables /private/work/assets/appearance --stormlib /path/to/libstorm.dylib \
  --workspace /private/druids
```

Close the exporter, clear other export-mode variables, and run the configured
wow.export adapter with `WXL_WORKSPACE=/private/druids`, the pinned
`WXL_BUILD_CONFIG`, `WXL_AUTO_EXPORT_HUMAN_MALE=1` and `WXL_EXPORT_DRUID_FORMS=1`.
This pass uses the explicit saved build metadata even if the live build list has
changed; the matching CDN data must remain available. It never substitutes latest.
Wait for `druid-export-status.json` to report `complete`.

With the pinned SDK, Clang/lld-link, Pillow and the optional Unicorn dependency:

```sh
python tools/druid_forms.py build --workspace /private/druids \
  --output /private/druids-package --sdk /path/to/wxl-core/include \
  --stormlib /path/to/libstorm.dylib
python tools/install_release.py --client /path/to/client \
  --package /private/druids-package --stormlib /path/to/libstorm.dylib
```

The builder checks model/skin references, texture decoding, shadow indices, DBC
changes and the extension ABI, then reads every MPQ member through two readers.
After WoW is closed, add `--apply --no-backup --report /private/reports/druids.json`
to the installation command. The report directory must exist. This new-only
installer refuses differing existing files and leaves EXE, race/equipment
archives, other extensions and settings intact. An interrupted installation must
be inspected before launch; there is no automatic rollback.

Transfer both files together to an already prepared build-12340 runtime:

- `Data/Patch-ModernRaces-DruidForms.MPQ`
- `Extensions/wxl-druid-forms/wxl-druid-forms.dll`

The extension redirects only `CreatureDisplayInfo.dbc` and `CreatureModelData.dbc`
to `WXL/DruidForms/DBFilesClient/`. Only the 30 selected displays' model references
change; new model rows retain the original scale/collision fields. All original
model rows remain intact. This cannot be combined blindly with another project
that overrides those same tables. Check each form in-game, including changing
forms, moving, attacking/casting, swimming/flying and shadows, before treating
the package as gameplay-verified.

## 9. Update existing Undead torsos

Full preparation includes the default Bony back for both sexes. Older packages
left its geoset 1901 hidden by the Wrath character selector. Update an installed
loose or packed HD package without rebuilding its textures:

```sh
python tools/undead_torso.py --client /path/to/client \
  --output /private/undead-torso-package --stormlib /path/to/libstorm.dylib
python tools/install_release.py --client /path/to/client \
  --package /private/undead-torso-package --stormlib /path/to/libstorm.dylib
```

Close WoW, then add `--apply --no-backup --report /private/reports/undead-torso.json`
to the installation command. Output/report paths must be new. This adds only
`Data/Patch-ModernRaces-UndeadTorso.MPQ`: each of its 14 SKIN profiles differs from
the installed source by exactly two geoset-ID bytes. Vertex/UV data, draw/shadow
indices, models, textures, animations, settings and other archives remain intact.
Both archive readers must reproduce the exact repair; conflicting character
overlays and differing existing destinations are refused. Check both sexes,
robes and ordinary chest armor in-game. Remove this overlay before a later full
HD rebuild: it must not override newer SKIN profiles.
