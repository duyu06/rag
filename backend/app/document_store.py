from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import SecretStr

from app.config import settings

LOCAL_DOCUMENT_ROOT = Path("data/documents")


def _secret(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return str(value or "").strip()


def _safe_name(file_name: str) -> str:
    return Path(file_name).name


def _object_key(knowledge_base_id: str, file_name: str) -> str:
    prefix = str(settings.s3_prefix or "").strip("/")
    parts = [part for part in (prefix, knowledge_base_id, _safe_name(file_name)) if part]
    return "/".join(parts)


@dataclass(frozen=True)
class DocumentMeta:
    file_name: str
    knowledge_base_id: str
    size_bytes: int
    last_modified: str | None = None


class LocalDocumentStore:
    backend = "local"

    def path(self, knowledge_base_id: str, file_name: str) -> Path:
        directory = LOCAL_DOCUMENT_ROOT / knowledge_base_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory / _safe_name(file_name)

    def put(self, knowledge_base_id: str, file_name: str, content: bytes) -> None:
        self.path(knowledge_base_id, file_name).write_bytes(content)

    def get(self, knowledge_base_id: str, file_name: str) -> bytes:
        path = self.path(knowledge_base_id, file_name)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(file_name)
        return path.read_bytes()

    def exists(self, knowledge_base_id: str, file_name: str) -> bool:
        path = self.path(knowledge_base_id, file_name)
        return path.exists() and path.is_file()

    def delete(self, knowledge_base_id: str, file_name: str) -> None:
        self.path(knowledge_base_id, file_name).unlink(missing_ok=True)

    def list(self, knowledge_base_id: str) -> list[DocumentMeta]:
        directory = LOCAL_DOCUMENT_ROOT / knowledge_base_id
        if not directory.exists():
            return []
        result: list[DocumentMeta] = []
        for path in directory.iterdir():
            if not path.is_file():
                continue
            stat = path.stat()
            result.append(
                DocumentMeta(
                    file_name=path.name,
                    knowledge_base_id=knowledge_base_id,
                    size_bytes=stat.st_size,
                    last_modified=str(stat.st_mtime),
                )
            )
        return result

    def ping(self) -> bool:
        try:
            LOCAL_DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False


class S3DocumentStore:
    backend = "s3"

    def __init__(self) -> None:
        if not str(settings.s3_bucket or "").strip():
            raise RuntimeError("S3_BUCKET is required for S3 document storage")
        kwargs: dict[str, Any] = {}
        region = str(settings.s3_region or "").strip()
        endpoint = str(settings.s3_endpoint_url or "").strip()
        access_key = _secret(settings.s3_access_key_id)
        secret_key = _secret(settings.s3_secret_access_key)
        session_token = _secret(settings.s3_session_token)

        if region:
            kwargs["region_name"] = region
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if access_key:
            kwargs["aws_access_key_id"] = access_key
        if secret_key:
            kwargs["aws_secret_access_key"] = secret_key
        if session_token:
            kwargs["aws_session_token"] = session_token
        if settings.s3_force_path_style:
            kwargs["config"] = Config(s3={"addressing_style": "path"})

        self.bucket = str(settings.s3_bucket).strip()
        self.client = boto3.client("s3", **kwargs)

    def put(self, knowledge_base_id: str, file_name: str, content: bytes) -> None:
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        self.client.put_object(
            Bucket=self.bucket,
            Key=_object_key(knowledge_base_id, file_name),
            Body=content,
            ContentType=content_type,
            ServerSideEncryption="AES256",
            Metadata={"knowledge-base-id": knowledge_base_id},
        )

    def get(self, knowledge_base_id: str, file_name: str) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=_object_key(knowledge_base_id, file_name),
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(file_name) from exc
            raise
        return response["Body"].read()

    def exists(self, knowledge_base_id: str, file_name: str) -> bool:
        try:
            self.client.head_object(
                Bucket=self.bucket,
                Key=_object_key(knowledge_base_id, file_name),
            )
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                return False
            raise

    def delete(self, knowledge_base_id: str, file_name: str) -> None:
        self.client.delete_object(
            Bucket=self.bucket,
            Key=_object_key(knowledge_base_id, file_name),
        )

    def list(self, knowledge_base_id: str) -> list[DocumentMeta]:
        prefix = _object_key(knowledge_base_id, "")
        paginator = self.client.get_paginator("list_objects_v2")
        result: list[DocumentMeta] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = str(item.get("Key") or "")
                if not key or key.endswith("/"):
                    continue
                result.append(
                    DocumentMeta(
                        file_name=key.rsplit("/", 1)[-1],
                        knowledge_base_id=knowledge_base_id,
                        size_bytes=int(item.get("Size") or 0),
                        last_modified=(
                            item["LastModified"].isoformat()
                            if item.get("LastModified") is not None
                            else None
                        ),
                    )
                )
        return result

    def ping(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except (BotoCoreError, ClientError):
            return False


def build_document_store():
    backend = str(settings.document_store_backend or "local").strip().lower()
    if backend == "s3":
        return S3DocumentStore()
    if backend == "local":
        return LocalDocumentStore()
    raise RuntimeError(f"Unsupported DOCUMENT_STORE_BACKEND={backend}")


document_store = build_document_store()
