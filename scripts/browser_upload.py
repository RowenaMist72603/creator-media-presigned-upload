"""Request a ticket and perform the browser's direct PUT from the command line."""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--creator", default="demo-creator")
    parser.add_argument("--service", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    content_type = mimetypes.guess_type(args.file.name)[0] or "application/octet-stream"
    ticket_response = httpx.request(
        method="POST",
        url=f"{args.service}/assets/uploads",
        json={
            "creator_id": args.creator,
            "filename": args.file.name,
            "content_type": content_type,
            "size_bytes": args.file.stat().st_size,
        },
        timeout=20.0,
    )
    ticket_response.raise_for_status()
    ticket = ticket_response.json()

    with args.file.open("rb") as media_bytes:
        upload_response = httpx.request(
            method=ticket["method"],
            url=ticket["upload_url"],
            content=media_bytes,
            headers={"Content-Type": content_type},
            timeout=120.0,
        )
    upload_response.raise_for_status()
    print(f"uploaded asset {ticket['asset_id']} as {ticket['object_key']}")


if __name__ == "__main__":
    main()

