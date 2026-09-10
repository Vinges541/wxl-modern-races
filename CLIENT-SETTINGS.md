# Wine/mtld3d settings

Requires Python 3.10+; no third-party Python packages are needed.

```sh
python tools/configure_client.py --client /path/to/client --dry-run
python tools/configure_client.py --client /path/to/client --check
# Close WoW before applying:
python tools/configure_client.py --client /path/to/client --apply
```

| File | Setting | Purpose |
| --- | --- | --- |
| WTF/Config.wtf | `shadowInstancing "0"` | Work around oversized creature shadows; shadows remain enabled. |
| WTF/Config.wtf | `gxWindow "0"` | Fullscreen mode. |
| WTF/Config.wtf | `gxApi "d3d9"` | D3D9, matching the launcher's `-d3d9` option. |
| mtld3d.conf | `shaderCache.enable = false` | Avoid texture corruption during shader pre-warm in mtld3d 0.7.0. |

These are compatibility workarounds, not renderer fixes, and may affect
performance or startup time. All other settings are preserved. The script
does not install Wine or modify the launcher.

Preview is the default. `--check` returns 0 when settings match, 1 when changes
are needed and 2 on error. Applying an already matching profile changes nothing.
Apply refuses while WoW is running or its process check is unavailable.

## Recovery

Originals and a manifest are saved in the client under
`DisabledPatches/ClientSettings/before-*/`. Backups may contain account names;
keep them private. File replacements are individually atomic, not a multi-file
transaction; a failed apply reports the backup location.

To undo, close WoW and restore originals at the relative paths in `manifest.json`.
For entries marked `existed: false`, remove the corresponding newly created file
instead. Check for later user edits before restoring or removing any file.
