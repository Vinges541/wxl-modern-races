"""Explicit private inputs for reproducible preparation; never discover server data."""
import os
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ.get('WXL_WORKSPACE', SOURCE_ROOT)).expanduser().resolve()


def dbc_path(name):
  directory = os.environ.get('WXL_DBC_DIR')
  if not directory:
    raise ValueError('Set WXL_DBC_DIR to a directory of original, locale-matched 3.3.5a DBC files')
  if Path(name).name != name:
    raise ValueError('Expected a DBC filename')
  return Path(directory).expanduser().resolve() / name


def client_path():
  value = os.environ.get('WXL_CLIENT')
  if not value:
    raise ValueError('Set WXL_CLIENT or pass --client; no implicit client writes')
  return Path(value).expanduser().resolve()
