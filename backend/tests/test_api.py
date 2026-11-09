import sqlite3

import pytest
from fastapi.testclient import TestClient

import main
import measure
import storage


def fake_scan(include_throughput=True):
    yield "path", {
        "latency_ms": 30.0, "jitter_ms": 4.0, "packet_loss": 0.0, "rtts": [30.0, 28.0],
        "gateway_ip": "192.168.1.1", "gateway_ms": 2.0, "gateway_loss": 0.0, "gateway_jitter_ms": 0.5,
        "errors": {},
    }
    yield "dns", {"dns_ms": 25.0, "errors": {}}
    if include_throughput:
        yield "download", {"download_mbps": 50.0, "errors": {}}
        yield "upload", {"upload_mbps": 12.0, "errors": {}}
    else:
        yield "download", {"download_mbps": None, "errors": {"download": "skipped"}}
        yield "upload", {"upload_mbps": None, "errors": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NETLENS_DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(measure, "run_scan", fake_scan)
    monkeypatch.setattr(main, "_latest", None)
    with TestClient(main.app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def test_health(client):
    assert client.get("/health").json()["version"] == main.VERSION


def test_scan_saves_and_appears_in_history(client):
    result = client.post("/api/v1/scan").json()
    assert result["saved"] is True
    assert result["status"] == "good"
    history = client.get("/api/v1/history").json()
    assert len(history) == 1 and history[0]["download_mbps"] == 50.0


def test_scan_stream_reports_each_stage(client):
    body = client.get("/api/v1/scan/stream?throughput=false").text
    assert body.count("event: stage") == 4
    assert "event: result" in body
    assert '"download":"skipped"' in body


def test_failed_ping_is_not_saved(client, monkeypatch):
    def broken_scan(include_throughput=True):
        yield "path", {"latency_ms": None, "packet_loss": None, "errors": {"ping": "no ping"}}

    monkeypatch.setattr(measure, "run_scan", broken_scan)
    result = client.post("/api/v1/scan").json()
    assert result["saved"] is False
    assert client.get("/api/v1/history").json() == []


def test_check_task_requires_scan_then_answers(client):
    assert client.post("/api/v1/check-task", json={"task": "zoom"}).status_code == 409
    client.post("/api/v1/scan")
    answer = client.post("/api/v1/check-task", json={"task": "Can I join a Zoom call?"}).json()
    assert answer["matched"] and answer["key"] == "video_call" and answer["verdict"] == "yes"
    unknown = client.post("/api/v1/check-task", json={"task": "bake bread"}).json()
    assert unknown["matched"] is False


def test_csv_export_and_clear(client):
    client.post("/api/v1/scan")
    csv_text = client.get("/api/v1/history.csv").text
    assert csv_text.splitlines()[0].startswith("id,timestamp,score")
    assert client.delete("/api/v1/history").json() == {"deleted": 1}


def test_cross_site_requests_are_blocked(client):
    response = client.post("/api/v1/scan", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.post("/api/v1/scan", headers={"Origin": "null"}).status_code == 403


def test_dns_rebinding_host_is_blocked(client):
    assert client.get("/health", headers={"Host": "evil.example:8000"}).status_code == 403


def test_dashboard_is_served(client):
    response = client.get("/")
    assert response.status_code == 200 and "NetLens" in response.text


def test_legacy_table_is_migrated(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("NETLENS_DB", str(path))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE diagnostics (id INTEGER PRIMARY KEY, timestamp TEXT, score INTEGER, latency_ms REAL,"
            " packet_loss REAL, dns_ms REAL, download_mbps REAL, status TEXT)"
        )
        connection.execute("INSERT INTO diagnostics VALUES (1, '2026-01-01', 70, 90, 1, 40, 33.3, 'fair')")
    storage.init_db()
    storage.init_db()  # idempotent
    rows = storage.history()
    assert len(rows) == 1
    assert rows[0]["score"] == 70 and rows[0]["download_mbps"] is None


def test_latest_is_empty_until_first_scan(client):
    assert client.get("/api/v1/scan/latest").status_code == 204
    client.post("/api/v1/scan")
    assert client.get("/api/v1/scan/latest").json()["status"] == "good"
