from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_private_receipt_cannot_return_after_logout():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node 22+ is optional and required only for frontend ESM regression')
    assert node is not None
    result = subprocess.run(
        [node, '--experimental-default-type=module', str(ROOT / 'tests/frontend_security.mjs')],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert 'passed' in result.stdout
