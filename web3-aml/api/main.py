"""Run: python -m uvicorn api.main:app --host 127.0.0.1 --port 8000"""
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from src.utils.io import ROOT
from api.runtime import Runtime, Conflict
from api.exporter import bundle_zip


@asynccontextmanager
async def lifespan(app):
    try:
        app.state.runtime = Runtime()
        app.state.error = None
    except Exception:
        logging.exception('AML service initialization failed')
        app.state.runtime = None
        app.state.error = '分析服务未就绪，请检查 processed 与 artifacts 文件及服务端日志'
    yield
    if app.state.runtime is not None:
        app.state.runtime.close()


app = FastAPI(title='链境智安可信研判服务', lifespan=lifespan)
DatasetID = Literal['bitcoin', 'ethereum']


def runtime():
    if app.state.runtime is None:
        raise HTTPException(503, app.state.error)
    return app.state.runtime


@app.exception_handler(KeyError)
async def not_found(request, exc):
    dataset_id = request.query_params.get('dataset_id')
    if dataset_id is None and request.method == 'POST':
        try:
            dataset_id = (await request.json()).get('dataset_id', 'bitcoin')
        except (ValueError, AttributeError):
            pass
    return JSONResponse({'detail': str(exc).strip("'"), 'code': 'not_found',
                         'dataset_id': dataset_id or 'bitcoin'}, status_code=404)


@app.exception_handler(FileNotFoundError)
async def not_ready(request, exc):
    logging.exception('Dataset artifact missing', exc_info=exc)
    return JSONResponse({'detail': '当前数据集运行产物尚未准备完成，请完成数据准备后重试。',
                         'code': 'dataset_not_ready'}, status_code=503)


@app.exception_handler(Conflict)
async def conflict(request, exc):
    return JSONResponse({'detail': str(exc), 'code': 'version_conflict'}, status_code=409)


@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    return JSONResponse({'detail': '输入或参数无效，请检查地址、参数范围与结果编号', 'code': 'invalid_parameters'}, status_code=422)


@app.exception_handler(Exception)
async def failed(request, exc):
    logging.exception('AML request failed', exc_info=exc)
    return JSONResponse({'detail': '分析未完成，请稍后重试；详细原因见服务端日志', 'code': 'analysis_failed'}, status_code=500)


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    max_depth: int | None = Field(default=None, ge=1, le=32)
    beam_width: int | None = Field(default=None, ge=1, le=20)
    risk_threshold: int | None = Field(default=None, ge=0, le=100)
    top_paths: int | None = Field(default=None, ge=1, le=30)
    edge_budget: int | None = Field(default=None, ge=100, le=10000)
    max_bridge_nodes: int | None = Field(default=None, ge=1, le=31)


class TraceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_id: DatasetID = 'bitcoin'
    analysis_id: str = Field(max_length=100)
    params: Parameters = Field(default_factory=Parameters)
    mode: Literal['quick','long'] = 'quick'


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_id: DatasetID = 'bitcoin'
    analysis_id: str = Field(max_length=100)
    trace_id: str | None = Field(default=None, max_length=100)
    mode: Literal['auto','template'] = 'auto'


class DemoRequest(BaseModel):
    dataset_id: DatasetID = 'bitcoin'
    kind: Literal['path_score_as_risk','invented_amount','subject_swap']


class AddressReportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_id: DatasetID
    address: str = Field(min_length=1, max_length=150)
    mode: Literal['auto','template'] = 'auto'
    reuse_analysis_id: str | None = Field(default=None, max_length=100)
    reuse_trace_id: str | None = Field(default=None, max_length=100)
    trace_mode: Literal['quick','long'] | None = None
    trace_params: Parameters | None = None


@app.get('/api/datasets')
def datasets():
    return runtime().datasets()


@app.get('/api/meta')
def meta(dataset_id: DatasetID = 'bitcoin'):
    return runtime().meta(dataset_id)


@app.get('/api/risk')
def risk(address: str = Query(min_length=1, max_length=150), dataset_id: DatasetID = 'bitcoin'):
    return runtime().analyze(address, dataset_id)


@app.get('/api/queue')
def queue(limit: int = Query(100, ge=10, le=500), offset: int = Query(0, ge=0, le=1_000_000), dataset_id: DatasetID = 'bitcoin'):
    return runtime().queue_page(limit, offset, dataset_id)


