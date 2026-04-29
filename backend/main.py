import random
import re
import socket
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "netlens.db"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_origin_regex=r"^null$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AssistantSummaryRequest(BaseModel):
    latency_ms: float = Field(ge=0)
    packet_loss: float = Field(ge=0, le=100)
    dns_ms: float = Field(ge=0)
    download_mbps: float = Field(ge=0)


class AssistantTaskCheckRequest(BaseModel):
    task: str = Field(min_length=1, max_length=200)
    latency_ms: float = Field(ge=0)
    packet_loss: float = Field(ge=0, le=100)
    download_mbps: float = Field(ge=0)


@app.on_event("startup")
def startup():
    _init_database()


@app.get("/")
def root():
    return {"message": "NetLens API running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "NetLens Agent",
        "version": "0.1.0",
    }


def _get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _init_database() -> None:
    try:
        with _get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS diagnostics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    packet_loss REAL NOT NULL,
                    dns_ms REAL NOT NULL,
                    download_mbps REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(diagnostics)").fetchall()
            }
            expected_columns = {
                "timestamp": "TEXT NOT NULL DEFAULT ''",
                "score": "INTEGER NOT NULL DEFAULT 0",
                "latency_ms": "REAL NOT NULL DEFAULT 0",
                "packet_loss": "REAL NOT NULL DEFAULT 0",
                "dns_ms": "REAL NOT NULL DEFAULT 0",
                "download_mbps": "REAL NOT NULL DEFAULT 0",
                "status": "TEXT NOT NULL DEFAULT 'unknown'",
            }
            for column, definition in expected_columns.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE diagnostics ADD COLUMN {column} {definition}")
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not initialize diagnostics database: {exc}") from exc


def _save_diagnostic(result: dict[str, int | float | str]) -> bool:
    try:
        with _get_connection() as connection:
            connection.execute(
                """
                INSERT INTO diagnostics (
                    timestamp,
                    score,
                    latency_ms,
                    packet_loss,
                    dns_ms,
                    download_mbps,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    result["score"],
                    result["latency_ms"],
                    result["packet_loss"],
                    result["dns_ms"],
                    result["download_mbps"],
                    result["status"],
                ),
            )
    except sqlite3.Error:
        return False

    return True


def _get_diagnostics_history() -> list[dict[str, int | float | str]]:
    try:
        with _get_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    timestamp,
                    score,
                    latency_ms,
                    packet_loss,
                    dns_ms,
                    download_mbps,
                    status
                FROM (
                    SELECT
                        id,
                        timestamp,
                        score,
                        latency_ms,
                        packet_loss,
                        dns_ms,
                        download_mbps,
                        status
                    FROM diagnostics
                    ORDER BY id DESC
                    LIMIT 20
                )
                ORDER BY id ASC
                """
            ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="Diagnostics history is unavailable") from exc

    return [dict(row) for row in rows]


def _run_ping() -> tuple[float, float]:
    command = ["ping", "-n", "5", "8.8.8.8"]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return 180.0, 8.0

    output = f"{result.stdout}\n{result.stderr}"
    if not output.strip():
        return 180.0, 8.0

    latency_ms = _extract_average_latency(output)
    packet_loss = _extract_packet_loss(output)

    if latency_ms is None or packet_loss is None:
        return 180.0, 8.0

    return latency_ms, packet_loss


