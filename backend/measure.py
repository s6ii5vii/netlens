"""Network measurements taken from the user's own machine.

Every function here returns real measurements or reports that it could not
measure. Nothing is estimated or simulated: a value of ``None`` means "not
measured", and the reason is recorded alongside it.
"""

from __future__ import annotations

import http.client
import os
import platform
import re
import socket
import statistics
import struct
import subprocess
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterator

INTERNET_HOST = os.getenv("NETLENS_PING_HOST", "8.8.8.8")
PING_COUNT = 8
DNS_HOSTS = ("google.com", "cloudflare.com", "wikipedia.org")

DOWNLOAD_URL = "https://speed.cloudflare.com/__down?bytes={size}"
UPLOAD_URL = "https://speed.cloudflare.com/__up"
DOWNLOAD_MAX_BYTES = 10_000_000
UPLOAD_MAX_BYTES = 3_000_000
TRANSFER_MAX_SECONDS = 8.0
USER_AGENT = "NetLens/0.2"

# Keep subprocesses from flashing a console window on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class PingResult:
    host: str
    sent: int
    rtts: list[float] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def received(self) -> int:
        return len(self.rtts)

    @property
    def loss(self) -> float | None:
        if not self.ok or self.sent == 0:
            return None
        return round((self.sent - self.received) / self.sent * 100, 1)

    @property
    def latency(self) -> float | None:
        return round(statistics.fmean(self.rtts), 1) if self.rtts else None

    @property
    def jitter(self) -> float | None:
        return jitter_ms(self.rtts)


# --------------------------------------------------------------------------
# Ping
# --------------------------------------------------------------------------

def build_ping_command(host: str, count: int, system: str | None = None) -> list[str]:
    system = system or platform.system()
    if system == "Windows":
        return ["ping", "-n", str(count), "-w", "2000", host]
    if system == "Darwin":
        return ["ping", "-c", str(count), "-W", "2000", host]  # -W is milliseconds on macOS
    return ["ping", "-c", str(count), "-W", "2", host]  # -W is seconds on Linux


