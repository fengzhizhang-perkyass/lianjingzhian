"""Explicit offline preparation and verification of frozen two-chain releases.

Base asset verification is stdlib-only. Optional pipeline verification loads
numeric state/trace metadata without models, construction, labels or training.
The web launcher verifies prepared state; preparation is a CLI maintenance task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ('bitcoin', 'ethereum')
COMMON_ASSETS = {
    'risk_scores.parquet', 'address_to_idx.json', 'idx_to_address.json',
    'outgoing_neighbors.pkl', 'incoming_neighbors.pkl',
}
EXTRA_ASSETS = {
    'bitcoin': {'schema.json'},
    'ethereum': {'features.npy', 'embeddings.npy', 'addresses.npy',
                 'feature_names.json', 'edge_evidence.sqlite', 'graph_statistics.parquet'},
}


class ReleaseVerificationError(RuntimeError):
    """A prepared release or one of its declared assets is unavailable/changed."""


def _contained_file(base: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ReleaseVerificationError(f'清单中的文件路径无效：{name!r}')
    base = base.resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base):
        raise ReleaseVerificationError(f'清单中的文件路径越界：{name}')
    if not path.is_file():
        raise ReleaseVerificationError(f'缺少运行文件：{path}')
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _check_asset(base: Path, name: str, expected: str, size=None) -> int:
    if not isinstance(expected, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
        raise ReleaseVerificationError(f'文件SHA256字段无效：{name}')
    path = _contained_file(base, name)
    actual_size = path.stat().st_size
    if size is not None:
        if type(size) is not int or size < 0 or actual_size != size:
            raise ReleaseVerificationError(f'运行文件大小与清单不符：{path}')
    if _sha256(path) != expected.lower():
        raise ReleaseVerificationError(f'运行文件SHA256与清单不符：{path}')
    return actual_size


def verify_release(root: Path, dataset_id: str, *, check_sources: bool = False,
                   check_pipeline: bool = False) -> dict:
    """Check prepared files only; raise ReleaseVerificationError on any mismatch.

    Supports BTC's runtime_hashes and ETH's runtime_assets without converting or
    rewriting either manifest. Optional source checks read all declared original
    inputs (including large features/CSV), and can take longer than startup.
    Passing verification does not replace model-parity or API acceptance tests.
    """
    if dataset_id not in DATASETS:
        raise ReleaseVerificationError(f'未知数据集：{dataset_id}')
    root = Path(root).resolve()
    folder = root / 'artifacts' / 'datasets' / dataset_id / 'current'
    manifest_path = folder / 'manifest.json'
    if not manifest_path.is_file():
        raise ReleaseVerificationError(
            f'{dataset_id}尚未准备：缺少{manifest_path}；'
            f'请先运行 python scripts/prepare_v3_runtime.py --dataset {dataset_id}')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ReleaseVerificationError(f'无法读取运行清单：{manifest_path}') from exc
    if not isinstance(manifest, dict) or manifest.get('dataset_id') != dataset_id:
        raise ReleaseVerificationError(f'运行清单的数据集身份不匹配：{manifest_path}')
    for key in ('fingerprint', 'risk_revision', 'feature_revision', 'graph_revision'):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ReleaseVerificationError(f'运行清单缺少版本字段：{key}')
    entries = {}
    for field in ('runtime_hashes', 'runtime_assets'):
        values = manifest.get(field, {})
        if not isinstance(values, dict):
            raise ReleaseVerificationError(f'运行清单{field}必须是文件映射')
        for name, value in values.items():
            if field == 'runtime_assets':
                if not isinstance(value, dict) or 'sha256' not in value or 'bytes' not in value:
                    raise ReleaseVerificationError(f'运行资产记录不完整：{name}')
                record = (value['sha256'], value['bytes'])
            else:
                record = (value, None)
            if name in entries and entries[name][0] != record[0]:
                raise ReleaseVerificationError(f'两种运行清单对同一文件的SHA256不一致：{name}')
            if name not in entries or record[1] is not None:
                entries[name] = record
    missing = sorted((COMMON_ASSETS | EXTRA_ASSETS[dataset_id]) - entries.keys())
    if missing:
        raise ReleaseVerificationError('运行清单未覆盖必需文件：' + ', '.join(missing))
    total_bytes = 0
    for name, (expected, size) in sorted(entries.items()):
        total_bytes += _check_asset(folder, name, expected, size)
    source_count = 0
    if check_sources:
        sources = manifest.get('source_hashes')
        if not isinstance(sources, dict) or not sources:
            raise ReleaseVerificationError('运行清单缺少source_hashes输入溯源记录')
        for name, expected in sorted(sources.items()):
            _check_asset(root, name, expected)
            source_count += 1
    result = {
        'dataset_id': dataset_id, 'asset_checks_passed': True,
        'release': str(folder), 'runtime_files_checked': len(entries),
        'runtime_bytes_checked': total_bytes, 'source_files_checked': source_count,
        'risk_revision': manifest['risk_revision'],
        'training_performed': False,
    }
    if check_pipeline:
        result['pipeline'] = verify_pipeline(root, dataset_id, manifest, check_sources=check_sources)
    return result


def verify_pipeline(root, dataset_id, manifest, *, check_sources=False):
    """Verify the explicitly prepared calibration state and active trace assets."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.probability_calibration import load_calibration
    from api.datasets.scored_graph import verify_scored_trace_graph, effective_risk_revision
    root = Path(root)
    state = root/'artifacts/calibration'/dataset_id/'current/manifest.json'
    if not state.is_file():
        raise ReleaseVerificationError('校准数据审计尚未准备，请先运行 python scripts/audit_probability_calibration.py。')
    calibration = load_calibration(root, dataset_id, manifest)
    if check_sources:
        audit = json.loads(state.with_name('audit.json').read_text())
        for name, sha in audit.get('source_sha256', {}).items():
            _check_asset(root, name, sha)
    current_risk = effective_risk_revision(manifest['risk_revision'], calibration.revision)
    if dataset_id == 'ethereum':
        traced = verify_scored_trace_graph(root/'artifacts/datasets/ethereum/current/trace_scored',
            source_manifest=manifest, calibration_revision=calibration.revision)
        graph_revision, scope = traced['graph_revision'], traced['trace_scope']
    else:
        folder = root/'artifacts/datasets/bitcoin/current/anchor_index_v31'/current_risk[:16]
        metadata_file = folder/'metadata.json'
        if not metadata_file.is_file():
            raise ReleaseVerificationError('比特币当前风险口径的追踪索引尚未准备，请运行统一准备脚本。')
        index = json.loads(metadata_file.read_text())
        for key, value in {'risk_revision':current_risk, 'calibration_revision':calibration.revision,
                           'graph_revision':manifest['graph_revision'], 'trace_scope':'bitcoin_scored_addresses_only'}.items():
            if index.get(key) != value:
                raise ReleaseVerificationError('比特币索引修订不匹配：'+key)
        for name in ('distance.npy', 'next_node.npy'):
            _check_asset(folder, name, index['array_sha256'][name])
        graph_revision, scope = manifest['graph_revision'], index['trace_scope']
    return {'calibration':calibration.describe(), 'trace_scope':scope,
            'risk_revision':current_risk, 'graph_revision':graph_revision,
            'pipeline_checks_passed':True}


