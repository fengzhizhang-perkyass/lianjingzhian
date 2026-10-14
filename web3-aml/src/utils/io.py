from pathlib import Path
import json
import os
import re
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_config(name: str, root: Path = ROOT) -> dict:
    text = (root / "config" / name).read_text(encoding="utf-8")
    text = re.sub(r"\$\{([A-Z_]+)\}", lambda m: os.environ.get(m[1], ""), text)
    return yaml.safe_load(text)


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_key(address_id: str) -> str:
    """Never use an untrusted address as a filesystem path."""
    import hashlib
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if len(address_id) <= 100 and re.fullmatch(r"[A-Za-z0-9_-]+", address_id) and address_id.upper() not in reserved:
        return address_id
    return "address_"+hashlib.sha256(address_id.encode()).hexdigest()[:24]
