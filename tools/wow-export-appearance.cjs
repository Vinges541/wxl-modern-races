'use strict';
const fs = require('fs').promises;
const path = require('path');
const { workspace, buildIndex: selectBuild } = require('./export_config.cjs');
const ROOT = path.join(workspace(), 'assets', 'appearance');
async function run({ core, log, CASCRemote, db2 }) {
  await fs.mkdir(ROOT, { recursive: true });
  const source = new CASCRemote('us');
  await source.init();
  const index = selectBuild(source.builds);
  if (index < 0) throw new Error('Retail source unavailable');
  await source.load(index);
  core.view.casc = source;
  if (process.env.WXL_SCALE_TABLES === '1') {
    for (const name of ['CreatureModelData', 'CreatureDisplayInfo']) {
      const rows = [...(await db2[name].getAllRows()).entries()].map(([ID, row]) => ({ ID, ...row }));
      await fs.writeFile(path.join(ROOT, name + '.json'), JSON.stringify(rows));
      log.write('[WXL scale table] %s complete: %d rows', name, rows.length);
    }
    return;
  }
  if (process.env.WXL_NPC_TABLES === '1') {
    const name = 'CreatureDisplayInfoExtra';
    const rows = [...(await db2[name].getAllRows()).entries()].map(([ID, row]) => ({ ID, ...row }));
    await fs.writeFile(path.join(ROOT, name + '.json'), JSON.stringify(rows));
    log.write('[WXL NPC table] complete: %d rows', rows.length);
    return;
  }
  if (process.env.WXL_APPEARANCE_FILES === '1') {
    const requested = JSON.parse(await fs.readFile(path.join(ROOT, 'texture-requests.json'), 'utf8'));
    const pending = [...requested];
    const result = { requested: requested.length, complete: [], failed: [] };
    await fs.mkdir(path.join(ROOT, 'textures'), { recursive: true });
    await Promise.all(Array.from({ length: 4 }, async () => {
      while (pending.length) {
        const id = pending.shift();
        try {
          const dest = path.join(ROOT, 'textures', id + '.blp');
          try { await fs.access(dest); } catch (_) { await (await source.getFile(id)).writeToFile(dest); }
          result.complete.push(id);
        } catch (error) { result.failed.push({ id, error: String(error) }); }
        log.write('[WXL appearance textures] %d/%d', result.complete.length + result.failed.length, requested.length);
      }
    }));
    await fs.writeFile(path.join(ROOT, 'textures-status.json'), JSON.stringify(result, null, 2));
    return;
  }
  await fs.writeFile(path.join(ROOT, 'build.json'), JSON.stringify(source.builds[index], null, 2));
  for (const name of ['CharComponentTextureLayouts', 'CharComponentTextureSections', 'ChrModel', 'ChrModelMaterial', 'ChrRaceXChrModel', 'ChrCustomizationGeoset', 'ChrCustomizationOption', 'ChrCustomizationChoice', 'ChrCustomizationElement', 'ChrCustomizationMaterial', 'ChrModelTextureLayer', 'TextureFileData']) {
    try {
      const rows = [...(await db2[name].getAllRows()).entries()].map(([ID, row]) => ({ ID, ...row }));
      await fs.writeFile(path.join(ROOT, name + '.json'), JSON.stringify(rows, null, 2));
      log.write('[WXL appearance] %s: %d rows', name, rows.length);
    } catch (error) {
      await fs.writeFile(path.join(ROOT, name + '.error.txt'), error.stack || String(error));
    }
  }
  await fs.writeFile(path.join(ROOT, 'complete.json'), JSON.stringify({ completed: new Date().toISOString() }));
}
module.exports = { run };
