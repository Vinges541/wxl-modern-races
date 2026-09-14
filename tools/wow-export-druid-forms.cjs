'use strict';
// Uses the pinned wow.export raw M2 exporter, never a flattened OBJ/glTF export.
const fs = require('fs').promises;
const path = require('path');
const { workspace } = require('./export_config.cjs');
const BUILD = 'c9fa1a64b0170829cc5c5c98c71025c3';

async function run({ core, log, CASCRemote, M2Exporter, db2 }) {
  const root = workspace();
  const plan = JSON.parse(await fs.readFile(path.join(root, 'druid-plan.json'), 'utf8'));
  if (plan.kind !== 'wxl-druid-forms-plan' || plan.build?.BuildConfig !== BUILD ||
      process.env.WXL_BUILD_CONFIG !== BUILD || plan.build?.Product !== 'wow')
    throw Error('Explicit pinned druid plan and BuildConfig required');
  const out = path.join(root, 'assets/druid_forms/raw');
  await fs.mkdir(out, { recursive: true });
  const state = { state: 'starting', build: plan.build, models: [], textures: [] };
  const save = async () => {
    await fs.writeFile(path.join(root, 'druid-export-status.json.tmp'), JSON.stringify(state, null, 2));
    await fs.rename(path.join(root, 'druid-export-status.json.tmp'), path.join(root, 'druid-export-status.json'));
  };
  try {
    await save();
    const source = new CASCRemote('us');
    await source.init();
    // Explicit previously saved metadata permits the exact pinned donor even
    // after it disappears from the live version list. No latest-build fallback.
    source.builds = [plan.build];
    await source.load(0);
    core.view.casc = source;
    Object.assign(core.view.config, {
      exportDirectory: out, enableSharedChildren: true, enableSharedTextures: true,
      modelsExportTextures: true, modelsExportSkin: true, modelsExportSkel: true,
      modelsExportBone: true, modelsExportAnim: true, overwriteFiles: true,
      removePathSpaces: false, pathFormat: 'posix',
    });
    for (const id of [...new Set(plan.displays.map(r => r.fileDataId))]) {
      if (!Number.isSafeInteger(id) || id <= 0) throw Error('Invalid model FileDataID');
      state.state = 'model'; state.current = id; await save();
      const file = path.join(out, id + '.m2');
      const exporter = new M2Exporter(await source.getFile(id), [], id);
      const files = [];
      await exporter.exportRaw(file, { isCancelled: () => false }, files);
      await fs.writeFile(path.join(out, id + '.files.manifest.json'), JSON.stringify({files}, null, 2));
      state.models.push({ fileDataId: id, modelPath: id + '.m2', state: 'complete' });
      log.write('[WXL druid] model %d complete', id); await save();
    }
    await fs.mkdir(path.join(out, 'textures'), {recursive:true});
    for (const id of [...new Set(plan.displays.flatMap(r => r.textureFileDataIds).filter(Boolean))]) {
      if (!Number.isSafeInteger(id) || id <= 0) throw Error('Invalid texture FileDataID');
      state.state = 'texture'; state.current = id; await save();
      await (await source.getFile(id)).writeToFile(path.join(out, 'textures', id + '.blp'));
      state.textures.push(id);
    }
    const geosets = [...(await db2.CreatureDisplayInfoGeosetData.getAllRows()).entries()]
      .map(([ID, row]) => ({ID, ...row})).filter(row => plan.displays.some(r => r.displayId === row.CreatureDisplayInfoID));
    await fs.writeFile(path.join(root, 'druid-geosets.json'), JSON.stringify(geosets, null, 2));
    state.state = 'complete'; delete state.current; await save();
  } catch (error) {
    state.state = 'failed'; state.error = error.stack || String(error); await save();
    throw error;
  }
}
module.exports = { run };
