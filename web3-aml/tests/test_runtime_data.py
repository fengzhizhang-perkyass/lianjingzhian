import hashlib
import io
import json
import zipfile

import pytest

from api.runtime_data import ensure_runtime_data


def package(root):
    files = {'data/processed/raw_features.npy': b'\x93NUMPY\x00' * 50,
             'artifacts/evidence_scoring/features.npy': b'evidence-array' * 100}
    folder = root / 'runtime-data'
    folder.mkdir()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    data = buffer.getvalue()
    manifest = {'files': [{'path': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                          for name, value in files.items()], 'parts': [],
                'archive_bytes': len(data), 'archive_sha256': hashlib.sha256(data).hexdigest()}
    split = len(data) // 2
    for index, block in enumerate([data[:split], data[split:]], 1):
        name = f'runtime-{index:03d}.part'
        (folder / name).write_bytes(block)
        manifest['parts'].append({'name': name, 'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return files


def test_restore_and_reuse_without_archives(tmp_path):
    files = package(tmp_path)
    assert ensure_runtime_data(tmp_path) == 2
    assert all((tmp_path / name).read_bytes() == value for name, value in files.items())
    for part in (tmp_path / 'runtime-data').glob('*.part'):
        part.unlink()
    assert ensure_runtime_data(tmp_path) == 0


def test_missing_lfs_parts_have_actionable_error(tmp_path):
    package(tmp_path)
    (tmp_path / 'runtime-data/runtime-001.part').write_text('version https://git-lfs.github.com/spec/v1\n')
    with pytest.raises(RuntimeError, match='git lfs pull'):
        ensure_runtime_data(tmp_path)
    assert not (tmp_path / 'data/processed/raw_features.npy').exists()


def test_corrupted_part_is_rejected_before_writing_data(tmp_path):
    package(tmp_path)
    path = tmp_path / 'runtime-data/runtime-001.part'
    block = bytearray(path.read_bytes())
    block[-1] ^= 1
    path.write_bytes(block)
    with pytest.raises(RuntimeError, match='分卷校验失败'):
        ensure_runtime_data(tmp_path)
    assert not (tmp_path / 'data/processed/raw_features.npy').exists()


def test_existing_mismatched_data_is_not_overwritten(tmp_path):
    package(tmp_path)
    path = tmp_path / 'data/processed/raw_features.npy'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'my-other-data')
    with pytest.raises(RuntimeError, match='运行数据与清单不匹配'):
        ensure_runtime_data(tmp_path)
    assert path.read_bytes() == b'my-other-data'
