from functools import partial
from io import BytesIO
from typing import Protocol

from anyio import to_thread


class ObjectStorage(Protocol):
    async def ensure_bucket(self) -> None:
        raise NotImplementedError

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        raise NotImplementedError

    async def read(self, key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError


class MinioObjectStorage:
    def __init__(
        self,
        *,
        bucket: str,
        client=None,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool = False,
    ):
        if client is None:
            if not endpoint or not access_key or not secret_key:
                raise ValueError("MinIO connection settings are required")
            from minio import Minio

            client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            )
        self._client = client
        self._bucket = bucket

    async def ensure_bucket(self) -> None:
        exists = await to_thread.run_sync(partial(self._client.bucket_exists, self._bucket))
        if not exists:
            await to_thread.run_sync(partial(self._client.make_bucket, self._bucket))

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        await to_thread.run_sync(
            partial(
                self._client.put_object,
                self._bucket,
                key,
                BytesIO(content),
                len(content),
                content_type=content_type,
            )
        )

    async def read(self, key: str) -> bytes:
        response = await to_thread.run_sync(partial(self._client.get_object, self._bucket, key))
        try:
            return bytes(response.data)
        finally:
            await to_thread.run_sync(response.close)
            await to_thread.run_sync(response.release_conn)

    async def delete(self, key: str) -> None:
        await to_thread.run_sync(partial(self._client.remove_object, self._bucket, key))
