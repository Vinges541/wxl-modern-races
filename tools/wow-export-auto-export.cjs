'use strict';

const fs = require('fs');
const fsp = fs.promises;
const path = require('path');

const { workspace, buildIndex: selectBuild } = require('./export_config.cjs');
const PROJECT_ROOT = workspace();
const EXPORT_ROOT = path.join(PROJECT_ROOT, 'assets', 'human_male', 'raw');
const STATUS_FILE = path.join(PROJECT_ROOT, 'assets', 'human_male', 'wow-export-status.json');
const MODEL_FILE_DATA_ID = 119940;
const MODEL_PATH = 'Character/Human/Male/HumanMale.m2';

async function writeStatus(status) {
  await fsp.mkdir(path.dirname(STATUS_FILE), { recursive: true });
  await fsp.writeFile(STATUS_FILE, JSON.stringify({
    updatedAt: new Date().toISOString(),
    ...status,
  }, null, 2) + '\n', 'utf8');
}

async function run({ core, log, CASCRemote, M2Exporter, db2 }) {
  if (process.env.WXL_EXPORT_APPEARANCE === '1')
    return require('./wow-export-appearance.cjs').run({ core, log, CASCRemote, db2 });
  if (process.env.WXL_EXPORT_ALL_RACES === '1')
    return require('./wow-export-all-races.cjs').run({ core, log, CASCRemote, M2Exporter });
  const status = {
    state: 'starting',
    region: 'us',
    product: 'wow',
    modelFileDataId: MODEL_FILE_DATA_ID,
    modelPath: MODEL_PATH,
    exportRoot: EXPORT_ROOT,
  };

  try {
    await writeStatus(status);
    log.write('[WXL races] automated Human Male export started');

    Object.assign(core.view.config, {
      exportDirectory: EXPORT_ROOT,
      enableSharedChildren: true,
      enableSharedTextures: true,
      modelsExportTextures: true,
      modelsExportSkin: true,
      modelsExportSkel: true,
      modelsExportBone: true,
      modelsExportAnim: true,
      overwriteFiles: true,
      removePathSpaces: false,
      pathFormat: 'posix',
    });

    const source = new CASCRemote(status.region);
    status.state = 'fetching-build-list';
    await writeStatus(status);
    await source.init();

    const buildIndex = selectBuild(source.builds);
    if (buildIndex < 0)
      throw new Error('Retail product "wow" was not returned by the Battle.net versions endpoint');

    const build = source.builds[buildIndex];
    status.state = 'loading-casc';
    status.build = {
      version: build.VersionsName,
      buildConfig: build.BuildConfig,
      cdnConfig: build.CDNConfig,
    };
    await writeStatus(status);
    await source.load(buildIndex);

    const modelOut = path.join(EXPORT_ROOT, MODEL_PATH);
    await fsp.mkdir(path.dirname(modelOut), { recursive: true });

    status.state = 'downloading-model';
    await writeStatus(status);
    const modelData = await source.getFile(MODEL_FILE_DATA_ID);

    status.state = 'exporting-dependencies';
    await writeStatus(status);
    const manifest = [];
    const helper = { isCancelled: () => false };
    const exporter = new M2Exporter(modelData, [], MODEL_FILE_DATA_ID);
    await exporter.exportRaw(modelOut, helper, manifest);

    status.state = 'complete';
    status.modelOutput = modelOut;
    status.manifestOutput = modelOut.replace(/\.m2$/i, '.manifest.json');
    status.exportedFileCount = manifest.length;
    status.exportedFiles = manifest;
    await writeStatus(status);
    log.write('[WXL races] automated Human Male export complete (%d files)', manifest.length);
  } catch (error) {
    status.state = 'failed';
    status.error = error?.stack || String(error);
    await writeStatus(status);
    log.write('[WXL races] automated Human Male export failed: %s', status.error);
    throw error;
  }
}

module.exports = { run };
