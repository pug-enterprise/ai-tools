"""
TikTok Content Posting API v2 client.

Supports two post modes:
  direct — POST /v2/post/publish/video/init/  → publishes immediately to profile
  draft  — POST /v2/post/publish/inbox/video/init/ → sends to creator inbox as draft

Upload flow (same for both modes):
  1. Init → get publish_id + upload_url
  2. PUT upload_url with chunked video bytes + Content-Range
  3. Poll /v2/post/publish/status/fetch/ until PUBLISH_COMPLETE

Required OAuth scopes:
  direct → video.publish
  draft  → video.upload
"""

from __future__ import annotations
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx

from config import settings
from domain.models import TikTokPost

log = logging.getLogger(__name__)

BASE_URL = "https://open.tiktokapis.com"
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks
POLL_TIMEOUT = 300   # seconds
POLL_INTERVAL = 5    # seconds

PostMode = Literal["draft", "direct"]

INIT_ENDPOINTS = {
    "direct": "/v2/post/publish/video/init/",
    "draft":  "/v2/post/publish/inbox/video/init/",
}


class TikTokClient:
    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or settings.tiktok_access_token
        if not self.access_token:
            raise RuntimeError("TIKTOK_ACCESS_TOKEN is not set. Run: python cli.py auth tiktok")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def publish(
        self,
        local_path: str,
        caption: str,
        mode: PostMode = "draft",
    ) -> TikTokPost:
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {local_path}")

        file_size = path.stat().st_size
        log.info(f"TikTok upload: {path.name} ({file_size} bytes, mode={mode})")

        # ── 1. Init upload ────────────────────────────────────────────────────
        publish_id, upload_url = self._init_upload(caption, file_size, mode)

        # ── 2. Upload video chunks ────────────────────────────────────────────
        self._upload_chunks(upload_url, path, file_size)

        # ── 3. Poll for completion ────────────────────────────────────────────
        video_id = self._poll_status(publish_id)

        return TikTokPost(
            id=str(uuid4()),
            video_job_id="",  # set by caller via pipeline
            post_mode=mode,
            tiktok_video_id=video_id,
            status="published",
            posted_at=datetime.utcnow(),
        )

    def _init_upload(self, caption: str, file_size: int, mode: PostMode) -> tuple[str, str]:
        endpoint = INIT_ENDPOINTS[mode]

        # Chunk count required for TikTok's chunked upload
        chunk_count = max(1, (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE)

        body: dict = {
            "post_info": {
                "title": caption[:150],
                "privacy_level": "PUBLIC_TO_EVERYONE" if mode == "direct" else "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": CHUNK_SIZE,
                "total_chunk_count": chunk_count,
            },
        }

        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            resp = client.post(endpoint, json=body, headers=self._headers())

        _raise_for_tiktok_error(resp)
        data = resp.json()["data"]
        return data["publish_id"], data["upload_url"]

    def _upload_chunks(self, upload_url: str, path: Path, file_size: int) -> None:
        offset = 0
        with open(path, "rb") as f:
            chunk_num = 0
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                headers = {
                    "Content-Range": f"bytes {offset}-{end}/{file_size}",
                    "Content-Type": "video/mp4",
                }
                with httpx.Client(timeout=120) as client:
                    resp = client.put(upload_url, content=chunk, headers=headers)
                resp.raise_for_status()
                offset += len(chunk)
                chunk_num += 1
                log.debug(f"  Uploaded chunk {chunk_num} ({offset}/{file_size} bytes)")

    def _poll_status(self, publish_id: str) -> str:
        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            with httpx.Client(base_url=BASE_URL, timeout=15) as client:
                resp = client.post(
                    "/v2/post/publish/status/fetch/",
                    json={"publish_id": publish_id},
                    headers=self._headers(),
                )
            _raise_for_tiktok_error(resp)
            data = resp.json().get("data", {})
            status = data.get("status", "")
            log.debug(f"  TikTok publish status: {status}")

            if status == "PUBLISH_COMPLETE":
                return data.get("publicaly_available_post_id", [publish_id])[0]
            if "FAIL" in status or "ERROR" in status:
                raise RuntimeError(f"TikTok publish failed: {status} — {data}")

            time.sleep(POLL_INTERVAL)

        raise TimeoutError(f"TikTok publish did not complete within {POLL_TIMEOUT}s")


def _raise_for_tiktok_error(resp: httpx.Response) -> None:
    try:
        body = resp.json()
    except Exception:
        resp.raise_for_status()
        return

    err = body.get("error", {})
    code = err.get("code", "ok")
    if code not in ("ok", "success", ""):
        raise RuntimeError(f"TikTok API error {code}: {err.get('message', resp.text)}")
