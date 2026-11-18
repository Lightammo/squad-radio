"""KOOK API client and broadcast adapter."""
from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .broadcasters import Broadcaster
from .models import Broadcast
from .rich import RichStyle, format_broadcast


class KookApiError(RuntimeError):
    def __init__(self, code: int, message: str, http_status: int | None = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"KOOK API error {code}: {message}")


class KookClient:
    """Minimal KOOK Open API client using only the standard library."""

    BASE_URL = "https://www.kookapp.cn/api/v3"

    def __init__(self, token: str, base_url: str = BASE_URL, timeout: int = 10):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        data = None
        headers = {
            "Authorization": f"Bot {self.token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                http_status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            http_status = exc.code
        except urllib.error.URLError as exc:
            raise KookApiError(-1, f"network error: {exc.reason}") from exc

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KookApiError(-2, f"invalid JSON response: {raw[:200]}") from exc

        code = int(result.get("code", -3))
        if code != 0:
            raise KookApiError(
                code,
                str(result.get("message", "unknown error")),
                http_status,
            )
        return result.get("data")

    def gateway(self, compress: int = 0) -> dict[str, Any]:
        data = self._request("GET", "/gateway/index", params={"compress": compress})
        return dict(data or {})

    def me(self) -> dict[str, Any]:
        data = self._request("GET", "/user/me")
        return dict(data or {})

    def channels(
        self, guild_id: str, channel_type: int = 1, page_size: int = 50
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "/channel/list",
            params={
                "guild_id": guild_id,
                "type": channel_type,
                "page_size": page_size,
            },
        )
        return list((data or {}).get("items", []))

    def view_channel(self, channel_id: str) -> dict[str, Any]:
        data = self._request(
            "GET", "/channel/view", params={"target_id": channel_id}
        )
        return dict(data or {})

    def send_message(
        self,
        target_id: str,
        content: str,
        msg_type: int = 9,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target_id": target_id,
            "type": msg_type,
            "content": content,
        }
        if nonce:
            payload["nonce"] = nonce
        data = self._request("POST", "/message/create", payload=payload)
        return dict(data or {})

    def upload_asset(self, file_path: str | Path) -> str:
        """Upload a local image to KOOK CDN and return its permanent URL.

        Uses multipart/form-data as required by /api/v3/asset/create. The
        returned img.kookapp.cn URL has no hotlink protection, so it renders
        reliably inside KOOK when used as a link thumbnail.
        """
        path = Path(file_path)
        if not path.is_file():
            raise KookApiError(-4, f"asset file not found: {path}")
        raw = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        boundary = f"----squadradio{uuid.uuid4().hex}"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = head + raw + tail

        url = f"{self.base_url}/asset/create"
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bot {self.token}",
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout, 20)) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise KookApiError(exc.code, exc.read().decode("utf-8", errors="replace")[:200]) from exc
        except urllib.error.URLError as exc:
            raise KookApiError(-1, f"network error: {exc.reason}") from exc

        code = int(result.get("code", -3))
        if code != 0:
            raise KookApiError(code, str(result.get("message", "upload failed")))
        asset_url = str((result.get("data") or {}).get("url") or "")
        if not asset_url:
            raise KookApiError(-5, "asset/create returned empty url")
        return asset_url


class KookBroadcaster(Broadcaster):
    """Send Squad Radio broadcasts into a KOOK text channel."""

    def __init__(
        self,
        client: KookClient,
        channel_id: str,
        style: RichStyle | None = None,
    ):
        self.client = client
        self.channel_id = channel_id
        self.style = style or RichStyle()

    def send(self, broadcast: Broadcast) -> None:
        content = format_broadcast(broadcast, self.style)
        self.client.send_message(
            self.channel_id,
            content,
            msg_type=9,
            nonce=broadcast.event_key or None,
        )
