"""Keep immutable-by-name run bundles; SHA256 is an integrity check, not a signature."""
from datetime import datetime,timezone
from pathlib import Path
import uuid
from src.utils.io import save_json,file_sha256
from src.report.fact_catalog import digest


def reporting_revision():
    folder = Path(__file__).parent
    names = ('fact_catalog.py','claim_schema.py','claim_validator.py','claim_renderer.py',
             'audited_reporter.py','report_audit.py','source_locator.py')
    return digest({name:file_sha256(folder/name) for name in names})


def new_report_id():
    return 'report_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:12]


def save_bundle(root,report):
    folder=root/'artifacts/reports'/report['report_id']
    folder.mkdir(parents=True,exist_ok=False)
    for name,value in [('evidence.json',report['evidence_snapshot']),('fact_catalog.json',report['fact_catalog']),
        ('claims_raw.json',report['candidates']),('claims_validated.json',report['claims_document']),('audit.json',report['audit'])]:
        save_json(folder/name,value)
    (folder/'report.md').write_text(report['markdown'],encoding='utf-8')
    hashes={p.name:file_sha256(p) for p in folder.iterdir() if p.is_file()}
    save_json(folder/'manifest.json',{'report_id':report['report_id'],
        'evidence_hash':report['audit']['evidence_hash'],'reporting_revision':report['audit']['reporting_revision'],
        'file_sha256':hashes,'integrity_scope':'local consistency; unsigned manifest'})
    return str(folder)
