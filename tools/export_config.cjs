'use strict';
const path = require('path');
function workspace() {
  if (!process.env.WXL_WORKSPACE) throw new Error('Set WXL_WORKSPACE to a private export workspace');
  return path.resolve(process.env.WXL_WORKSPACE);
}
function buildIndex(builds) {
  const key = process.env.WXL_BUILD_CONFIG;
  if (!key || !/^[a-f0-9]{32}$/i.test(key)) throw new Error('Set WXL_BUILD_CONFIG to the pinned Retail BuildConfig');
  const index = builds.findIndex(b => b?.Product === 'wow' && b.BuildConfig === key);
  if (index < 0) throw new Error('Pinned Retail build is not offered by the source; do not silently use latest');
  return index;
}
module.exports = { workspace, buildIndex };
