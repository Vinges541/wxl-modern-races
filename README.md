# wxl-modern-races

Tools for preparing modern player-race models for **World of Warcraft 3.3.5a,
build 12340**, with [WarcraftXL](https://github.com/WarcraftXL/wxl-core).
Supports both sexes of all ten WotLK races, NPC appearance textures and helmet
attachment adaptation.

**Experimental alpha.** Some customization and rendering limitations remain;
see [compatibility](docs/COMPATIBILITY.md). Supply your own client and exports:
this repository contains source code, not game assets or executables.

## Setup

Python 3.10–3.14; tested on macOS and Linux. Run from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[prepare,test]'
wxl-races --help
```

## Usage

Follow the [build guide](docs/BUILD.md) to export source assets with
[wow.export](https://github.com/Kruithne/wow.export), prepare the models and
runtime patches, then install them into an existing client. Supported versions
and hashes are in [dependencies.lock.json](dependencies.lock.json).

Installation previews changes by default and supports backups and rollback.
For Wine + mtld3d, also apply the [client compatibility settings](CLIENT-SETTINGS.md).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests and commit conventions,
[SECURITY.md](SECURITY.md) for safety and vulnerability reporting, and
[CHANGELOG.md](CHANGELOG.md) for changes.

## License

[GPL-3.0-or-later](LICENSE): GNU GPL version 3 or, at your option, any later
version. Provided without warranty. See [third-party notices](THIRD-PARTY-NOTICES.md)
for attribution and dependency licenses. Game assets are not covered by this
license. Not affiliated with or endorsed by Blizzard.
