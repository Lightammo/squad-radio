"""Tests for the optional HTTP health endpoint."""
from __future__ import annotations

import json
import threading
import urllib.request

from squad_radio.health import HealthServer, HealthState


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_health_state_snapshot():
    state = HealthState()
    assert state.snapshot()["status"] == "degraded"
    assert state.snapshot()["connected"] is False

    state.mark_connected(True)
    state.mark_event()
    state.mark_reply()
    snap = state.snapshot()
    assert snap["status"] == "ok"
    assert snap["connected"] is True
    assert snap["replies_sent"] == 1
    assert snap["last_event_at"] is not None
    assert snap["seconds_since_last_event"] is not None


def test_health_server_serves_json():
    state = HealthState()
    state.mark_connected(True)
    port = _free_port()
    server = HealthServer(port, state, host="127.0.0.1")
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["status"] == "ok"
        assert payload["service"] == "squad-radio"
        assert "uptime_seconds" in payload
    finally:
        server.stop()


def test_reconnect_counter_increments_on_disconnect():
    state = HealthState()
    state.mark_connected(True)
    state.mark_connected(False)
    assert state.snapshot()["reconnects"] == 1
