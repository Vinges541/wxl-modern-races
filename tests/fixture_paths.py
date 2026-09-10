"""Private integration fixtures are explicit; the default suite needs no game files."""
import os
from pathlib import Path
import unittest

integration = unittest.skipUnless(os.environ.get('WXL_INTEGRATION') == '1', 'private integration test (opt-in)')


def fixture_root():
  return Path(os.environ['WXL_WORKSPACE']).expanduser().resolve()


def client_root():
  return Path(os.environ['WXL_CLIENT']).expanduser().resolve()


def dbc_root():
  return Path(os.environ['WXL_DBC_DIR']).expanduser().resolve()
