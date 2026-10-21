"""Address-independent immutable result files; IDs never refer to 'latest'."""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
import numpy as np


def json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f'Unsupported JSON value: {type(value).__name__}')


def wire(value):
    # Fail on invalid numbers, rather than quietly changing scientific data.
    return json.loads(json.dumps(value, default=json_default, ensure_ascii=False, allow_nan=False))


class SnapshotStore:
    def __init__(self, folder):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)

    def write(self, kind, payload, result_id=None):
        result_id = result_id or kind + '_' + uuid.uuid4().hex
        record = wire({**payload, 'created_at': datetime.now(timezone.utc).isoformat()})
        target = self.folder / (result_id + '.json')
        # Unique names and exclusive creation prevent another run from replacing it.
        with target.open('x', encoding='utf-8') as output:
            json.dump(record, output, ensure_ascii=False, allow_nan=False)
        return result_id, record

    def read(self, result_id, kind):
        if not re.fullmatch(kind + r'_[A-Za-z0-9_]+', result_id):
            raise KeyError('结果编号无效')
        path = self.folder / (result_id + '.json')
        if not path.is_file():
            raise KeyError('结果不存在，请重新运行分析')
        return json.loads(path.read_text(encoding='utf-8'))
