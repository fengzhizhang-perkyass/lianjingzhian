"""One process owns one original service; mutable legacy saves are serialized."""
import threading
from collections import OrderedDict
import pandas as pd
from src.inference.analysis_service import AnalysisService
from src.utils.io import ROOT, read_json, load_config
from src.report.audited_reporter import AuditedReportGenerator
from src.report.report_audit import reporting_revision
from src.report.source_locator import SourceIndex
from src.report.fault_demo import generate_fault_demo
from api.store import SnapshotStore, wire
from api.presenters import scoring_charts, relation_chart
from api.reporting import generate_web_report


class Conflict(ValueError):
    pass


class Runtime:
    def __init__(self):
        self.lock = threading.RLock()
        self.service = AnalysisService()
        self.store = SnapshotStore(ROOT / 'artifacts/web_runs')
        self.cache = OrderedDict()
        self.versions = {'dataset_fingerprint': self.service.metadata['fingerprint'],
                         'risk_revision': self.service.metadata['risk_revision'],
                         'tracing_revision': self.service.tracer.revision, 'reporting_revision': reporting_revision()}
        self.queue = self.service.predictor.table.sort_values('overall_risk_score', ascending=False)

    def meta(self):
        # Constructor resolves dotenv, but never performs an external API request.
        reporter = AuditedReportGenerator(ROOT)
        configured = bool(reporter.config.get('api_key')) and bool(reporter.config.get('enabled'))
        source = SourceIndex.load(ROOT, reporter.reporting['source_index_path'], self.versions['dataset_fingerprint'])
        registry = read_json(ROOT/self.service.tracer.config['long_path_cases'])
        valid_cases = registry.get('cases', []) if registry.get('provenance') == self.service.tracer.provenance and registry.get('tracing_revision') == self.service.tracer.revision else []
        active = self.service.predictor.metadata
        metrics = read_json(ROOT/active['metrics_path'])
        return wire({'ready': True, 'versions': self.versions, 'dataset': self.service.metadata,
                     'model': {k: active[k] for k in ['model_kind', 'model_name', 'model_version', 'seed']},
                     'metrics': {k: metrics[k] for k in ['pr_auc', 'f1', 'recall']},
                     'top500': metrics['review']['top_500']['precision'], 'defaults': self.service.tracer.config,
                     'examples': read_json(ROOT/'artifacts/demo_cases.json'), 'long_cases': valid_cases,
                     'capabilities': {'llm_configured': configured, 'raw_csv': source is not None,
                                      'template_report': True, 'snapshot_only': True},
                     'risk_counts': self.service.predictor.table.risk_level.value_counts().to_dict()})

    def current(self, record):
        if record['versions'] != self.versions:
            raise Conflict('结果属于不同的数据或配置版本，请重新评分和追踪')

    def analyze(self, address):
        with self.lock:
            address = self.service.predictor.resolve(address.strip())
            if address in self.cache:
                self.cache.move_to_end(address)
                return self.cache[address]
            analysis = wire(self.service.analyze(address))
            key, record = self.store.write('analysis', {'address_id': address, 'versions': self.versions,
                'analysis': analysis, 'charts': scoring_charts(analysis['scoring_analysis'])})
            result = {'analysis_id': key, **record}
            self.cache[address] = result
            if len(self.cache) > 128:
                self.cache.popitem(last=False)
            return result

    def trace(self, analysis_id, params, mode='quick'):
        with self.lock:
            analysis = self.store.read(analysis_id, 'analysis'); self.current(analysis)
            overrides = dict(self.service.tracer.config.get('long_path_profile', {})) if mode == 'long' else {}
            overrides.update(params)
            trace = wire(self.service.trace(analysis['address_id'], overrides))
            key, record = self.store.write('trace', {'analysis_id': analysis_id, 'address_id': analysis['address_id'],
                'versions': self.versions, 'mode': mode, 'result': trace, 'chart': relation_chart(trace)})
            return {'trace_id': key, **record}

    def report(self, analysis_id, trace_id=None, mode='auto'):
        with self.lock:
            analysis = self.store.read(analysis_id, 'analysis'); self.current(analysis)
            generated_trace = None
            if trace_id is None:
                generated_trace = self.trace(analysis_id, {})
                trace_id = generated_trace['trace_id']
            trace = self.store.read(trace_id, 'trace'); self.current(trace)
            if trace['analysis_id'] != analysis_id or trace['address_id'] != analysis['address_id']:
                raise Conflict('报告的评分与追踪必须属于同一次分析')
            evidence = self.service.evidence(analysis['analysis'], trace['result'])
            if mode == 'template':
                report = AuditedReportGenerator(ROOT, config={'enabled': False}).generate(evidence, graph=self.service.graph, risk_scores=self.service.risks)
            else:
                report = generate_web_report(self.service, evidence)
            report.pop('bundle_path', None)
            key, record = self.store.write('report', {'analysis_id': analysis_id, 'trace_id': trace_id,
                'address_id': analysis['address_id'], 'versions': self.versions, 'report': report}, report['report_id'])
            return {'report_id': key, **record, 'generated_trace': generated_trace}

    def queue_page(self, limit, offset):
        columns = ['address_id', 'risk_rank', 'overall_risk_score', 'risk_level', 'behavior_score', 'graph_score', 'structure_score']
        return wire({'total': len(self.queue), 'offset': offset, 'limit': limit,
                     'rows': self.queue.iloc[offset:offset+limit][columns].to_dict('records')})

    def evaluation(self):
        metadata = self.service.predictor.metadata
        result = read_json(ROOT/metadata['metrics_path'])
        names = {'standardized_deviation_fusion':'完整证据融合','behavior_only':'只有行为画像','context_only':'只有方向邻域均值',
                 'structure_only':'只有有向结构','context_z_only':'只有邻域偏离','without_behavior':'去掉行为画像',
                 'without_context':'去掉邻域偏离','without_structure':'去掉有向结构','direction_removed':'去掉边方向'}
        main = pd.read_csv(ROOT/'artifacts/experiments'/metadata['experiment']/'final_comparison.csv')
        ablation = pd.read_csv(ROOT/'artifacts/experiments/evidence_tree_v1_ablation/comparison.csv')
        columns = ['candidate','pr_auc','f1','recall']
        comparison = pd.concat([main[main.seed == metadata['seed']][columns], ablation[columns]], ignore_index=True)
        comparison.candidate = comparison.candidate.map(names)
        # ROC thresholds can contain Infinity; they are not plotted or used here.
        keys = ['precision','recall','f1','pr_auc','roc_auc','threshold','confusion_matrix','num_test_nodes','review']
        def curves(record):
            return {**{k:record[k] for k in keys if k in record},
                    'pr_curve': {k:record['pr_curve'][k] for k in ['recall','precision']},
                    'roc_curve': {k:record['roc_curve'][k] for k in ['fpr','tpr']}}
        history = {name: curves(read_json(ROOT/'artifacts/metrics'/f'{name}.json')) for name in ['lightgbm','behavior','graphsage','dual_view']}
        return wire({'model_name': metadata['model_name'], 'current': curves(result), 'comparison': comparison.to_dict('records'), 'history': history})

    def demo(self, report_id, kind):
        with self.lock:
            original = self.store.read(report_id, 'report'); self.current(original)
            if kind == 'path_score_as_risk' and not original['report']['evidence_snapshot']['trace_analysis'].get('top_paths'):
                raise Conflict('当前报告没有关系路径，不能演示路径排序分错误')
            report = generate_fault_demo(ROOT, original['report'], kind, self.service.graph, self.service.risks)
            report.pop('bundle_path', None)
            key, record = self.store.write('report', {**{k: original[k] for k in ['analysis_id','trace_id','address_id','versions']}, 'report': report}, report['report_id'])
            return {'report_id': key, **record}
