from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
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


def qdrant_headers() -> dict[str, str]:
    key = str(settings.qdrant_api_key or "").strip()
    return {"api-key": key} if key else {}


def backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def backup_app_data(stage: Path) -> Path:
    source_dir = ROOT / "backend" / "data"
    staged = stage / "data"
    staged.mkdir(parents=True, exist_ok=True)

    if source_dir.exists():
        for source in source_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_dir)
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                backup_sqlite(source, destination)
            else:
                shutil.copy2(source, destination)

    archive = stage / "backend-data.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staged, arcname="data")
    return archive


def create_qdrant_snapshot(stage: Path) -> tuple[Path, dict]:
    base = settings.qdrant_url.rstrip("/")
    collection = settings.qdrant_collection
    headers = qdrant_headers()
    create_url = f"{base}/collections/{collection}/snapshots"
    response = httpx.post(create_url, params={"wait": "true"}, headers=headers, timeout=120)
    response.raise_for_status()
    result = response.json().get("result") or {}
    name = str(result.get("name") or "")
    if not name:
        raise RuntimeError("Qdrant snapshot response missing result.name")

    snapshot_path = stage / name
    download = httpx.get(
        f"{base}/collections/{collection}/snapshots/{name}",
        headers=headers,
        timeout=120,
    )
    download.raise_for_status()
    snapshot_path.write_bytes(download.content)

    try:
        httpx.delete(
            f"{base}/collections/{collection}/snapshots/{name}",
            headers=headers,
            timeout=30,
        )
    except Exception:
        pass

    return snapshot_path, result


def main() -> int:
    parser = argparse.ArgumentParser(description="Create yaoke enterprise backup bundle")
    parser.add_argument("--output", default=str(ROOT / "backups"))
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_root / f"yaoke-backup-{timestamp}"
    destination.mkdir(parents=True, exist_ok=False)

    with tempfile.TemporaryDirectory(prefix="yaoke-backup-") as tmp:
        stage = Path(tmp)
        data_archive = backup_app_data(stage)
        qdrant_snapshot, qdrant_meta = create_qdrant_snapshot(stage)

        shutil.move(str(data_archive), destination / data_archive.name)
        shutil.move(str(qdrant_snapshot), destination / qdrant_snapshot.name)

    data_path = destination / "backend-data.tar.gz"
    snapshot_path = destination / qdrant_snapshot.name
    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "qdrant_collection": settings.qdrant_collection,
        "retrieval_schema_version": settings.retrieval_schema_version,
        "qdrant_snapshot": {
            "file": snapshot_path.name,
            "sha256": sha256_file(snapshot_path),
            "server_metadata": qdrant_meta,
        },
        "backend_data": {
            "file": data_path.name,
            "sha256": sha256_file(data_path),
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
