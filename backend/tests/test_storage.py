"""存储层：本地目录与 S3 兼容存储（用 moto 模拟），分片上传、服务端加密、区间读取、删除。"""
import os

import boto3
import pytest
from moto import mock_aws

from app.services.storage import LocalStorage, Part, S3Storage, StorageError

MB = 1024 * 1024


@pytest.fixture
def s3():
    with mock_aws():
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="audition")
        yield client, S3Storage(client, "audition", "AES256")


def _roundtrip(storage, key: str, data: bytes, part: int):
    uid = storage.start_multipart(key, "video/mp4")
    parts = []
    for i in range(0, len(data), part):
        n = i // part + 1
        parts.append(Part(n, storage.upload_part(key, uid, n, data[i:i + part])))
    storage.complete_multipart(key, uid, list(reversed(parts)))  # 顺序无关
    assert storage.size(key) == len(data)
    assert b"".join(storage.read_range(key, 0, len(data) - 1)) == data
    assert b"".join(storage.read_range(key, 10, 19)) == data[10:20]
    assert b"".join(storage.read_range(key, len(data) - 5, len(data) - 1)) == data[-5:]


def test_s3_multipart_with_sse(s3):
    client, storage = s3
    data = os.urandom(11 * MB)  # S3 分片除最后一片外至少 5 MB
    _roundtrip(storage, "recordings/x/raw/a.mp4", data, 5 * MB)
    assert client.head_object(Bucket="audition", Key="recordings/x/raw/a.mp4")["ServerSideEncryption"] == "AES256"
    storage.put("candidates/c/consent/1.pdf", b"%PDF", "application/pdf")
    assert client.head_object(Bucket="audition", Key="candidates/c/consent/1.pdf")["ServerSideEncryption"] == "AES256"
    assert storage.probe_location("recordings/x/raw/a.mp4").startswith("https://")
    storage.delete("recordings/x/raw/a.mp4")
    with pytest.raises(client.exceptions.ClientError):
        client.head_object(Bucket="audition", Key="recordings/x/raw/a.mp4")
    assert storage.encrypted is True


def test_s3_abort(s3):
    client, storage = s3
    uid = storage.start_multipart("k", "video/mp4")
    storage.upload_part("k", uid, 1, b"x" * 10)
    storage.abort_multipart("k", uid)
    assert not client.list_multipart_uploads(Bucket="audition").get("Uploads")


def test_local_storage(tmp_path):
    storage = LocalStorage(tmp_path)
    _roundtrip(storage, "recordings/x/raw/a.mp4", os.urandom(300_000), 64 * 1024)
    assert storage.encrypted is False
    assert list((tmp_path / ".multipart").iterdir()) == []  # 合并后清理分片
    with pytest.raises(StorageError):
        storage.put("../escape.txt", b"x", "text/plain")


def test_production_refuses_local_storage(monkeypatch):
    from app import settings
    from app.services import storage as st

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_STORAGE", "local")
    settings.get_settings.cache_clear()
    st.get_storage.cache_clear()
    try:
        with pytest.raises(StorageError, match="生产环境"):
            st.get_storage()
    finally:
        monkeypatch.undo()
        settings.get_settings.cache_clear()
        st.get_storage.cache_clear()
