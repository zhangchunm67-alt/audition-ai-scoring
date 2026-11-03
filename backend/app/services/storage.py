"""对象存储。生产用 S3 兼容存储（服务端加密，境内云厂商均兼容）；本地目录只用于开发和测试。

媒体读取一律经后端代理（T10），这里不对外签发地址；presigned 地址只给本机 ffprobe 等内部工具用。
"""
from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from ..settings import get_settings

CHUNK = 1024 * 1024


class StorageError(RuntimeError):
    pass


@dataclass
class Part:
    part_no: int
    etag: str


class Storage(Protocol):
    encrypted: bool

    def start_multipart(self, key: str, content_type: str) -> str: ...
    def upload_part(self, key: str, upload_id: str, part_no: int, data: bytes) -> str: ...
    def complete_multipart(self, key: str, upload_id: str, parts: list[Part]) -> None: ...
    def abort_multipart(self, key: str, upload_id: str) -> None: ...
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def size(self, key: str) -> int: ...
    def read_range(self, key: str, start: int, end: int) -> Iterator[bytes]: ...  # end 含
    def probe_location(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """开发和测试用：文件直接落在本地目录，不加密（encrypted=False），生产环境禁止使用。"""

    encrypted = False

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise StorageError("非法的存储路径")
        return p

    def _mp(self, upload_id: str) -> Path:
        uuid.UUID(upload_id)
        return self.root / ".multipart" / upload_id

    def start_multipart(self, key: str, content_type: str) -> str:
        uid = str(uuid.uuid4())
        self._mp(uid).mkdir(parents=True)
        return uid

    def upload_part(self, key: str, upload_id: str, part_no: int, data: bytes) -> str:
        d = self._mp(upload_id)
        if not d.exists():
            raise StorageError("分片上传不存在或已结束")
        (d / f"{part_no:06d}").write_bytes(data)
        import hashlib

        return hashlib.md5(data).hexdigest()  # noqa: S324  与 S3 的 ETag 语义一致，仅作校验

    def complete_multipart(self, key: str, upload_id: str, parts: list[Part]) -> None:
        d = self._mp(upload_id)
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as out:
            for p in sorted(parts, key=lambda x: x.part_no):
                with open(d / f"{p.part_no:06d}", "rb") as f:
                    shutil.copyfileobj(f, out, CHUNK)
        shutil.rmtree(d)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        shutil.rmtree(self._mp(upload_id), ignore_errors=True)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def read_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        with open(self._path(key), "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(CHUNK, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    def probe_location(self, key: str) -> str:
        return str(self._path(key))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """S3 兼容存储。所有对象写入都带服务端加密（默认 AES256，可配 aws:kms）。"""

    encrypted = True

    def __init__(self, client, bucket: str, sse: str = "AES256"):
        self.c, self.bucket, self.sse = client, bucket, sse

    def start_multipart(self, key: str, content_type: str) -> str:
        r = self.c.create_multipart_upload(Bucket=self.bucket, Key=key, ContentType=content_type, ServerSideEncryption=self.sse)
        return r["UploadId"]

    def upload_part(self, key: str, upload_id: str, part_no: int, data: bytes) -> str:
        r = self.c.upload_part(Bucket=self.bucket, Key=key, UploadId=upload_id, PartNumber=part_no, Body=data)
        return r["ETag"].strip('"')

    def complete_multipart(self, key: str, upload_id: str, parts: list[Part]) -> None:
        self.c.complete_multipart_upload(
            Bucket=self.bucket, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": [{"PartNumber": p.part_no, "ETag": f'"{p.etag}"'} for p in sorted(parts, key=lambda x: x.part_no)]},
        )

    def abort_multipart(self, key: str, upload_id: str) -> None:
        self.c.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.c.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, ServerSideEncryption=self.sse)

    def size(self, key: str) -> int:
        return int(self.c.head_object(Bucket=self.bucket, Key=key)["ContentLength"])

    def read_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        body = self.c.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}")["Body"]
        yield from body.iter_chunks(CHUNK)

    def probe_location(self, key: str) -> str:
        return self.c.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=600)

    def delete(self, key: str) -> None:
        self.c.delete_object(Bucket=self.bucket, Key=key)


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage == "s3":
        import boto3

        client = boto3.client("s3", endpoint_url=s.s3_endpoint, region_name=s.s3_region)
        return S3Storage(client, s.s3_bucket, s.s3_sse)  # type: ignore[arg-type]
    if s.env == "production":
        raise StorageError("生产环境必须使用 S3 兼容存储（APP_STORAGE=s3），本地目录存储不加密")
    return LocalStorage(s.storage_dir or os.path.join(os.getcwd(), "var", "storage"))
