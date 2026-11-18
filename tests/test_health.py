"""Smoke test for the optional HTTP health endpoint."""
from __future__ import annotations

import json
import socket
import urllib.request

from squad_radio.health import HealthServer, HealthState


def test_healthz_returns_runtime_status():
    """端点返回 200 + 运行态 JSON，计数随连接/事件/回复更新。"""
    state = HealthState()
    assert state.snapshot()["status"] == "degraded"

    state.mark_connected(True)
    state.mark_event()
    state.mark_reply()
    state.mark_connected(False)  # 断线重连计数

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = HealthServer(port, state, host="127.0.0.1")
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
    finally:
        server.stop()

    assert payload["service"] == "squad-radio"
    assert "uptime_seconds" in payload and "connected" in payload
    assert payload["replies_sent"] == 1
    assert payload["reconnects"] == 1
