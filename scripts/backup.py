#!/usr/bin/env python3
"""Make a private, consistent SQLite backup together with its encryption key."""
import argparse
import json
import os
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def backup(data_dir: Path, output: Path) -> None:
    data_dir = data_dir.resolve()
    output = output.resolve()
    database = data_dir / 'app.db'
    key = data_dir / 'master.key'
    if not database.is_file() or not key.is_file():
        raise SystemExit('找不到 app.db 或 master.key。请确认 --data-dir。')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an existing backup or follow an output symlink.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with tempfile.TemporaryDirectory(prefix='gatebox-backup-') as work:
            work_dir = Path(work)
            snap = work_dir / 'app.db'
            source = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
            dest = sqlite3.connect(snap)
            try:
                source.backup(dest)
                if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('数据库完整性检查未通过')
            finally:
                dest.close()
                source.close()
            os.chmod(snap, 0o600)
            metadata = work_dir / 'backup.json'
            metadata.write_text(json.dumps({
                'app': 'GateBox Lite', 'version': '0.1.0',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'warning': 'Contains private data and master encryption key',
            }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            with tarfile.open(output, 'w:gz') as archive:
                for path, name in [(snap, 'app.db'), (key, 'master.key'), (metadata, 'backup.json')]:
                    info = archive.gettarinfo(str(path), arcname=name)
                    info.mode = 0o600
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
                # Subsequent phases may use these directories; paths come only from fixed names.
                for name in ('configs', 'sources'):
                    directory = data_dir / name
                    if directory.is_dir():
                        for file in directory.rglob('*'):
                            if file.is_file() and not file.is_symlink():
                                archive.add(file, arcname=str(file.relative_to(data_dir)), recursive=False)
        os.chmod(output, 0o600)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(f'备份完成：{output}（包含私密数据和主钥，请勿公开）')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('GATEBOX_DATA_DIR', '/var/lib/gateboxlite')))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    backup(args.data_dir, args.output)
