'use strict';
const fs = require('fs').promises;
const path = require('path');
const { workspace, buildIndex: selectBuild } = require('./export_config.cjs');
const ROOT = workspace();
const OUT = path.join(ROOT, 'assets/all_races_hd/raw');
const STATUS = path.join(ROOT, 'assets/all_races_hd/status.json');
const MODELS = [
  ['Human', 'Male', 1011653], ['Human', 'Female', 1000764],
  ['Orc', 'Male', 917116], ['Orc', 'Female', 949470],
  ['Dwarf', 'Male', 878772], ['Dwarf', 'Female', 950080],
  ['NightElf', 'Male', 974343], ['NightElf', 'Female', 921844],
  ['Scourge', 'Male', 959310], ['Scourge', 'Female', 997378],
  ['Tauren', 'Male', 968705], ['Tauren', 'Female', 986648],
  ['Gnome', 'Male', 900914], ['Gnome', 'Female', 940356],
  ['Troll', 'Male', 1022938], ['Troll', 'Female', 1018060],
  ['BloodElf', 'Male', 1100087], ['BloodElf', 'Female', 1100258],
  ['Draenei', 'Male', 1005887], ['Draenei', 'Female', 1022598],
];
async function run({ core, log, CASCRemote, M2Exporter }) {
  const status = { state: 'starting', models: [] };
  let previous = {};
  try { previous = JSON.parse(await fs.readFile(STATUS, 'utf8')); } catch (_) {}
  let writes = Promise.resolve();
  async function save() {
    const snapshot = JSON.stringify({ ...status, updatedAt: new Date().toISOString() }, null, 2);
    writes = writes.then(async () => {
      await fs.mkdir(path.dirname(STATUS), { recursive: true });
      await fs.writeFile(STATUS + '.tmp', snapshot);
      await fs.rename(STATUS + '.tmp', STATUS);
    });
    await writes;
  }
  try {
    await save();
    Object.assign(core.view.config, {
      exportDirectory: OUT, enableSharedChildren: true, enableSharedTextures: true,
      modelsExportTextures: true, modelsExportSkin: true, modelsExportSkel: true,
      modelsExportBone: true, modelsExportAnim: true, overwriteFiles: true,
      removePathSpaces: false, pathFormat: 'posix',
    });
    const source = new CASCRemote('us');
    await source.init();
    const buildIndex = selectBuild(source.builds);
    if (buildIndex < 0) throw new Error('Retail wow product not found');
    status.build = source.builds[buildIndex];
    status.state = 'loading-casc';
    await save();
    await source.load(buildIndex);
    core.view.casc = source;
    async function exportModel([race, sex, fileDataId]) {
      const modelPath = `Character/${race}/${sex}/${race}${sex}_HD.m2`;
      const old = previous.build?.BuildConfig === status.build.BuildConfig
        ? previous.models?.find(model => model.fileDataId === fileDataId && model.state === 'complete') : null;
      if (old) {
        status.models.push(old);
        await save();
        return;
      }
      const entry = { race, sex, fileDataId, modelPath, state: 'exporting' };
      status.models.push(entry);
      status.state = 'exporting';
      await save();
      try {
        const out = path.join(OUT, modelPath);
        await fs.mkdir(path.dirname(out), { recursive: true });
        const exporter = new M2Exporter(await source.getFile(fileDataId), [], fileDataId);
        const files = [];
        await exporter.exportRaw(out, { isCancelled: () => false }, files);
        entry.state = 'complete';
        entry.files = files;
        // Absolute paths remove ambiguity for shared children in a multi-model export.
        await fs.writeFile(out.replace(/\.m2$/i, '.files.manifest.json'), JSON.stringify({ files }, null, 2));
      } catch (error) {
        entry.state = 'failed';
        entry.error = error?.stack || String(error);
        log.write('[WXL races] %s %s failed: %s', race, sex, entry.error);
      }
      await save();
    }
    const pending = [...MODELS];
    await Promise.all(Array.from({ length: 4 }, async () => {
      while (pending.length) await exportModel(pending.shift());
    }));
    status.state = status.models.some(model => model.state === 'failed') ? 'partial' : 'complete';
    await save();
  } catch (error) {
    status.state = 'failed';
    status.error = error?.stack || String(error);
    await save();
    throw error;
  }
}
module.exports = { run };