_REPLY_TIME = re.compile(r"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE)


def parse_ping_replies(output: str) -> list[float]:
    """Extract one round-trip time per reply line.

    Reply lines contain a TTL field on every platform and in every Windows
    language, so we key off that instead of the localized summary text.
    """
    rtts: list[float] = []
    for line in output.splitlines():
        if "ttl" not in line.lower() or "DUP!" in line:
            continue
        match = _REPLY_TIME.search(line)
        if match:
            rtts.append(float(match.group(1).replace(",", ".")))
    return rtts


def jitter_ms(rtts: list[float]) -> float | None:
    """Mean absolute difference between consecutive round trips."""
    if len(rtts) < 2:
        return None
    diffs = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
    return round(statistics.fmean(diffs), 1)


def ping(host: str, count: int = PING_COUNT, runner: Callable = subprocess.run) -> PingResult:
    command = build_ping_command(host, count)
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=count * 3 + 5,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        return PingResult(host, count, error="The ping command is not available on this system.")
    except subprocess.TimeoutExpired:
        return PingResult(host, count, error="Ping did not finish in time.")
    except (OSError, subprocess.SubprocessError) as exc:
        return PingResult(host, count, error=f"Ping could not run: {exc}")

    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    if not output.strip():
        return PingResult(host, count, error="Ping produced no output.")

    # No replies after ping ran normally is a real result: 100% packet loss.
    return PingResult(host, count, rtts=parse_ping_replies(output)[:count])


# --------------------------------------------------------------------------
# Default gateway (your router)
# --------------------------------------------------------------------------

def parse_linux_route_table(text: str) -> str | None:
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        destination, gateway, flags = parts[1], parts[2], int(parts[3], 16)
        if destination == "00000000" and flags & 0x2:
            return socket.inet_ntoa(struct.pack("<L", int(gateway, 16)))
    return None


def parse_macos_route(text: str) -> str | None:
    match = re.search(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)", text)
    return match.group(1) if match else None


def parse_windows_route_print(text: str) -> str | None:
    routes = re.findall(
        r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+\S+\s+(\d+)",
        text,
        re.MULTILINE,
    )
    if not routes:
        return None
    return min(routes, key=lambda route: int(route[1]))[0]


def default_gateway(system: str | None = None) -> str | None:
    system = system or platform.system()
    try:
        if system == "Linux":
            with open("/proc/net/route", encoding="ascii") as handle:
                return parse_linux_route_table(handle.read())
        if system == "Darwin":
            out = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True, timeout=5)
            return parse_macos_route(out.stdout)
        if system == "Windows":
            out = subprocess.run(
                ["route", "print", "-4", "0.0.0.0"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_NO_WINDOW,
            )
            return parse_windows_route_print(out.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


# --------------------------------------------------------------------------
# DNS
# --------------------------------------------------------------------------

def measure_dns(hosts: tuple[str, ...] = DNS_HOSTS) -> tuple[float | None, str | None]:
    """Median lookup time, as applications on this machine experience it."""
    timings = []
    for host in hosts:
        start = time.perf_counter()
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            continue
        timings.append((time.perf_counter() - start) * 1000)
    if not timings:
        return None, "No DNS lookups succeeded."
    return round(statistics.median(timings), 1), None


# --------------------------------------------------------------------------
# Throughput
# --------------------------------------------------------------------------

def _mbps(byte_count: int, seconds: float) -> float:
    return round(byte_count * 8 / seconds / 1_000_000, 2)


def measure_download(
    max_bytes: int = DOWNLOAD_MAX_BYTES,
    max_seconds: float = TRANSFER_MAX_SECONDS,
) -> tuple[float | None, str | None]:
    request = urllib.request.Request(
        DOWNLOAD_URL.format(size=max_bytes),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            first_byte_at = None
            counted = 0
            while True:
                chunk = response.read(64 * 1024)
                now = time.perf_counter()
                if not chunk:
                    break
                if first_byte_at is None:
                    # Start the clock at the first byte so latency doesn't count as slowness.
                    first_byte_at = now
                    continue
                counted += len(chunk)
                if now - first_byte_at >= max_seconds:
                    break
    except (OSError, http.client.HTTPException) as exc:
        return None, f"Download test failed: {exc}"

    if first_byte_at is None or counted == 0:
        return None, "Download test received too little data to measure."
    elapsed = max(time.perf_counter() - first_byte_at, 0.001)
    return _mbps(counted, elapsed), None


def _https_connection(url: str, timeout: float) -> http.client.HTTPSConnection:
    target = urllib.parse.urlsplit(url)
    proxy = urllib.request.getproxies().get("https")
    if proxy and not urllib.request.proxy_bypass(target.hostname or ""):
        proxy_url = urllib.parse.urlsplit(proxy)
        connection = http.client.HTTPSConnection(proxy_url.hostname, proxy_url.port or 443, timeout=timeout)
        connection.set_tunnel(target.hostname, target.port or 443)
        return connection
    return http.client.HTTPSConnection(target.hostname, target.port or 443, timeout=timeout)


def measure_upload(
    max_bytes: int = UPLOAD_MAX_BYTES,
    max_seconds: float = TRANSFER_MAX_SECONDS,
) -> tuple[float | None, str | None]:
    chunk = os.urandom(64 * 1024)
    sent = 0
    try:
        connection = _https_connection(UPLOAD_URL, timeout=10)
        try:
            path = urllib.parse.urlsplit(UPLOAD_URL).path
            connection.putrequest("POST", path)
            connection.putheader("User-Agent", USER_AGENT)
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Transfer-Encoding", "chunked")
            connection.endheaders()
            start = time.perf_counter()
            # Chunked encoding lets us stop early on slow uplinks instead of
            # committing to a fixed size up front.
            while sent < max_bytes and time.perf_counter() - start < max_seconds:
                connection.send(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                sent += len(chunk)
            connection.send(b"0\r\n\r\n")
            response = connection.getresponse()
            response.read()
            elapsed = max(time.perf_counter() - start, 0.001)
        finally:
            connection.close()
    except (OSError, http.client.HTTPException) as exc:
        return None, f"Upload test failed: {exc}"

    if response.status >= 400:
        return None, f"Upload test was rejected (HTTP {response.status})."
    return _mbps(sent, elapsed), None


# --------------------------------------------------------------------------
# Full scan
# --------------------------------------------------------------------------

def run_scan(include_throughput: bool = True) -> Iterator[tuple[str, dict]]:
    """Run each measurement in turn, yielding ``(stage, partial_result)``.

    Stages: ``path`` (router + internet ping), ``dns``, ``download``, ``upload``.
    The caller merges the partial dictionaries into one measurement record.
    """
    gateway = default_gateway()
    with ThreadPoolExecutor(max_workers=2) as pool:
        internet_job = pool.submit(ping, INTERNET_HOST)
        gateway_job = pool.submit(ping, gateway) if gateway else None
        internet = internet_job.result()
        local = gateway_job.result() if gateway_job else None

    errors: dict[str, str] = {}
    if not internet.ok:
        errors["ping"] = internet.error or "Ping failed."
    if gateway is None:
        errors["gateway"] = "Could not find your router's address."
    elif local and not local.ok:
        errors["gateway"] = local.error or "Router ping failed."

    yield "path", {
        "ping_host": INTERNET_HOST,
        "latency_ms": internet.latency,
        "jitter_ms": internet.jitter,
        "packet_loss": internet.loss,
        "rtts": internet.rtts,
        "gateway_ip": gateway,
        "gateway_ms": local.latency if local else None,
        "gateway_jitter_ms": local.jitter if local else None,
        "gateway_loss": local.loss if local else None,
        "errors": errors,
    }

    dns_ms, dns_error = measure_dns()
    yield "dns", {"dns_ms": dns_ms, "errors": {"dns": dns_error} if dns_error else {}}

    offline = internet.ok and internet.loss == 100
    if not include_throughput:
        skipped = {"download": "skipped", "upload": "skipped"}
        yield "download", {"download_mbps": None, "errors": skipped}
        yield "upload", {"upload_mbps": None, "errors": {}}
        return
    if offline:
        reason = "Skipped because the internet is unreachable."
        yield "download", {"download_mbps": None, "errors": {"download": reason}}
        yield "upload", {"upload_mbps": None, "errors": {"upload": reason}}
        return

    download, download_error = measure_download()
    yield "download", {"download_mbps": download, "errors": {"download": download_error} if download_error else {}}
    upload, upload_error = measure_upload()
    yield "upload", {"upload_mbps": upload, "errors": {"upload": upload_error} if upload_error else {}}