def prepare_release(root: Path, dataset_id: str) -> Path:
    """Reuse frozen models/outputs; explicitly prepare only from the CLI."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if dataset_id == 'bitcoin':
        from scripts.prepare_bitcoin_v3 import prepare_bitcoin
        folder = prepare_bitcoin(root)
        from api.datasets.scored_graph import prepare_bitcoin_trace_index
        prepare_bitcoin_trace_index(root)
        from scripts.prepare_bitcoin_examples_v3 import prepare_bitcoin_examples
        prepare_bitcoin_examples(root)
        return folder
    if dataset_id == 'ethereum':
        from api.datasets.ethereum_assets import prepare_ethereum_release
        folder = prepare_ethereum_release(root)
        from api.datasets.scored_graph import prepare_scored_trace_graph
        prepare_scored_trace_graph(root)
        # Examples are actual directed paths, prepared ahead of user requests.
        from api.datasets.ethereum import EthereumService, prepare_trace_examples
        prepare_trace_examples(EthereumService(root))
        return folder
    raise ReleaseVerificationError(f'未知数据集：{dataset_id}')


def main(argv=None) -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description='显式准备/校验链境智安双数据集冻结运行包；不训练模型')
    parser.add_argument('--dataset', choices=('all', *DATASETS), default='all')
    parser.add_argument('--verify-only', action='store_true', help='只校验已有清单与文件，不准备或修改运行包')
    parser.add_argument('--runtime-only', action='store_true', help='仅校验运行包，不全量重读source_hashes原始输入')
    parser.add_argument('--groups-only', action='store_true', help='仅显式构建/核验群组索引，不重做冻结运行资产')
    args = parser.parse_args(argv)
    selected = DATASETS if args.dataset == 'all' else (args.dataset,)
    failures = 0
    for dataset_id in selected:
        try:
            if args.groups_only:
                from scripts.build_dense_group_index import build_for_dataset
                if args.verify_only:
                    from api.datasets.base import DatasetService
                    service = DatasetService(ROOT, dataset_id, ROOT/'artifacts/datasets'/dataset_id/'current')
                    if service.group_index is None:
                        raise ReleaseVerificationError('群组索引未就绪：'+service.group_status)
                    result = {'dataset_id':dataset_id,'dense_group_checks_passed':True,
                              'dense_group_revision':service.dense_group_revision,
                              'group_count':len(service.group_index.groups)}
                    del service
                else:
                    result = build_for_dataset(ROOT,dataset_id)
                    from scripts.refresh_trace_examples_v4 import refresh_examples
                    result['examples'] = refresh_examples(ROOT,dataset_id)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                continue
            if not args.verify_only:
                prepare_release(ROOT, dataset_id)
            result = verify_release(ROOT, dataset_id, check_sources=not args.runtime_only, check_pipeline=True)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:
            failures += 1
            print(json.dumps({'dataset_id': dataset_id, 'asset_checks_passed': False,
                              'error': str(exc), 'error_type': type(exc).__name__},
                             ensure_ascii=False), file=sys.stderr, flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
