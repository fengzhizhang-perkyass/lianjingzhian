"""Constructing a second runtime must not interrupt an actually live owner."""
import json
import os
import threading
from types import SimpleNamespace
from pathlib import Path
from api.runtime_v3 import Runtime


def record(root, owner_pid):
    folder=root/'artifacts/web_jobs';folder.mkdir(parents=True)
    path=folder/('job_'+'a'*32+'.json')
    path.write_text(json.dumps({'job_id':'job_'+'a'*32,'dataset_id':'bitcoin',
                                'status':'running','stage':'generation','owner_pid':owner_pid}))
    return path


def test_another_live_runtime_job_is_not_called_a_restart(tmp_path):
    path=record(tmp_path,os.getpid())
    runtime=Runtime(tmp_path)
    try:assert json.loads(path.read_text())['status']=='running'
    finally:runtime.close()


def test_confirmed_dead_owner_is_recovered_as_interrupted(tmp_path,monkeypatch):
    path=record(tmp_path,123456)
    monkeypatch.setattr(Runtime,'_owner_alive',staticmethod(lambda row:False))
    runtime=Runtime(tmp_path)
    try:assert json.loads(path.read_text())['status']=='interrupted'
    finally:runtime.close()


def test_finished_reports_are_never_modified_by_recovery(tmp_path,monkeypatch):
    path=record(tmp_path,123456)
    path.write_text(json.dumps({'status':'completed','report_id':'report_frozen','owner_pid':123456}))
    original=path.read_bytes()
    monkeypatch.setattr(Runtime,'_owner_alive',staticmethod(lambda row:False))
    runtime=Runtime(tmp_path)
    try:assert path.read_bytes()==original
    finally:runtime.close()


def test_shutdown_marks_only_cancelled_queued_jobs_as_interrupted(tmp_path):
    runtime=Runtime(tmp_path)
    service=SimpleNamespace(predictor=SimpleNamespace(resolve=lambda address:address),versions={'dataset_id':'bitcoin'})
    runtime.registry=SimpleNamespace(get=lambda dataset:service)
    gate=threading.Event()
    runtime._run_report_job=lambda *args:gate.wait(3)
    try:
        first=runtime.report_from_address('A',mode='template')
        second=runtime.report_from_address('B',mode='template')
        queued=runtime.report_from_address('C',mode='template')
        runtime.close()
        assert runtime.job(queued['job_id'])['status']=='interrupted'
        assert runtime.job(first['job_id'])['status']=='queued'
        assert runtime.job(second['job_id'])['status']=='queued'
    finally:
        gate.set()
        runtime.executor.shutdown(wait=True,cancel_futures=True)
