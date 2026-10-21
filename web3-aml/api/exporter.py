"""The same auditable ZIP format as the Streamlit download, without UI imports."""
import hashlib
import io
import json
import zipfile


def bundle_zip(report):
    files = {name: json.dumps(report[key], ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
             for name, key in [('evidence.json', 'evidence_snapshot'), ('fact_catalog.json', 'fact_catalog'),
                               ('claims_raw.json', 'candidates'), ('claims_validated.json', 'claims_document'), ('audit.json', 'audit')]}
    files['report.md'] = report['markdown'].encode('utf-8')
    manifest = {'report_id': report['report_id'], 'evidence_hash': report['audit']['evidence_hash'],
                'file_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                'integrity_scope': 'unsigned local consistency manifest'}
    files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return result.getvalue()
