"""Restore the supplied runtime files from verified, compressed Git LFS parts."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

from filelock import FileLock


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def safe_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path == root:
        raise RuntimeError('运行数据清单含无效路径。')
    return path


def ensure_runtime_data(root=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    folder = root / 'runtime-data'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    targets = [(safe_path(root, item['path']), item) for item in manifest['files']]

    def missing():
        result = []
        for path, item in targets:
            if not path.exists():
                result.append((path, item))
            elif path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
                raise RuntimeError(f"运行数据与清单不匹配：{item['path']}；请保留自己的数据并检查版本。")
        return result

    if not missing():
        return 0
    cache = root / '.runtime-cache'
    cache.mkdir(exist_ok=True)
    with FileLock(str(cache / 'restore.lock'), timeout=600):
        pending = missing()
        if not pending:
            return 0
        print('正在还原并校验运行数据，首次启动需要等待片刻…', flush=True)
        with tempfile.TemporaryFile(dir=cache) as archive:
            total = hashlib.sha256()
            total_bytes = 0
            for part in manifest['parts']:
                path = safe_path(folder.resolve(), part['name'])
                if not path.is_file() or path.stat().st_size != part['bytes']:
                    raise RuntimeError('运行数据分卷缺失或未下载完整，请安装 Git LFS 并运行 git lfs pull。')
                current = hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        current.update(block)
                        total.update(block)
                        total_bytes += len(block)
                        archive.write(block)
                if current.hexdigest() != part['sha256']:
                    raise RuntimeError(f"运行数据分卷校验失败：{part['name']}。")
            if total_bytes != manifest['archive_bytes'] or total.hexdigest() != manifest['archive_sha256']:
                raise RuntimeError('运行数据压缩包校验失败。')
            archive.seek(0)
            with zipfile.ZipFile(archive) as package:
                if set(package.namelist()) != {item['path'] for _, item in targets}:
                    raise RuntimeError('运行数据压缩包文件清单不匹配。')
                for path, item in pending:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path = path.with_name(path.name + '.partial')
                    try:
                        actual = hashlib.sha256()
                        written = 0
                        with package.open(item['path']) as source, temp_path.open('wb') as dest:
                            for block in iter(lambda: source.read(1024 * 1024), b''):
                                dest.write(block)
                                actual.update(block)
                                written += len(block)
                        if written != item['bytes'] or actual.hexdigest() != item['sha256']:
                            raise RuntimeError(f"还原数据校验失败：{item['path']}。")
                        os.replace(temp_path, path)
                    finally:
                        temp_path.unlink(missing_ok=True)
        print('运行数据已还原，文件校验通过。', flush=True)
        return len(pending)
