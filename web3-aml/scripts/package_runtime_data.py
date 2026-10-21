"""Rebuild compressed runtime parts after changing the supplied data files."""
import _bootstrap
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from api.runtime_data import digest


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / 'runtime-data'
    folder.mkdir(exist_ok=True)
    cache = root / '.runtime-cache'
    cache.mkdir(exist_ok=True)
    names = ['artifacts/evidence_scoring/features.npy',
             'artifacts/risk_scores/graph_statistics.parquet',
             'data/processed/raw_features.npy']
    manifest = {'format': 'verified_zip_parts_v1', 'files': [], 'parts': []}
    with tempfile.TemporaryFile(dir=cache) as archive:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
            for name in names:
                path = root / name
                manifest['files'].append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with path.open('rb') as source, package.open(info, 'w', force_zip64=True) as dest:
                    shutil.copyfileobj(source, dest, length=1024 * 1024)
                print('已压缩：' + name, flush=True)
        manifest['archive_bytes'] = archive.tell()
        archive.seek(0)
        total = hashlib.sha256()
        while block := archive.read(16 * 1024 * 1024):
            name = f"runtime-{len(manifest['parts']) + 1:03d}.part"
            (folder / name).write_bytes(block)
            total.update(block)
            manifest['parts'].append({'name': name, 'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
        manifest['archive_sha256'] = total.hexdigest()
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files': len(names), 'parts': len(manifest['parts']),
                      'original_bytes': sum(i['bytes'] for i in manifest['files']),
                      'compressed_bytes': manifest['archive_bytes']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
