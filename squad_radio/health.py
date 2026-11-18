"""Optional HTTP health endpoint for container orchestrators and probes.

Uses only the standard library. Disabled by default; enable via
``SQUAD_RADIO_HEALTH_PORT`` env var or ``--health-port`` CLI flag.

Endpoints:
    GET /healthz  -> 200 JSON liveness/status payload
    GET /         -> 200 JSON status payload (same as /healthz)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

LOG = logging.getLogger("squad_radio.health")


class HealthState:
    """Mutable snapshot of runtime state, updated by the bot, read by probes."""

    def __init__(self, service: str = "squad-radio"):
        self.service = service
        self._lock = threading.Lock()
        self.started_at = datetime.now(timezone.utc)
        self.connected = False
        self.last_event_at: datetime | None = None
        self.replies_sent = 0
        self.reconnects = 0

    def mark_connected(self, value: bool) -> None:
        with self._lock:
            self.connected = value
            if not value:
                self.reconnects += 1

    def mark_event(self) -> None:
        with self._lock:
            self.last_event_at = datetime.now(timezone.utc)

    def mark_reply(self) -> None:
        with self._lock:
            self.replies_sent += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(timezone.utc)
            uptime = now - self.started_at
            return {
                "status": "ok" if self.connected else "degraded",
                "service": self.service,
                "uptime_seconds": int(uptime.total_seconds()),
                "connected": self.connected,
                "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
                "seconds_since_last_event": (
                    int((now - self.last_event_at).total_seconds())
                    if self.last_event_at else None
                ),
                "replies_sent": self.replies_sent,
                "reconnects": self.reconnects,
                "timestamp": now.isoformat(),
            }


def make_handler(state: HealthState) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            payload = state.snapshot()
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            LOG.debug("health %s - %s", self.address_string(), fmt % args)

    return HealthHandler


class HealthServer:
    """Threaded HTTP server running in a daemon thread."""

    def __init__(self, port: int, state: HealthState, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.state = state
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler = make_handler(self.state)
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="health-server", daemon=True
        )
        self._thread.start()
        LOG.info("健康检查端点已启动：http://%s:%s/healthz", self.host, self.port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            LOG.info("健康检查端点已停止")
