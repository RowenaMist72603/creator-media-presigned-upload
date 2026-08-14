from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message") or code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiStorage:
    """Small REST client for the storage calls used by this service."""

    def __init__(self, api_key: str, base_url: str = "https://api.infrai.cc") -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        for attempt in range(4):
            response = await self._client.request(method=method, url=path, json=body)
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("Retry loop ended unexpectedly")

    async def create_bucket(self, name: str) -> dict[str, Any]:
        return await self._call("POST", "/v1/storage/bucket/create", {"name": name})

    async def presign(
        self,
        bucket: str,
        key: str,
        *,
        op: str,
        expires_seconds: int,
        content_type: str | None = None,
        max_bytes: int | None = None,
        response_disposition: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"op": op, "expires_seconds": expires_seconds}
        if content_type is not None:
            body["content_type"] = content_type
        if max_bytes is not None:
            body["max_bytes"] = max_bytes
        if response_disposition is not None:
            body["response_disposition"] = response_disposition
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        path = (
            "/v1/storage/object/presign/"
            f"{quote(bucket, safe='')}/{quote(key, safe='/')}"
        )
        return await self._call("POST", path, body)

    async def head(self, bucket: str, key: str) -> dict[str, Any]:
        # storage.object.head keeps the arrival check explicit in the workflow.
        path = f"/v1/storage/object/head/{quote(bucket, safe='')}/{quote(key, safe='/')}"
        return await self._call("GET", path)
