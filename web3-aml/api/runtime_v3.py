"""Dataset-isolated immutable analyses and background one-address report jobs."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import re
import threading
import uuid
from api.datasets.registry import DatasetRegistry
from api.store import SnapshotStore, wire
from api.presenters import scoring_charts, relation_chart
from src.utils.io import ROOT, read_json, save_json


class Conflict(ValueError):
    pass


class Runtime:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.registry = DatasetRegistry(self.root)
        self.store = SnapshotStore(self.root/'artifacts/web_runs')
        self.cache = OrderedDict()
        self.cache_lock = threading.RLock()
        self.jobs_lock = threading.RLock()
        self.jobs_folder = self.root/'artifacts/web_jobs'
        self.jobs_folder.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='trusted-report')
        self.job_futures = {}
        self.instance_id = uuid.uuid4().hex
        for path in self.jobs_folder.glob('job_*.json'):
            record = read_json(path)
            if record.get('status') in ('queued', 'running') and not self._owner_alive(record):
                record.update(status='interrupted', stage='failed', message='服务已重启，本次任务已中断，请重新生成。')
                save_json(path, record)

    @staticmethod
    def _owner_alive(record):
        pid = record.get('owner_pid')
        if type(pid) is not int or pid < 1:
            return False  # Pre-ownership historical jobs use the old recovery rule.
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, OverflowError):
            return False
        except PermissionError:
            # Lack of permission to inspect a live owner does not prove death.
            return True

    @property
    def service(self):
        return self.registry.get('bitcoin')

    @property
    def queue(self):
        return self.service.queue

    @property
    def versions(self):
        return self.service.versions

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def datasets(self):
        return self.registry.list()

    def meta(self, dataset_id='bitcoin'):
        return wire(self.registry.get(dataset_id).meta())

    def current(self, record, dataset_id='bitcoin'):
        service = self.registry.get(dataset_id)
        if record.get('dataset_id', 'bitcoin') != dataset_id or record.get('versions') != service.versions:
            raise Conflict('评分、路径与报告必须属于同一数据集和当前模型，请在所选数据集中重新分析。')
        return service

    def snapshot(self, result_id, kind, dataset_id=None):
        record = self.store.read(result_id, kind)
        actual = record.get('dataset_id', record.get('versions', {}).get('dataset_id', 'bitcoin'))
        if dataset_id is not None and actual != dataset_id:
            raise Conflict('结果属于另一个数据集，请切换到对应数据集。')
        return record

    def analyze(self, address, dataset_id='bitcoin'):
        service = self.registry.get(dataset_id)
        address = service.predictor.resolve(address)
        cache_key = (dataset_id, json.dumps(service.versions, sort_keys=True), address)
        with self.cache_lock:
            if cache_key in self.cache:
                self.cache.move_to_end(cache_key)
                return self.cache[cache_key]
        with service.lock:
            analysis = wire(service.analyze(address))
            key, record = self.store.write('analysis', {'dataset_id': dataset_id, 'address_id': address,
                'versions': service.versions, 'analysis': analysis,
                'charts': scoring_charts(analysis['scoring_analysis'])})
        result = {'analysis_id': key, **record}
        with self.cache_lock:
            self.cache[cache_key] = result
            if len(self.cache) > 256:
                self.cache.popitem(last=False)
        return result

    def trace(self, analysis_id, params, mode='quick', dataset_id='bitcoin'):
        analysis = self.snapshot(analysis_id, 'analysis', dataset_id)
        service = self.current(analysis, dataset_id)
        overrides = dict(service.tracer.config.get('long_path_profile', {})) if mode == 'long' else {}
        overrides.update(params)
        with service.lock:
            result = wire(service.trace(analysis['address_id'], overrides))
        key, record = self.store.write('trace', {'dataset_id': dataset_id, 'analysis_id': analysis_id,
            'address_id': analysis['address_id'], 'versions': service.versions, 'mode': mode,
            'result': result, 'chart': relation_chart(result)})
        return {'trace_id': key, **record}

    def trace_groups(self, trace_id, dataset_id='bitcoin', path_id=None):
        """Read group evidence for one immutable, current tracing context."""
        traced = self.snapshot(trace_id, 'trace', dataset_id)
        service = self.current(traced, dataset_id)
        with service.lock:
            result = service.related_groups(traced['result'], path_id=path_id)
        return wire({**result, 'trace_id': trace_id, 'address_id': traced['address_id']})

    def trace_group_detail(self, trace_id, group_id, dataset_id='bitcoin', *,
                           path_id=None, offset=0, limit=500):
        """Load only a related group's frozen members and original edges.

        Expanding a view is a read operation: it must not save a new trace,
        rerun inference or mutate the original trace's paths and statistics.
        """
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('群组分页参数无效。')
        traced = self.snapshot(trace_id, 'trace', dataset_id)
        service = self.current(traced, dataset_id)
        with service.lock:
            result = service.group_detail(traced['result'], group_id, path_id=path_id,
                                          offset=offset, limit=limit)
        return wire({**result, 'trace_id': trace_id, 'address_id': traced['address_id']})

    def report(self, analysis_id, trace_id=None, mode='auto', dataset_id='bitcoin', progress=None):
        from src.report.dataset_reporting import generate_dataset_report
        analysis = self.snapshot(analysis_id, 'analysis', dataset_id)
        service = self.current(analysis, dataset_id)
        generated_trace = None
        if trace_id is None:
            if progress:
                progress('trace')
            generated_trace = self.trace(analysis_id, {}, dataset_id=dataset_id)
            trace_id = generated_trace['trace_id']
        traced = self.snapshot(trace_id, 'trace', dataset_id)
        self.current(traced, dataset_id)
        if traced['analysis_id'] != analysis_id or traced['address_id'] != analysis['address_id']:
            raise Conflict('报告的评分与路径必须属于同一次地址分析。')
        evidence = service.evidence(analysis['analysis'], traced['result'])
        if progress:
            progress('generation')
        report = generate_dataset_report(service, evidence, mode, progress=progress)
        report.pop('bundle_path', None)
        key, record = self.store.write('report', {'dataset_id': dataset_id, 'analysis_id': analysis_id,
            'trace_id': trace_id, 'address_id': analysis['address_id'],
            'versions': service.versions, 'report': report}, report['report_id'])
        return {'report_id': key, **record, 'generated_trace': generated_trace}

    def queue_page(self, limit, offset, dataset_id='bitcoin'):
        return wire(self.registry.get(dataset_id).queue_page(limit, offset))

    def queue_export(self, limit, offset, dataset_id='bitcoin'):
        frame = self.registry.get(dataset_id).queue.iloc[offset:offset+limit].copy()
        frame.insert(0, 'dataset_id', dataset_id)
        return frame[['dataset_id', 'address_id', 'risk_rank', 'overall_risk_score', 'risk_level']].to_csv(index=False).encode('utf-8-sig')

    def evaluation(self, dataset_id='bitcoin'):
        if dataset_id == 'bitcoin':
            raw = read_json(self.root/'model_upgrade/remote_records/long_and_refit_test/model_upgrade/all_pretest_refit/releases/fixed_s42/test.json')
        else:
            raw = read_json(self.root/'model_upgrade/ethereum/artifacts/test_evaluation.json')['test']
        return wire({'dataset_id': dataset_id, 'current': raw})

    def demo(self, report_id, kind, dataset_id='bitcoin'):
        from src.report.dataset_reporting import generate_dataset_fault_demo
        original = self.snapshot(report_id, 'report', dataset_id)
        service = self.current(original, dataset_id)
        if kind == 'path_score_as_risk' and not original['report']['evidence_snapshot']['trace_analysis'].get('top_paths'):
            raise Conflict('当前报告没有关系路径，不能演示路径排序分错误。')
        try:
            report = generate_dataset_fault_demo(service, original['report'], kind)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        report.pop('bundle_path', None)
        key, record = self.store.write('report', {**{k: original[k] for k in
            ('dataset_id', 'analysis_id', 'trace_id', 'address_id', 'versions')}, 'report': report}, report['report_id'])
        return {'report_id': key, **record}

    def _job_path(self, job_id):
        if not re.fullmatch(r'job_[a-f0-9]{32}', job_id):
            raise KeyError('任务编号无效。')
        return self.jobs_folder/(job_id+'.json')

    def job(self, job_id, dataset_id=None):
        path = self._job_path(job_id)
        with self.jobs_lock:
            if not path.exists():
                raise KeyError('任务不存在，请重新提交地址。')
            result = read_json(path)
        if dataset_id is not None and result['dataset_id'] != dataset_id:
            raise Conflict('任务属于另一个数据集。')
        return result

    def _update_job(self, job_id, **updates):
        with self.jobs_lock:
            record = self.job(job_id)
            record.update(updates)
            save_json(self._job_path(job_id), wire(record))
        return record

    def _reuse_candidate(self, result_id, kind, address, dataset_id, service):
        if result_id is None:
            return None, 'not_provided'
        try:
            candidate = self.snapshot(result_id, kind, dataset_id)
        except KeyError:
            return None, 'not_found'
        # snapshot() rejects cross-dataset IDs. Stale same-chain results can be
        # automatically refreshed without letting an old target replace input.
        if candidate.get('address_id') != address:
            return None, 'different_address'
        if candidate.get('versions') != service.versions:
            return None, 'revision_changed'
        return {kind+'_id': result_id, **candidate}, None

    def _report_context(self, address, dataset_id, reuse_analysis_id, reuse_trace_id, trace_mode, trace_params):
        service = self.registry.get(dataset_id)
        address = service.predictor.resolve(address)
        traced, trace_rejected = self._reuse_candidate(reuse_trace_id, 'trace', address, dataset_id, service)
        analysis_id = reuse_analysis_id or (traced['analysis_id'] if traced else None)
        analyzed, analysis_rejected = self._reuse_candidate(analysis_id, 'analysis', address, dataset_id, service)
        if traced and (not analyzed or traced.get('analysis_id') != analyzed['analysis_id']):
            traced, trace_rejected = None, 'analysis_changed'
        selected_mode = trace_mode or (traced.get('mode', 'quick') if traced else 'quick')
        params = dict(trace_params) if trace_params is not None else None
        if traced:
            if trace_mode is not None and selected_mode != traced.get('mode', 'quick'):
                traced, trace_rejected = None, 'mode_changed'
            elif params is not None:
                expected = dict(service.tracer.config)
                if selected_mode == 'long':
                    expected.update(service.tracer.config.get('long_path_profile', {}))
                expected.update(params)
                keys = ('max_depth', 'beam_width', 'risk_threshold', 'top_paths', 'edge_budget', 'max_bridge_nodes')
                if any(traced['result']['config'].get(k) != expected.get(k) for k in keys):
                    traced, trace_rejected = None, 'parameters_changed'
        return address, analyzed, traced, selected_mode, params or {}, {
            'analysis': analyzed is not None, 'trace': traced is not None,
            'analysis_refresh_reason': analysis_rejected,
            'trace_refresh_reason': trace_rejected}

    def report_from_address(self, address, dataset_id='bitcoin', mode='auto', *,
                            reuse_analysis_id=None, reuse_trace_id=None, trace_mode=None, trace_params=None):
        service = self.registry.get(dataset_id)
        address, analyzed, traced, selected_mode, params, reuse = self._report_context(
            address, dataset_id, reuse_analysis_id, reuse_trace_id, trace_mode, trace_params)
        job_id = 'job_'+uuid.uuid4().hex
        record = {'job_id': job_id, 'dataset_id': dataset_id, 'address_id': address,
                  'owner_pid': os.getpid(), 'owner_instance': self.instance_id,
                  'versions': service.versions, 'reuse': reuse,
                  'status': 'queued', 'stage': 'queued', 'message': '任务已提交，准备核对地址证据。'}
        with self.jobs_lock:
            save_json(self._job_path(job_id), record)
        future = self.executor.submit(self._run_report_job, job_id, address, dataset_id, mode,
                                      analyzed, traced, selected_mode, params)
        with self.jobs_lock:
            self.job_futures[job_id] = future
        def finished(_):
            with self.jobs_lock:
                if _.cancelled():
                    self._update_job(job_id, status='interrupted', stage='failed',
                                     message='服务已停止，本次排队任务已取消，请重新生成。')
                self.job_futures.pop(job_id, None)
        future.add_done_callback(finished)
        return record

    def _run_report_job(self, job_id, address, dataset_id, mode, analyzed=None, traced=None,
                        trace_mode='quick', trace_params=None):
        messages = {'risk': '正在读取真实风险评分与模型解释。', 'trace': '正在搜索有向关联路径。',
                    'generation': '正在组织可信研判报告。', 'validation': '正在核对报告事实与证据来源。'}
        def progress(stage):
            self._update_job(job_id, status='running', stage=stage, message=messages.get(stage, '正在分析。'))
        try:
            if analyzed is None:
                progress('risk')
                analyzed = self.analyze(address, dataset_id)
            else:
                self.current(analyzed, dataset_id)
                self._update_job(job_id, status='running', stage='risk', message='已复用当前地址的有效评分与解释。')
            if traced is None:
                progress('trace')
                traced = self.trace(analyzed['analysis_id'], trace_params or {}, trace_mode, dataset_id)
            else:
                self.current(traced, dataset_id)
                self._update_job(job_id, status='running', stage='trace', message='已复用当前参数下的有效关联路径。')
            generated = self.report(analyzed['analysis_id'], traced['trace_id'], mode, dataset_id, progress)
            generated.update(analysis=analyzed, trace=traced)
            self._update_job(job_id, status='completed', stage='completed',
                             message='报告及证据核验已完成。', result=generated)
        except Exception as exc:
            import logging
            logging.exception('Dataset report job failed: %s', job_id)
            failed_stage = self.job(job_id).get('stage')
            self._update_job(job_id, status='failed', stage='failed', message='分析未完成，请检查错误提示后重试。',
                error={'code': 'analysis_failed', 'stage': failed_stage,
                       'detail': str(exc) if isinstance(exc, (ValueError, KeyError)) else '服务执行异常，请查看服务端日志。'})