def _measure_dns_ms() -> float:
    start = time.perf_counter()
    try:
        socket.getaddrinfo("google.com", 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return 180.0

    return clamp((time.perf_counter() - start) * 1000, 1, 250)


def _extract_average_latency(output: str) -> float | None:
    windows_match = re.search(r"Average\s*=\s*(\d+(?:\.\d+)?)ms", output, re.IGNORECASE)
    if windows_match:
        return float(windows_match.group(1))

    unix_match = re.search(
        r"(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+\s*ms",
        output,
        re.IGNORECASE,
    )
    if unix_match:
        return float(unix_match.group(1))

    return None


def _extract_packet_loss(output: str) -> float | None:
    windows_match = re.search(r"\((\d+(?:\.\d+)?)%\s*loss\)", output, re.IGNORECASE)
    if windows_match:
        return float(windows_match.group(1))

    unix_match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", output, re.IGNORECASE)
    if unix_match:
        return float(unix_match.group(1))

    return None


def _simulate_download_mbps(latency_ms: float, packet_loss: float) -> float:
    base_speed = 42.0
    latency_penalty = max(latency_ms - 35, 0) * 0.075
    loss_penalty = packet_loss * 3.2
    jitter = random.uniform(-2.2, 2.2)
    speed = base_speed - latency_penalty - loss_penalty + jitter

    if packet_loss >= 15:
        speed *= 0.45
    elif packet_loss >= 8:
        speed *= 0.65
    elif latency_ms >= 220:
        speed *= 0.72

    return round(clamp(speed, 0.8, 95.0), 1)


def _calculate_score(
    latency_ms: float,
    packet_loss: float,
    dns_ms: float,
    download_mbps: float,
) -> int:
    score = 100.0
    score -= min(packet_loss * 6.5, 55)
    score -= min(max(latency_ms - 35, 0) * 0.18, 28)
    score -= min(max(dns_ms - 45, 0) * 0.12, 16)
    score -= min(max(25 - download_mbps, 0) * 1.05, 26)
    return round(clamp(score, 0, 100))


def _status_for_score(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 50:
        return "fair"
    return "poor"


def _verdict_title(score: int) -> str:
    if score >= 80:
        return "Good connection"
    if score >= 50:
        return "Fair connection"
    return "Poor connection"


def _verdict_subtitle(
    latency_ms: float,
    packet_loss: float,
    dns_ms: float,
    download_mbps: float,
    score: int,
) -> str:
    if packet_loss >= 12:
        return "Heavy packet loss is making the connection unreliable for real-time tasks."
    if score < 50:
        return "Your network is currently too unstable for demanding tasks."
    if packet_loss > 5:
        return "Packet loss is hurting performance and video calls may be unstable."
    if latency_ms > 140:
        return "High latency may cause lag in calls, games, and live apps."
    if dns_ms > 100:
        return "DNS response time is elevated, so sites may feel slow to start loading."
    if download_mbps < 8:
        return "Download bandwidth is limited and large transfers may feel slow."
    return "Your connection is stable enough for most tasks."


def _diagnostic_recommendations(
    latency_ms: float,
    packet_loss: float,
    dns_ms: float,
    download_mbps: float,
) -> list[dict[str, str]]:
    candidates: list[tuple[int, dict[str, str]]] = []

    if packet_loss >= 5:
        candidates.extend(
            [
                (100, {"title": "Move closer to router", "impact": "high", "time": "instant"}),
                (95, {"title": "Restart router", "impact": "high", "time": "2 min"}),
                (90, {"title": "Disconnect background devices", "impact": "medium", "time": "1 min"}),
            ]
        )

    if latency_ms >= 140:
        candidates.extend(
            [
                (86, {"title": "Reduce live traffic", "impact": "high", "time": "instant"}),
                (82, {"title": "Move closer to router", "impact": "medium", "time": "instant"}),
                (70, {"title": "Retry later", "impact": "medium", "time": "5 min"}),
            ]
        )

    if dns_ms >= 90:
        candidates.append((88, {"title": "Switch DNS to 8.8.8.8", "impact": "high", "time": "30 sec"}))

    if download_mbps < 12:
        candidates.extend(
            [
                (84, {"title": "Pause downloads", "impact": "high", "time": "instant"}),
                (79, {"title": "Disconnect background devices", "impact": "high", "time": "1 min"}),
            ]
        )

    candidates.extend(
        [
            (30, {"title": "Switch DNS to 8.8.8.8", "impact": "medium", "time": "30 sec"}),
            (20, {"title": "Disconnect background devices", "impact": "medium", "time": "1 min"}),
            (10, {"title": "Move closer to router", "impact": "medium", "time": "instant"}),
        ]
    )

    seen_titles: set[str] = set()
    recommendations = []
    for _, recommendation in sorted(candidates, key=lambda item: item[0], reverse=True):
        if recommendation["title"] in seen_titles:
            continue
        seen_titles.add(recommendation["title"])
        recommendations.append(recommendation)
        if len(recommendations) == 3:
            break

    return recommendations


def _task_scores(
    latency_ms: float,
    packet_loss: float,
    dns_ms: float,
    download_mbps: float,
    score: int,
) -> dict[str, int]:
    latency = max(latency_ms - 60, 0)
    dns = max(dns_ms - 90, 0)
    low_download = max(18 - download_mbps, 0)

    email = score + 12 - packet_loss * 1.2 - dns * 0.08
    video_call = score + 8 - packet_loss * 4.4 - latency * 0.11 - low_download * 0.8
    upload_1gb = score - 8 + download_mbps * 1.15 - packet_loss * 2.8 - latency * 0.025
    music = score + 14 - packet_loss * 1.5 - max(download_mbps - 3, 0) * -0.08
    video_4k = score - 18 + download_mbps * 1.35 - packet_loss * 2.4 - latency * 0.035
    whatsapp = score + 15 - packet_loss * 1.4 - latency * 0.025

    return {
        "email": round(clamp(email, 8, 99)),
        "video_call": round(clamp(video_call, 5, 99)),
        "upload_1gb": round(clamp(upload_1gb, 5, 99)),
        "music": round(clamp(music, 8, 99)),
        "video_4k": round(clamp(video_4k, 5, 99)),
        "whatsapp": round(clamp(whatsapp, 8, 99)),
    }


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _build_summary(metrics: AssistantSummaryRequest) -> str:
    if metrics.packet_loss > 10:
        return "Your connection is unstable due to packet loss."
    if metrics.latency_ms > 150:
        return "Your connection is slow due to high latency."
    if metrics.download_mbps < 5:
        return "Your connection has weak bandwidth."
    return "Your connection looks healthy."


def _build_recommendations(metrics: AssistantSummaryRequest) -> list[dict[str, str]]:
    recommendations: list[tuple[int, dict[str, str]]] = []

    if metrics.packet_loss > 10:
        recommendations.extend(
            [
                (
                    100,
                    {
                        "title": "Disconnect other devices",
                        "impact": "high",
                        "time": "1 min",
                    },
                ),
                (
                    90,
                    {
                        "title": "Restart your router",
                        "impact": "high",
                        "time": "2 min",
                    },
                ),
                (
                    80,
                    {
                        "title": "Move closer to router",
                        "impact": "medium",
                        "time": "instant",
                    },
                ),
            ]
        )

    if metrics.latency_ms > 150:
        recommendations.extend(
            [
                (
                    70,
                    {
                        "title": "Pause video calls and game downloads",
                        "impact": "high",
                        "time": "instant",
                    },
                ),
                (
                    60,
                    {
                        "title": "Use a wired connection",
                        "impact": "medium",
                        "time": "3 min",
                    },
                ),
            ]
        )

    if metrics.download_mbps < 5:
        recommendations.extend(
            [
                (
                    50,
                    {
                        "title": "Disconnect other devices",
                        "impact": "high",
                        "time": "1 min",
                    },
                ),
                (
                    40,
                    {
                        "title": "Move closer to router",
                        "impact": "medium",
                        "time": "instant",
                    },
                ),
            ]
        )

    if not recommendations:
        recommendations.append(
            (
                10,
                {
                    "title": "Keep your current setup",
                    "impact": "low",
                    "time": "instant",
                },
            )
        )

    seen_titles: set[str] = set()
    ranked = []
    for _, recommendation in sorted(recommendations, key=lambda item: item[0], reverse=True):
        if recommendation["title"] in seen_titles:
            continue
        seen_titles.add(recommendation["title"])
        ranked.append(recommendation)

    return ranked


def _check_task_readiness(metrics: AssistantTaskCheckRequest) -> dict[str, str | float]:
    task = metrics.task.lower()

    if any(keyword in task for keyword in ("zoom", "teams", "meet", "video", "call")):
        if metrics.latency_ms < 150 and metrics.packet_loss < 5:
            return {
                "verdict": "yes",
                "confidence": 0.92,
                "explanation": "Your latency and packet loss are low enough for a stable video call.",
                "fallback": "Keep other high-bandwidth apps closed during the call.",
            }
        if metrics.latency_ms < 220 and metrics.packet_loss < 10:
            return {
                "verdict": "maybe",
                "confidence": 0.64,
                "explanation": "A video call should connect, but you may notice lag or brief audio drops.",
                "fallback": "Turn off HD video or join with audio only if the call stutters.",
            }
        return {
            "verdict": "no",
            "confidence": 0.88,
            "explanation": "High latency or packet loss will likely make a video call unreliable.",
            "fallback": "Use audio only or move closer to the router before joining.",
        }

    if any(keyword in task for keyword in ("upload", "send file", "backup", "cloud", "drive")):
        if metrics.download_mbps > 5:
            return {
                "verdict": "yes",
                "confidence": 0.86,
                "explanation": "Your bandwidth looks strong enough to handle the upload task.",
                "fallback": "Keep the upload window open until it completes.",
            }
        if metrics.download_mbps >= 3:
            return {
                "verdict": "maybe",
                "confidence": 0.58,
                "explanation": "The upload may work, but it could take longer than usual.",
                "fallback": "Try uploading a smaller file first or wait for a stronger connection.",
            }
        return {
            "verdict": "no",
            "confidence": 0.82,
            "explanation": "Your available bandwidth is too weak for a reliable upload.",
            "fallback": "Pause streaming and downloads, then try again.",
        }

    if any(keyword in task for keyword in ("message", "chat", "text", "slack", "whatsapp")):
        if metrics.packet_loss <= 20:
            return {
                "verdict": "yes",
                "confidence": 0.95,
                "explanation": "Messaging should work because it can tolerate this connection quality.",
                "fallback": "Retry sending if an individual message hangs.",
            }
        return {
            "verdict": "no",
            "confidence": 0.76,
            "explanation": "Packet loss is high enough that messages may fail to send.",
            "fallback": "Switch networks or move closer to the router.",
        }

    score = _calculate_score(metrics.latency_ms, metrics.packet_loss, 45, metrics.download_mbps)
    if score >= 80:
        return {
            "verdict": "yes",
            "confidence": 0.78,
            "explanation": "Your connection looks healthy enough for this task.",
            "fallback": "Keep bandwidth-heavy apps closed if the task becomes unstable.",
        }
    if score >= 50:
        return {
            "verdict": "maybe",
            "confidence": 0.6,
            "explanation": "Your connection is usable, but performance may vary.",
            "fallback": "Try the task now and reduce background network activity if needed.",
        }
    return {
        "verdict": "no",
        "confidence": 0.74,
        "explanation": "Your connection quality is too weak for a reliable experience.",
        "fallback": "Reconnect to Wi-Fi or restart your router before trying again.",
    }


@app.post("/api/v1/diagnostics/run")
def run_diagnostics():
    latency_ms, packet_loss = _run_ping()
    dns_ms = _measure_dns_ms()
    download_mbps = _simulate_download_mbps(latency_ms, packet_loss)
    score = _calculate_score(latency_ms, packet_loss, dns_ms, download_mbps)

    result = {
        "score": score,
        "latency_ms": round(latency_ms),
        "packet_loss": round(packet_loss, 1),
        "dns_ms": round(dns_ms),
        "download_mbps": download_mbps,
        "status": _status_for_score(score),
    }
    result.update(
        {
            "verdict_title": _verdict_title(score),
            "verdict_subtitle": _verdict_subtitle(
                result["latency_ms"],
                result["packet_loss"],
                result["dns_ms"],
                result["download_mbps"],
                score,
            ),
            "recommendations": _diagnostic_recommendations(
                result["latency_ms"],
                result["packet_loss"],
                result["dns_ms"],
                result["download_mbps"],
            ),
            "tasks": _task_scores(
                result["latency_ms"],
                result["packet_loss"],
                result["dns_ms"],
                result["download_mbps"],
                score,
            ),
        }
    )
    result_saved = _save_diagnostic(result)
    if not result_saved:
        result["history_saved"] = False
    return result


@app.get("/api/v1/diagnostics/history")
def diagnostics_history():
    return _get_diagnostics_history()


@app.post("/api/v1/assistant/summary")
def assistant_summary(metrics: AssistantSummaryRequest):
    return {
        "summary": _build_summary(metrics),
        "recommendations": _build_recommendations(metrics),
    }


@app.post("/api/v1/assistant/check-task")
def assistant_check_task(metrics: AssistantTaskCheckRequest):
    return _check_task_readiness(metrics)
