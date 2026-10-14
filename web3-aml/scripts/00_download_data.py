"""Download the three official Git-LFS CSV objects; verify SHA-256 before use."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = "git-disl/EllipticPlusPlus"
FILES = ("wallets_features.csv", "wallets_classes.csv", "AddrAddr_edgelist.csv")


def download(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"repository": f"https://github.com/{REPO}", "files": []}
    for name in FILES:
        raw = f"https://raw.githubusercontent.com/{REPO}/main/Actors%20Dataset/{name}"
        pointer = urllib.request.urlopen(raw, timeout=60).read().decode()
        match = re.search(r"oid sha256:([a-f0-9]+)\nsize (\d+)", pointer)
        if not match:
            raise RuntimeError(f"Unexpected LFS metadata for {name}")
        expected, size = match.group(1), int(match.group(2))
        target = destination / name
        if target.exists() and target.stat().st_size == size:
            with target.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest == expected:
                print(f"Verified existing {name}", flush=True)
                manifest["files"].append({"name": name, "bytes": size, "sha256": expected})
                continue
        url = f"https://media.githubusercontent.com/media/{REPO}/main/Actors%20Dataset/{name}"
        part = target.with_suffix(".csv.part")
        digest = hashlib.sha256()
        count, last = 0, time.monotonic()
        with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                count += len(chunk)
                if time.monotonic() - last > 10:
                    print(f"{name}: {count / size:.0%} ({count // 1024 // 1024} MiB)", flush=True)
                    last = time.monotonic()
        if count != size or digest.hexdigest() != expected:
            raise RuntimeError(f"Checksum/size mismatch for {name}; incomplete file kept at {part}")
        part.replace(target)
        print(f"Downloaded and verified {name}: {size} bytes", flush=True)
        manifest["files"].append({"name": name, "bytes": size, "sha256": expected, "url": url})
    (destination / "download_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "data/raw")
    download(parser.parse_args().destination)
