"""Plan druid forms from original build-12340 MPQs and pinned Retail tables."""
import argparse
import json
from pathlib import Path
import sys

from pack_mpq import Storm, no_links, save_json
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wxl_races.druids import make_plan


def original_table(client, library, name):
    data = no_links(client / 'Data')
    # These tables have no localized text. Their latest stock copy is identical
    # across locales; never read third-party overlays as an original input.
    archives = [data / n for n in ('patch-3.MPQ', 'patch-2.MPQ', 'patch.MPQ',
                                   'lichking.MPQ', 'expansion.MPQ', 'common-2.MPQ', 'common.MPQ')]
    for locale in sorted(data.iterdir()):
        if len(locale.name) == 4 and locale.name.isalpha() and locale.is_dir():
            archives.extend(locale / n for n in (f'patch-{locale.name}-3.MPQ', f'patch-{locale.name}-2.MPQ',
                                                 f'patch-{locale.name}.MPQ', f'locale-{locale.name}.MPQ'))
    storm = Storm(library)
    for archive in archives:
        no_links(archive)
        if not archive.is_file():
            continue
        handle = storm.open(archive)
        try:
            try:
                return storm.read(handle, 'DBFilesClient/' + name)
            except OSError:
                pass
        finally:
            storm.close(handle)
    raise FileNotFoundError(name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--retail-tables', type=Path, required=True)
    p.add_argument('--stormlib', type=Path, required=True)
    p.add_argument('--workspace', type=Path, required=True)
    a = p.parse_args()
    workspace = no_links(a.workspace)
    if workspace.exists():
        p.error('Use a fresh private workspace')
    source = no_links(a.retail_tables)
    tables = {name: original_table(a.client.resolve(), a.stormlib, name)
              for name in ('CreatureDisplayInfo.dbc', 'CreatureModelData.dbc')}
    plan = make_plan(tables['CreatureDisplayInfo.dbc'], tables['CreatureModelData.dbc'],
                     json.loads((source/'CreatureDisplayInfo.json').read_text()),
                     json.loads((source/'CreatureModelData.json').read_text()),
                     json.loads((source/'build.json').read_text()))
    workspace.mkdir(parents=True)
    (workspace/'original-dbc').mkdir()
    for name, data in tables.items():
        (workspace/'original-dbc'/name).write_bytes(data)
    save_json(workspace/'druid-plan.json', plan)
    print(f"Planned {len(plan['displays'])} displays, {len({r['fileDataId'] for r in plan['displays']})} source models")


if __name__ == '__main__':
    main()
