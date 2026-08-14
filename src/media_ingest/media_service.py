from __future__ import annotations

import os
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, AsyncIterator, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .infrai_storage import InfraiError, InfraiStorage

BUCKET = "creator-media-assets"
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {"video/mp4", "audio/mpeg", "image/jpeg", "image/png"}


class AssetState(str, Enum):
    awaiting_upload = "awaiting_upload"
    processing = "processing"
    ready = "ready"


class UploadRequest(BaseModel):
    creator_id: str = Field(min_length=1, max_length=80)
    filename: str = Field(min_length=1, max_length=180)
    content_type: str
    size_bytes: int = Field(gt=0)


class UploadTicket(BaseModel):
    asset_id: UUID
    object_key: str
    upload_url: str
    method: Literal["PUT"] = "PUT"
    state: AssetState


class ProcessingJob(BaseModel):
    job_id: UUID
    asset_id: UUID
    object_key: str
    state: AssetState


class DeliveryLink(BaseModel):
    asset_id: UUID
    download_url: str
    state: AssetState


class AssetRecord(BaseModel):
    asset_id: UUID
    creator_id: str
    filename: str
    object_key: str
    state: AssetState


def choose_upload(request: UploadRequest) -> None:
    if request.content_type not in ALLOWED_MEDIA_TYPES:
        raise ValueError("Choose MP4, MP3, JPEG, or PNG media")
    if request.size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError("Asset exceeds the 250 MiB direct-upload limit")


class MediaIngestion:
    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self.assets: dict[UUID, AssetRecord] = {}

    async def issue_upload(self, request: UploadRequest) -> UploadTicket:
        choose_upload(request)
        asset_id = uuid4()
        clean_name = PurePosixPath(request.filename).name.replace(" ", "-")
        object_key = f"creators/{request.creator_id}/{asset_id}/{clean_name}"
        signed = await self.storage.presign(
            BUCKET,
            object_key,
            op="put",
            expires_seconds=600,
            content_type=request.content_type,
            max_bytes=request.size_bytes,
            idempotency_key=str(asset_id),
        )
        self.assets[asset_id] = AssetRecord(
            asset_id=asset_id,
            creator_id=request.creator_id,
            filename=clean_name,
            object_key=object_key,
            state=AssetState.awaiting_upload,
        )
        return UploadTicket(
            asset_id=asset_id,
            object_key=object_key,
            upload_url=signed["url"],
            state=AssetState.awaiting_upload,
        )

    async def queue_processing(self, asset_id: UUID) -> ProcessingJob:
        asset = self._asset(asset_id)
        object_info = await self.storage.head(BUCKET, asset.object_key)
        if not object_info.get("found", False):
            raise ValueError("Upload is not complete yet")
        asset.state = AssetState.processing
        return ProcessingJob(
            job_id=uuid4(),
            asset_id=asset_id,
            object_key=asset.object_key,
            state=asset.state,
        )

    async def mark_ready(self, asset_id: UUID) -> AssetRecord:
        asset = self._asset(asset_id)
        if asset.state != AssetState.processing:
            raise ValueError("Asset must be processing before it can be delivered")
        asset.state = AssetState.ready
        return asset

    async def creator_delivery(self, asset_id: UUID) -> DeliveryLink:
        asset = self._asset(asset_id)
        if asset.state != AssetState.ready:
            raise ValueError("Asset is not ready for creator delivery")
        signed = await self.storage.presign(
            BUCKET,
            asset.object_key,
            op="get",
            expires_seconds=900,
            response_disposition=f'attachment; filename="{asset.filename}"',
        )
        return DeliveryLink(
            asset_id=asset_id, download_url=signed["url"], state=asset.state
        )

    def _asset(self, asset_id: UUID) -> AssetRecord:
        asset = self.assets.get(asset_id)
        if asset is None:
            raise ValueError("Asset was not found")
        return asset


def _service() -> MediaIngestion:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set INFRAI_API_KEY before starting the service")
    return MediaIngestion(InfraiStorage(api_key))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    service = _service()
    await service.storage.create_bucket(BUCKET)
    app.state.media = service
    yield
    await service.storage.close()


app = FastAPI(title="Creator media ingestion", lifespan=lifespan)


def media() -> MediaIngestion:
    return app.state.media


def client_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InfraiError):
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        return HTTPException(status_code=status, detail=exc.detail)
    return HTTPException(status_code=409, detail=str(exc))


@app.post("/assets/uploads", response_model=UploadTicket, status_code=201)
async def request_upload(request: UploadRequest) -> UploadTicket:
    try:
        return await media().issue_upload(request)
    except (ValueError, InfraiError) as exc:
        raise client_error(exc) from exc


@app.post("/assets/{asset_id}/processing", response_model=ProcessingJob)
async def start_processing(asset_id: UUID) -> ProcessingJob:
    try:
        return await media().queue_processing(asset_id)
    except (ValueError, InfraiError) as exc:
        raise client_error(exc) from exc


@app.post("/assets/{asset_id}/ready", response_model=AssetRecord)
async def finish_processing(asset_id: UUID) -> AssetRecord:
    try:
        return await media().mark_ready(asset_id)
    except ValueError as exc:
        raise client_error(exc) from exc


@app.get("/assets/{asset_id}/delivery", response_model=DeliveryLink)
async def get_delivery(asset_id: UUID) -> DeliveryLink:
    try:
        return await media().creator_delivery(asset_id)
    except (ValueError, InfraiError) as exc:
        raise client_error(exc) from exc
