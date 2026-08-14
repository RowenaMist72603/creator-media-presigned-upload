from __future__ import annotations

from typing import Any

import pytest

from media_ingest.media_service import (
    BUCKET,
    MAX_UPLOAD_BYTES,
    AssetState,
    MediaIngestion,
    UploadRequest,
)


class FakeStorage:
    def __init__(self, found: bool = True) -> None:
        self.found = found
        self.presign_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def create_bucket(self, name: str) -> dict:
        return {"name": name}

    async def presign(self, bucket: str, key: str, **body: object) -> dict:
        self.presign_calls.append((bucket, key, body))
        return {"url": "https://uploads.example/signed"}

    async def head(self, bucket: str, key: str) -> dict:
        return {"found": self.found}

    async def close(self) -> None:
        return None


def upload_request(size_bytes: int = 4_000_000) -> UploadRequest:
    return UploadRequest(
        creator_id="maya",
        filename="launch cut.mp4",
        content_type="video/mp4",
        size_bytes=size_bytes,
    )


@pytest.mark.asyncio
async def test_valid_asset_gets_scoped_put_ticket_then_processing_job() -> None:
    storage = FakeStorage(found=True)
    workflow = MediaIngestion(storage)

    ticket = await workflow.issue_upload(upload_request())
    job = await workflow.queue_processing(ticket.asset_id)

    assert ticket.state == AssetState.awaiting_upload
    assert ticket.object_key.startswith(f"creators/maya/{ticket.asset_id}/")
    assert job.state == AssetState.processing
    assert storage.presign_calls == [
        (
            BUCKET,
            ticket.object_key,
            {
                "op": "put",
                "expires_seconds": 600,
                "content_type": "video/mp4",
                "max_bytes": 4_000_000,
                "idempotency_key": str(ticket.asset_id),
            },
        )
    ]


@pytest.mark.asyncio
async def test_oversize_asset_is_rejected_before_a_url_is_signed() -> None:
    storage = FakeStorage()
    workflow = MediaIngestion(storage)

    with pytest.raises(ValueError, match="250 MiB"):
        await workflow.issue_upload(upload_request(MAX_UPLOAD_BYTES + 1))

    assert storage.presign_calls == []


@pytest.mark.asyncio
async def test_missing_object_stays_out_of_processing() -> None:
    storage = FakeStorage(found=False)
    workflow = MediaIngestion(storage)
    ticket = await workflow.issue_upload(upload_request())

    with pytest.raises(ValueError, match="not complete"):
        await workflow.queue_processing(ticket.asset_id)

    assert workflow.assets[ticket.asset_id].state == AssetState.awaiting_upload

