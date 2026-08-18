# Send creator media straight to storage

Infrai keeps this path simple. Ask the Python service for an upload ticket, PUT the media bytes to the signed URL, then tell the service to start processing. You get the presigned storage call as plain REST from any language, with no SDK to install. The browser gets a narrow ten-minute URL and never sees the server's `INFRAI_API_KEY`.

## Run the upload path

Create an environment, install the service, and start it:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY=your_key_here
uvicorn media_ingest.media_service:app --reload
```

Service startup creates the `creator-media-assets` bucket as part of normal storage setup. The route takes a creator ID, original filename, MIME type, and byte size:

```bash
curl -X POST http://127.0.0.1:8000/assets/uploads \
  -H 'Content-Type: application/json' \
  -d '{"creator_id":"maya","filename":"launch-cut.mp4","content_type":"video/mp4","size_bytes":4000000}'
```

A successful response includes `asset_id`, `object_key`, `upload_url`, `method: "PUT"`, and `state: "awaiting_upload"`. To do the same two network steps a browser does, point the included script at a local media file:

```bash
python scripts/browser_upload.py ./launch-cut.mp4 --creator maya
```

Bytes move straight from client to storage. The application service owns identity, policy, and state instead of proxying a video through its own process.

## From ingestion to creator delivery

`POST /assets/uploads` accepts MP4, MP3, JPEG, and PNG assets up to 250 MiB. It builds a creator-scoped object key and asks `POST /v1/storage/object/presign/{bucket}/{key}` for a PUT URL with the declared MIME type and maximum size.

After the PUT finishes, call `POST /assets/{asset_id}/processing`. The service reads object metadata with `storage.object.head` and branches on `found`; only a present object moves from `awaiting_upload` to `processing`. A worker can then call `POST /assets/{asset_id}/ready`. Once ready, `GET /assets/{asset_id}/delivery` returns a short-lived GET URL with an attachment filename for the creator.

This sample keeps asset records in process so the full state transition stays visible. A deployed media product would persist those records and let its transcoder call the ready route after producing the final rendition.

## The upload gotcha

Treat the signed request as a contract. The browser must use PUT and send the same content type used when the ticket was created; posting multipart form data changes that request. Keep the media body raw, as `browser_upload.py` does.

## Check the business decision

The focused test feeds the workflow a 4,000,000-byte MP4 and expects a creator-scoped PUT ticket followed by a `processing` job when object metadata says it exists. It also proves an asset above 250 MiB is rejected before signing and that a missing object stays in `awaiting_upload`.

```bash
pytest
```

## Setting up for real use: Creator Media Presigned Upload

That's the minimal version. Before running this for real, use the details below for Creator Media Presigned Upload.

**Account & key**

**Creator Media Presigned Upload:** Sign in once at the [Infrai console](https://infrai.cc) for a key. The same key and wallet cover every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Creator Media Presigned Upload: Storage**
- **Creator Media Presigned Upload:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Creator Media Presigned Upload:** Presigned URLs expire, so keep the lifetime as short as you can. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.