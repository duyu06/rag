from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"Checksum mismatch for {path.name}")


def qdrant_headers() -> dict[str, str]:
    key = str(settings.qdrant_api_key or "").strip()
    return {"api-key": key} if key else {}


def safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if root not in target.parents and target != root:
            raise RuntimeError("Unsafe path in backup archive")
    archive.extractall(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore yaoke enterprise backup bundle")
    parser.add_argument("backup_dir")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.force:
        raise RuntimeError("Restore overwrites live data. Re-run with --force after stopping backend writes.")

    backup_dir = Path(args.backup_dir).resolve()
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    if int(manifest.get("version") or 0) != 1:
        raise RuntimeError("Unsupported backup manifest version")

    data_meta = manifest["backend_data"]
    snapshot_meta = manifest["qdrant_snapshot"]
    data_archive = backup_dir / data_meta["file"]
    snapshot_path = backup_dir / snapshot_meta["file"]
    verify_file(data_archive, data_meta["sha256"])
    verify_file(snapshot_path, snapshot_meta["sha256"])

    collection = str(manifest.get("qdrant_collection") or settings.qdrant_collection)
    url = settings.qdrant_url.rstrip("/") + f"/collections/{collection}/snapshots/upload"
    with snapshot_path.open("rb") as handle:
        response = httpx.post(
            url,
            params={"wait": "true", "priority": "snapshot"},
            headers=qdrant_headers(),
            files={"snapshot": (snapshot_path.name, handle, "application/octet-stream")},
            timeout=300,
        )
    response.raise_for_status()

    target_data = ROOT / "backend" / "data"
    with tempfile.TemporaryDirectory(prefix="yaoke-restore-") as tmp:
        stage = Path(tmp)
        with tarfile.open(data_archive, "r:gz") as tar:
            safe_extract(tar, stage)
        restored = stage / "data"
        if not restored.exists():
            raise RuntimeError("Backup archive missing data directory")
        if target_data.exists():
            shutil.rmtree(target_data)
        shutil.copytree(restored, target_data)

    print("restore completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
