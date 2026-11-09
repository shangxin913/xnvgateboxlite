import importlib.util
import os
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gatebox_backup', ROOT / 'scripts' / 'backup.py')
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_initial_schema_constraints():
    con = sqlite3.connect(':memory:')
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript((ROOT / 'migrations/001_initial.sql').read_text())
    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert con.execute('PRAGMA foreign_key_check').fetchall() == []
    assert con.execute("SELECT is_enabled,include_in_subscription FROM egresses WHERE kind='local'").fetchone() == (0, 0)
    assert con.execute('SELECT sum(is_enabled) FROM schedules').fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO egresses(kind,name,node_id) VALUES('local','duplicate',NULL)")
    con.close()


def test_backup_keeps_key_and_snapshot_private(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    con = sqlite3.connect(data / 'app.db')
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE sample (value TEXT)')
    con.execute('INSERT INTO sample VALUES (?)', ('private-value',))
    con.commit()
    (data / 'master.key').write_bytes(b'test-key-not-real-secret')
    output = tmp_path / 'backup.tar.gz'
    module.backup(data, output)
    assert os.stat(output).st_mode & 0o777 == 0o600
    with tarfile.open(output) as archive:
        assert set(archive.getnames()) == {'app.db', 'master.key', 'backup.json'}
        key_stream = archive.extractfile('master.key')
        assert key_stream is not None
        assert key_stream.read() == b'test-key-not-real-secret'
        for member in archive.getmembers():
            assert member.mode == 0o600
        snapshot = tmp_path / 'restored.db'
        database_stream = archive.extractfile('app.db')
        assert database_stream is not None
        snapshot.write_bytes(database_stream.read())
    restored = sqlite3.connect(snapshot)
    assert restored.execute('SELECT value FROM sample').fetchone()[0] == 'private-value'
    restored.close()
    con.close()
    with pytest.raises(FileExistsError):
        module.backup(data, output)


def test_shell_script_syntax():
    result = subprocess.run(['bash', '-n', str(ROOT / 'scripts/install.sh'), str(ROOT / 'scripts/uninstall.sh')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
