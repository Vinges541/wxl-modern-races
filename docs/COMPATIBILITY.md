# Compatibility

Experimental alpha targeting WotLK 3.3.5a build 12340. Use the versions and
hashes in [dependencies.lock.json](../dependencies.lock.json).

| Area | Support and limitations |
| --- | --- |
| Races | Both sexes of all ten WotLK races are prepared. Not every customization, animation or equipment combination has been tested in-game. |
| NPC appearance | 13,706 atlases converted; 15 unmatched records remain. |
| Death knights | 384 extra face rows use corresponding ordinary HD faces. |
| Customization | Modern-only options, FacePose variants and Retail equipment are not fully ported. |
| Textures | Composite textures use WotLK-compatible dimensions, not full Retail resolution. |
| Elf eyes | Optional Primalist eye effects are excluded; ordinary eye materials remain. |
| Undead female jaw | Uses the intact-jaw default, without a full jaw-customization mapping. |
| Tauren | Character-selection camera framing needs review. World-scale overrides are not included. |
| Locales | ruRU validated; other locales require testing. |

The tested game runtime is macOS with Wine cx-26.3.0-4, x87sidecar 1.6.0 and
mtld3d 0.7.0. Oversized shadows and shader-cache texture corruption require
the [client settings workarounds](../CLIENT-SETTINGS.md).

Offline asset checks and animation-loader emulation do not replace gameplay
testing. The [source CI](https://github.com/Vinges541/wxl-modern-races/actions)
covers macOS/Linux and Python 3.10, 3.12 and 3.14 without game data.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for tests and private fixtures.
