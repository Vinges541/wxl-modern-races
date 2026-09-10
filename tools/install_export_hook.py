"""Optional wow.export 0.2.19 adapter: preview by default, retains the original app.js."""
import argparse
import json
from pathlib import Path
import sys
from configure_client import atomic_write

MARKER = '// wxl-modern-races export adapter v1'
ANCHOR = '  modules.source_select.setActive();\n})();'


def hook(text, module_path):
  import_line = 'const adapter = require(' + json.dumps(str(module_path.resolve())) + ');'
  if MARKER in text:
    if text.count(MARKER) != 1 or import_line not in text:
      raise ValueError('Existing adapter points elsewhere; restore original app.js before reinstalling')
    return text
  if 'WXL_AUTO_EXPORT_HUMAN_MALE' in text:
    raise ValueError('Legacy export hook found; restore the original app.js before installing this adapter')
  if text.count(ANCHOR) != 1:
    raise ValueError('Unsupported wow.export bundle; expected one 0.2.19 bootstrap anchor')
  injection = '''  modules.source_select.setActive();
  // wxl-modern-races export adapter v1
  if (process.env.WXL_AUTO_EXPORT_HUMAN_MALE === "1") {
    const adapter = require(MODULE_PATH);
    await adapter.run({core, log, CASCRemote: require_casc_source_remote(),
                       M2Exporter: require_M2Exporter(), db2: require_db2()});
  }
})();'''.replace('MODULE_PATH', json.dumps(str(module_path.resolve())))
  return text.replace(ANCHOR, injection)


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--app-dir', type=Path, required=True, help='app.nw directory containing package.json and src/app.js')
  parser.add_argument('--apply', action='store_true', help='close wow.export before applying')
  args = parser.parse_args(argv)
  try:
    root = args.app_dir.expanduser()
    if json.loads((root / 'package.json').read_text())['version'] != '0.2.19':
      raise ValueError('This adapter is only verified against wow.export 0.2.19')
    script = root / 'src/app.js'
    if script.is_symlink():
      raise ValueError('Refusing symlink')
    before = script.read_bytes()
    after = hook(before.decode(), Path(__file__).with_name('wow-export-auto-export.cjs')).encode()
    print(f'Adapter change needed: {after != before}; apply: {args.apply}')
    if args.apply and after != before:
      backup = script.with_suffix('.js.before-wxl-races')
      with backup.open('xb') as stream:
        stream.write(before)
      atomic_write(script, after, script.stat().st_mode & 0o777)
    return 0
  except (OSError, ValueError, KeyError) as exc:
    print(f'error: {exc}', file=sys.stderr)
    return 2


if __name__ == '__main__':
  raise SystemExit(main())