@app.get('/api/queue/export')
def queue_export(limit: int = Query(100, ge=10, le=500), offset: int = Query(0, ge=0, le=1_000_000), dataset_id: DatasetID = 'bitcoin'):
    return download(runtime().queue_export(limit, offset, dataset_id), dataset_id+'_risk_queue.csv', 'text/csv')


@app.get('/api/evaluation')
def evaluation(dataset_id: DatasetID = 'bitcoin'):
    return runtime().evaluation(dataset_id)


@app.get('/api/evaluation/design')
def evaluation_design():
    return FileResponse(ROOT/'docs/RISK_SCORING_REDESIGN.md', filename='risk_scoring_design.md')


@app.post('/api/traces')
def trace(body: TraceRequest):
    return runtime().trace(body.analysis_id, body.params.model_dump(exclude_none=True), body.mode, body.dataset_id)


@app.get('/api/traces/{trace_id}')
def trace_get(trace_id: str, dataset_id: DatasetID | None = None):
    return {'trace_id': trace_id, **runtime().snapshot(trace_id, 'trace', dataset_id)}


@app.get('/api/traces/{trace_id}/groups')
def trace_groups(trace_id: str, dataset_id: DatasetID = 'bitcoin',
                 path_id: str | None = Query(default=None, min_length=1, max_length=100)):
    return runtime().trace_groups(trace_id, dataset_id, path_id)


@app.get('/api/traces/{trace_id}/groups/{group_id}')
def trace_group_detail(trace_id: str, group_id: str, dataset_id: DatasetID = 'bitcoin',
                       path_id: str | None = Query(default=None, min_length=1, max_length=100),
                       offset: int = Query(default=0, ge=0),
                       limit: int = Query(default=500, ge=1, le=1000)):
    return runtime().trace_group_detail(trace_id, group_id, dataset_id,
                                        path_id=path_id, offset=offset, limit=limit)


def download(content, name, media):
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="{name}"'})


@app.get('/api/traces/{trace_id}/export')
def trace_export(trace_id: str, dataset_id: DatasetID | None = None):
    data = runtime().snapshot(trace_id, 'trace', dataset_id)['result']
    return download(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), trace_id+'.json', 'application/json')


@app.post('/api/reports')
def report(body: ReportRequest):
    return runtime().report(body.analysis_id, body.trace_id, body.mode, body.dataset_id)


@app.post('/api/reports/from-address', status_code=202)
def report_from_address(body: AddressReportRequest):
    return runtime().report_from_address(
        body.address, body.dataset_id, body.mode,
        reuse_analysis_id=body.reuse_analysis_id, reuse_trace_id=body.reuse_trace_id,
        trace_mode=body.trace_mode,
        trace_params=(body.trace_params.model_dump(exclude_none=True) if body.trace_params is not None else None))


@app.get('/api/jobs/{job_id}')
def job(job_id: str, dataset_id: DatasetID | None = None):
    return runtime().job(job_id, dataset_id)


@app.get('/api/reports/{report_id}')
def report_get(report_id: str, dataset_id: DatasetID | None = None):
    return {'report_id': report_id, **runtime().snapshot(report_id, 'report', dataset_id)}


@app.get('/api/reports/{report_id}/export')
def report_export(report_id: str, format: Literal['md','txt','evidence'] = 'md', dataset_id: DatasetID | None = None):
    report = runtime().snapshot(report_id, 'report', dataset_id)['report']
    data = json.dumps(report['evidence_snapshot'], ensure_ascii=False, indent=2, allow_nan=False) if format == 'evidence' else report['markdown']
    return download(data, report_id+('.json' if format == 'evidence' else '.'+format), 'application/json' if format == 'evidence' else 'text/plain')


@app.get('/api/reports/{report_id}/bundle')
def report_bundle(report_id: str, dataset_id: DatasetID | None = None):
    return download(bundle_zip(runtime().snapshot(report_id, 'report', dataset_id)['report']), report_id+'.zip', 'application/zip')


@app.post('/api/reports/{report_id}/demo')
def demo(report_id: str, body: DemoRequest):
    return runtime().demo(report_id, body.kind, body.dataset_id)


@app.get('/')
@app.get('/workspace')
@app.get('/workspace/{module}')
def index():
    return FileResponse(ROOT/'frontend/index.html', headers={'Cache-Control': 'no-cache'})


app.mount('/assets', StaticFiles(directory=ROOT/'frontend'), name='assets')
