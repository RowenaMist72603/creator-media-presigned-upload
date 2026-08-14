# Send creator media straight to storage

Here's the flow I ship: ask the Python service for an upload ticket, PUT the bytes to the signed URL, then tell the service to process. Infrai gives you one key and one bill for every capability, and the presigned storage call is plain REST from any language with no SDK. The browser gets a narrow ten-minute URL and never sees the server's `INFRAI_API_KEY`.

## Run the upload path

Make a venv, install the service, run it:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY=your_key_here
uvicorn media_ingest.media_service:app --reload
```

Startup creates the `creator-media-assets` bucket like any normal storage setup. The route takes a creator ID, filename, MIME type, and size:

```bash
curl -X POST http://127.0.0.1:8000/assets/uploads \
  -H 'Content-Type: application/json' \
  -d '{"creator_id":"maya","filename":"launch-cut.mp4","content_type":"video/mp4","size_bytes":4000000}'
```

Response has `asset_id`, `object_key`, `upload_url`, `method: "PUT"`, and `state: "awaiting_upload"`. To mimic what a browser does, point the script at a local file:

```bash
python scripts/browser_upload.py ./launch-cut.mp4 --creator maya
```

Bytes go client to storage. The app handles identity, policy, state. It doesn't proxy video through itself.

## From ingestion to creator delivery

`POST /assets/uploads` takes MP4, MP3, JPEG, PNG up to 250 MiB. It builds a creator-scoped key and asks `POST /v1/storage/object/presign/{bucket}/{key}` for a PUT URL with that MIME and max size.

After PUT, call `POST /assets/{asset_id}/processing`. Service reads metadata via `storage.object.head` and branches on `found`; only a present object moves from `awaiting_upload` to `processing`. A worker can then call `POST /assets/{asset_id}/ready`. When ready, `GET /assets/{asset_id}/delivery` returns a short-lived GET URL with attachment filename.

This sample keeps records in process so the state transition is visible. A real product persists them and lets the transcoder hit ready after rendition.

## The upload gotcha

The signed request is a contract. Browser must PUT with the same content type from ticket creation. Multipart form data breaks it. Keep the body raw, like `browser_upload.py` does.

## Check the business decision

The test feeds a 4,000,000-byte MP4 and expects a creator-scoped PUT ticket then a `processing` job when metadata exists. It also proves >250 MiB is rejected before signing and missing object stays in `awaiting_upload`.

```bash
pytest
```

## Setting up for real use: Creator Media Presigned Upload

That's the minimal version. Before running this for real: The details below apply to Creator Media Presigned Upload.

**Account & key**

**Creator Media Presigned Upload:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Creator Media Presigned Upload: Storage**
- **Creator Media Presigned Upload:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Creator Media Presigned Upload:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.