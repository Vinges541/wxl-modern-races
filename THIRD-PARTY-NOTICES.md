# Licensing and provenance

Project source is distributed under GPL-3.0-or-later. See [LICENSE](LICENSE)
and the [license grant](README.md#license).

## WarcraftXL

- [wxl-core](https://github.com/WarcraftXL/wxl-core), commit
  `3990e09b5f80e77351d605dcd48d76b68ab2c2bf`: GPL-3.0-or-later.
  Copyright (C) 2026 WarcraftXL.
- tools/patch_wow.py is a Python adaptation of the base patcher behavior,
  including the PE import layout and edits from src/patcher/PeImage.cpp,
  GlueUnlock.cpp and NamedPatchArchives.cpp. It replaces the original C++
  implementation with Python parsing, explicit exact-build checks, backup and
  command-line handling. These modifications were made in 2026.
- [wxl-modern-m2](https://github.com/WarcraftXL/wxl-modern-m2), commit
  `7845be16924a1ec8644b957f26726a73d4a8556e`: GPL-3.0-or-later.
  Copyright (C) 2026 WarcraftXL. Used as the runtime dependency and as a
  reference for model layouts and the guarded bone-budget patch. Its DLL is
  supplied separately, not included in this source repository.

Modified upstream binaries remain subject to their license and source-distribution
obligations. This source repository does not include those binaries.

## wow.export

[wow.export](https://github.com/Kruithne/wow.export) 0.2.19 is an external MIT
tool. tools/wow-export-*.cjs and install_export_hook.py integrate with its
bundled internal interfaces; the upstream application is not shipped here.
Upstream notice:

```text
MIT License

Copyright (c) Kruithne <kruithne@gmail.com>
Copyright (c) Marlamin <marlamin@marlamin.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Other dependencies and excluded data

- StormLib 9.30: external MPQ reader; its license and dependencies are in
  wxl-core/deps/stormlib at the pinned core commit.
- Pillow 12.3.0 and optional Unicorn 2.1.4 are installed as separately licensed
  Python dependencies. Their distributions contain their respective notices.
- Wine, x87sidecar and mtld3d are external runtimes, not bundled dependencies
  that this repository installs or redistributes.
- World of Warcraft models, animations, textures, DBCs, archives, game
  executables and trademarks remain the property of their respective owners.
  Supply authorized inputs and do not publish generated game-data packages.
