"""Rule-based analysis of a set of network measurements.

One engine produces everything the dashboard shows — score, headline,
where the problem is, task verdicts and fixes — so the different parts of
the app can never disagree with each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

Metrics = dict[str, Any]

METRIC_LABELS = {
    "latency_ms": ("latency", "ms"),
    "jitter_ms": ("jitter", "ms"),
    "packet_loss": ("packet loss", "%"),
    "dns_ms": ("DNS lookup", "ms"),
    "download_mbps": ("download", "Mb/s"),
    "upload_mbps": ("upload", "Mb/s"),
}

# Metrics where a lower number is better. Everything else is higher-is-better.
LOWER_IS_BETTER = {"latency_ms", "jitter_ms", "packet_loss", "dns_ms"}

# Thresholds used for the readings scale: (good up to / from, poor beyond).
READING_BANDS = {
    "latency_ms": (60, 150),
    "jitter_ms": (15, 40),
    "packet_loss": (1, 5),
    "dns_ms": (60, 150),
    "download_mbps": (25, 5),
    "upload_mbps": (10, 2),
}


def _num(metrics: Metrics, key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _fmt(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:g}%"
    if unit == "Mb/s":
        return f"{value:.1f} Mb/s" if value < 10 else f"{value:.0f} Mb/s"
    return f"{value:.0f} {unit}"


def is_offline(metrics: Metrics) -> bool:
    return _num(metrics, "packet_loss") == 100


# --------------------------------------------------------------------------
# Readings
# --------------------------------------------------------------------------

def rate_reading(key: str, value: float | None) -> str:
    """Return good / fair / poor / unknown for a single reading."""
    if value is None:
        return "unknown"
    good, poor = READING_BANDS[key]
    if key in LOWER_IS_BETTER:
        return "good" if value <= good else "fair" if value <= poor else "poor"
    return "good" if value >= good else "fair" if value >= poor else "poor"


def readings(metrics: Metrics) -> dict[str, dict[str, Any]]:
    result = {}
    for key, (label, unit) in METRIC_LABELS.items():
        value = _num(metrics, key)
        good, poor = READING_BANDS[key]
        result[key] = {
            "label": label,
            "unit": unit,
            "value": value,
            "rating": rate_reading(key, value),
            "good": good,
            "poor": poor,
            "lower_is_better": key in LOWER_IS_BETTER,
        }
    return result


# --------------------------------------------------------------------------
# Score
# --------------------------------------------------------------------------

def score(metrics: Metrics) -> int:
    if is_offline(metrics):
        return 0

    # Caps add up to 100, so only a connection that is bad in every way reaches zero.
    penalties = {
        "packet_loss": lambda v: min(v * 5, 35),
        "latency_ms": lambda v: min(max(v - 40, 0) * 0.12, 20),
        "jitter_ms": lambda v: min(max(v - 10, 0) * 0.35, 12),
        "dns_ms": lambda v: min(max(v - 50, 0) * 0.08, 8),
        "download_mbps": lambda v: min(max(20 - v, 0) * 0.8, 15),
        "upload_mbps": lambda v: min(max(5 - v, 0) * 2, 10),
    }
    total = 100.0
    for key, penalty in penalties.items():
        value = _num(metrics, key)
        if value is not None:
            total -= penalty(value)
    return round(max(0.0, min(100.0, total)))


def status_for(score_value: int, metrics: Metrics) -> str:
    if is_offline(metrics):
        return "offline"
    if score_value >= 80:
        return "good"
    if score_value >= 55:
        return "fair"
    return "poor"


# --------------------------------------------------------------------------
# Where is the problem?
# --------------------------------------------------------------------------

def locate_problem(metrics: Metrics) -> dict[str, str]:
    """Compare the router hop with the internet hop.

    If the router itself responds slowly or drops packets, the trouble is on
    the local network (usually Wi-Fi). If the router is fine but the internet
    is not, the trouble is beyond the home network (the provider).
    """
    if is_offline(metrics):
        gw_loss = _num(metrics, "gateway_loss")
        if gw_loss is not None and gw_loss < 100:
            return {
                "where": "isp",
                "detail": "Your router answers, but nothing beyond it does. The internet line itself is down.",
            }
        if gw_loss == 100:
            return {
                "where": "local",
                "detail": "This device can't reach your router. Check that Wi-Fi is connected.",
            }
        return {"where": "unknown", "detail": "The internet is unreachable from this device."}

    gw_ms = _num(metrics, "gateway_ms")
    gw_loss = _num(metrics, "gateway_loss")
    gw_jitter = _num(metrics, "gateway_jitter_ms")
    latency = _num(metrics, "latency_ms")
    loss = _num(metrics, "packet_loss")
    jitter = _num(metrics, "jitter_ms")

    internet_bad = (
        (loss is not None and loss >= 3)
        or (latency is not None and latency > 150)
        or (jitter is not None and jitter > 30)
    )
    if gw_ms is None and gw_loss is None:
        if internet_bad:
            return {
                "where": "unknown",
                "detail": "The connection is unstable, but the router couldn't be tested to say where.",
            }
        return {"where": "none", "detail": "No trouble found along the path."}

    local_bad = (
        (gw_loss is not None and gw_loss >= 3)
        or (gw_ms is not None and gw_ms > 30)
        or (gw_jitter is not None and gw_jitter > 15)
    )
    if local_bad:
        return {
            "where": "local",
            "detail": (
                f"Your router itself is slow to answer ({_fmt(gw_ms or 0, 'ms')}, "
                f"{_fmt(gw_loss or 0, '%')} lost). The weak link is between this device and the router — usually Wi-Fi."
            ),
        }
    if internet_bad:
        return {
            "where": "isp",
            "detail": (
                f"Your router answers in {_fmt(gw_ms or 0, 'ms')}, but the internet takes "
                f"{_fmt(latency or 0, 'ms')}. The slowdown is beyond your home network."
            ),
        }
    return {"where": "none", "detail": "No trouble found along the path."}


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Need:
    metric: str
    ok: float  # fine at or better than this
    limit: float  # unusable beyond this; in between is "shaky"


@dataclass(frozen=True)
class Task:
    key: str
    label: str
    keywords: tuple[str, ...]
    needs: tuple[Need, ...]
    transfer_gb: float | None = None  # for "how long would it take" estimates
    transfer_metric: str | None = None
    priority: int = 0  # wins over other matches, e.g. "4k youtube" is 4K, not HD


TASKS: tuple[Task, ...] = (
    Task(
        "video_call",
        "Video call",
        ("zoom", "teams", "meet", "video call", "facetime", "webex", "interview", "lecture", "class"),
        (
            Need("latency_ms", 150, 300),
            Need("jitter_ms", 30, 60),
            Need("packet_loss", 2, 6),
            Need("download_mbps", 3, 1.2),
            Need("upload_mbps", 3, 1),
        ),
    ),
    Task(
        "voice_call",
        "Voice call",
        ("voice", "audio call", "phone call", "whatsapp call", "call", "voip"),
        (
            Need("latency_ms", 200, 350),
            Need("jitter_ms", 30, 70),
            Need("packet_loss", 3, 10),
            Need("upload_mbps", 0.2, 0.1),
        ),
    ),
    Task(
        "messaging",
        "Messaging",
        ("message", "chat", "text", "whatsapp", "telegram", "slack", "signal", "dm"),
        (Need("packet_loss", 10, 30), Need("latency_ms", 500, 1500)),
    ),
    Task(
        "browsing",
        "Email & browsing",
        ("email", "mail", "browse", "browsing", "web", "website", "search", "news", "docs"),
        (
            Need("packet_loss", 5, 15),
            Need("latency_ms", 300, 800),
            Need("dns_ms", 150, 400),
            Need("download_mbps", 2, 0.5),
        ),
    ),
    Task(
        "hd_video",
        "HD streaming",
        ("youtube", "netflix", "stream", "streaming", "watch", "hd", "1080", "movie", "tiktok"),
        (Need("download_mbps", 8, 4), Need("packet_loss", 5, 12)),
    ),
    Task(
        "video_4k",
        "4K streaming",
        ("4k", "uhd", "ultra hd"),
        (Need("download_mbps", 25, 15), Need("packet_loss", 3, 10)),
        priority=1,
    ),
    Task(
        "gaming",
        "Online gaming",
        ("game", "games", "gaming", "fortnite", "valorant", "fifa", "cod", "pubg", "multiplayer"),
        (Need("latency_ms", 80, 150), Need("jitter_ms", 15, 40), Need("packet_loss", 1, 4)),
    ),
    Task(
        "upload_large",
        "Large upload (1 GB)",
        ("upload", "send file", "backup", "google drive", "dropbox", "onedrive", "post video", "submit"),
        (Need("upload_mbps", 10, 2), Need("packet_loss", 3, 10)),
        transfer_gb=1,
        transfer_metric="upload_mbps",
    ),
    Task(
        "download_large",
        "Large download (1 GB)",
        ("download", "update", "install", "torrent"),
        (Need("download_mbps", 10, 2), Need("packet_loss", 5, 15)),
        transfer_gb=1,
        transfer_metric="download_mbps",
    ),
)

TASKS_BY_KEY = {task.key: task for task in TASKS}
_VERDICT_RANK = {"yes": 0, "shaky": 1, "no": 2}


def _judge(need: Need, value: float) -> str:
    if need.metric in LOWER_IS_BETTER:
        return "yes" if value <= need.ok else "shaky" if value <= need.limit else "no"
    return "yes" if value >= need.ok else "shaky" if value >= need.limit else "no"


def _requirement_text(need: Need) -> str:
    label, unit = METRIC_LABELS[need.metric]
    comparator = "under" if need.metric in LOWER_IS_BETTER else "at least"
    return f"{label} {comparator} {_fmt(need.ok, unit)}"


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} sec"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} hours"


def evaluate_task(task: Task, metrics: Metrics) -> dict[str, Any]:
    if is_offline(metrics):
        return {
            "key": task.key,
            "label": task.label,
            "verdict": "no",
            "reason": "You're offline right now.",
            "untested": [],
        }

    judged = []
    untested = []
    for need in task.needs:
        value = _num(metrics, need.metric)
        if value is None:
            untested.append(METRIC_LABELS[need.metric][0])
            continue
        judged.append((need, value, _judge(need, value)))

    if not judged:
        return {
            "key": task.key,
            "label": task.label,
            "verdict": "unknown",
            "reason": f"Not tested — needs a {' and '.join(untested)} reading.",
            "untested": untested,
        }

    need, value, verdict = max(judged, key=lambda item: _VERDICT_RANK[item[2]])
    label, unit = METRIC_LABELS[need.metric]
    if verdict == "yes":
        reason = "Everything this needs is within range."
    else:
        reason = f"Needs {_requirement_text(need)} — you have {_fmt(value, unit)}."

    if task.transfer_gb and task.transfer_metric:
        speed = _num(metrics, task.transfer_metric)
        if speed:
            estimate = _duration(task.transfer_gb * 8000 / speed)
            reason = f"About {estimate} at {_fmt(speed, 'Mb/s')}. " + ("" if verdict == "yes" else reason)

    return {
        "key": task.key,
        "label": task.label,
        "verdict": verdict,
        "reason": reason.strip(),
        "untested": untested,
    }


def evaluate_tasks(metrics: Metrics) -> list[dict[str, Any]]:
    return [evaluate_task(task, metrics) for task in TASKS]


def match_task(text: str) -> Task | None:
    """Pick the task whose most specific keyword appears as whole words in ``text``."""
    lowered = text.lower()
    best: tuple[tuple[int, int], Task] | None = None
    for task in TASKS:
        for keyword in task.keywords:
            rank = (task.priority, len(keyword))
            if re.search(rf"\b{re.escape(keyword)}\b", lowered) and (best is None or rank > best[0]):
                best = (rank, task)
    return best[1] if best else None


# --------------------------------------------------------------------------
# Fixes
# --------------------------------------------------------------------------

FIXES: dict[str, dict[str, Any]] = {
    "check_wifi": {
        "title": "Check that you're connected",
        "time": "1 min",
        "steps": [
            "Open your Wi-Fi settings and confirm you're joined to the right network.",
            "Turn Wi-Fi off and on again, or unplug and replug the network cable.",
            "If other devices are also offline, the problem is the router or the line.",
        ],
    },
    "move_closer": {
        "title": "Move closer to the router",
        "time": "instant",
        "steps": [
            "Move into the same room as the router if you can.",
            "Keep walls, metal furniture and microwaves out of the way.",
            "Run a new scan and compare the router reading.",
        ],
    },
    "use_cable": {
        "title": "Use a network cable",
        "time": "3 min",
        "steps": [
            "Connect this device to the router with an Ethernet cable.",
            "Turn Wi-Fi off so traffic goes over the cable.",
            "Run a new scan. A cable removes Wi-Fi interference completely.",
        ],
    },
    "restart_router": {
        "title": "Restart the router",
        "time": "3 min",
        "steps": [
            "Unplug the router's power cable.",
            "Wait 20 seconds, then plug it back in.",
            "Give it two minutes to reconnect, then run a new scan.",
        ],
        "note": "Everyone on the network will be disconnected briefly.",
    },
    "pause_traffic": {
        "title": "Pause downloads and streams",
        "time": "1 min",
        "steps": [
            "Pause app updates, cloud backups and browser downloads.",
            "Stop video streams on other devices, or drop them to a lower quality.",
            "Run a new scan once the network has settled.",
        ],
        "note": "Heavy transfers fill the line and make calls lag even when speed looks fine.",
    },
    "switch_dns": {
        "title": "Switch to a faster DNS server",
        "time": "2 min",
        "steps": [
            "Open the settings for your active Wi-Fi or Ethernet connection.",
            "Set DNS to 1.1.1.1 (backup 8.8.8.8).",
            "Save, then run a new scan to compare the DNS reading.",
        ],
        "note": "This only speeds up how quickly pages start loading, not overall speed.",
    },
    "contact_isp": {
        "title": "Report it to your provider",
        "time": "10 min",
        "steps": [
            "Export your scan log (bottom of this page) as evidence.",
            "Tell your provider your router responds quickly but internet traffic is slow or dropping.",
            "Ask whether there's an outage or line fault in your area.",
        ],
    },
    "use_hotspot": {
        "title": "Try a mobile hotspot",
        "time": "2 min",
        "steps": [
            "Turn on the hotspot on your phone and connect this device to it.",
            "Run a new scan and compare.",
            "If it's better, use the hotspot for the task that can't wait.",
        ],
        "note": "This uses mobile data.",
    },
    "lower_quality": {
        "title": "Lower video quality",
        "time": "instant",
        "steps": [
            "Turn off your camera, or switch the call to audio only.",
            "For streaming, choose 480p or 720p instead of Auto.",
        ],
    },
    "retry_later": {
        "title": "Try again later",
        "time": "15 min",
        "steps": [
            "Provider congestion often clears outside peak evening hours.",
            "Run a new scan in 15 minutes and compare in the log below.",
        ],
    },
}


def recommend(metrics: Metrics, location: dict[str, str]) -> list[dict[str, Any]]:
    where = location["where"]
    picks: list[tuple[int, str, str]] = []  # (priority, fix id, why)

    def add(priority: int, fix_id: str, why: str) -> None:
        picks.append((priority, fix_id, why))

    latency = _num(metrics, "latency_ms")
    loss = _num(metrics, "packet_loss")
    jitter = _num(metrics, "jitter_ms")
    dns = _num(metrics, "dns_ms")
    download = _num(metrics, "download_mbps")
    upload = _num(metrics, "upload_mbps")

    if is_offline(metrics):
        if where == "isp":
            add(100, "restart_router", "The router is reachable but the internet behind it isn't.")
            add(90, "contact_isp", "If a restart doesn't help, the line itself may be down.")
            add(80, "use_hotspot", "A hotspot gets you online while the line is down.")
        else:
            add(100, "check_wifi", "This device can't reach the internet at all.")
            add(90, "restart_router", "A restart clears most stuck connections.")
        return _finalize(picks)

    if where == "local":
        add(100, "move_closer", location["detail"])
        add(95, "use_cable", "A cable bypasses Wi-Fi problems entirely.")
        add(70, "restart_router", "Restarting can clear radio interference and a stuck router.")
    elif where == "isp":
        add(90, "restart_router", "A restart makes the router reconnect to your provider, which sometimes clears the problem.")
        add(85, "retry_later", location["detail"])
        add(80, "contact_isp", "If this keeps happening, your provider needs to know.")
        add(60, "use_hotspot", "A hotspot can stand in for urgent calls.")
    elif loss is not None and loss >= 3:
        add(90, "restart_router", f"{_fmt(loss, '%')} of packets were lost.")
        add(85, "move_closer", "Packet loss is often caused by a weak Wi-Fi signal.")

    if jitter is not None and jitter > 30:
        add(88, "pause_traffic", f"Latency is swinging by {_fmt(jitter, 'ms')} between packets — typical of a busy line.")
    if (download is not None and download < 5) or (upload is not None and upload < 2):
        slow = []
        if download is not None and download < 5:
            slow.append(f"download is {_fmt(download, 'Mb/s')}")
        if upload is not None and upload < 2:
            slow.append(f"upload is {_fmt(upload, 'Mb/s')}")
        add(86, "pause_traffic", f"Bandwidth is tight: {' and '.join(slow)}.")
        add(50, "lower_quality", "Lower quality video needs far less bandwidth.")
    if latency is not None and latency > 150 and where != "isp":
        add(65, "lower_quality", f"At {_fmt(latency, 'ms')} latency, video calls will lag; audio holds up better.")
    if dns is not None and dns > 150:
        add(75, "switch_dns", f"DNS lookups take {_fmt(dns, 'ms')}, so pages are slow to start.")

    return _finalize(picks)


def _finalize(picks: list[tuple[int, str, str]], limit: int = 4) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for _priority, fix_id, why in sorted(picks, key=lambda pick: pick[0], reverse=True):
        if fix_id in seen:
            continue
        seen.add(fix_id)
        result.append({"id": fix_id, "why": why, **FIXES[fix_id]})
        if len(result) == limit:
            break
    return result


# --------------------------------------------------------------------------
# Headline
# --------------------------------------------------------------------------

def headline(status: str, tasks: list[dict[str, Any]]) -> str:
    if status == "offline":
        return "You're offline."
    by_key = {task["key"]: task["verdict"] for task in tasks}
    blocked = [task["label"].lower() for task in tasks if task["verdict"] == "no"]
    shaky = [task["label"].lower() for task in tasks if task["verdict"] == "shaky"]

    if not blocked and not shaky:
        return "Everything you'd normally do will work."
    if by_key.get("browsing") == "no" and by_key.get("messaging") == "no":
        return "Barely usable right now."
    if by_key.get("video_call") == "no":
        return "Video calls won't hold up right now."
    if by_key.get("video_call") == "shaky":
        return "Video calls will be shaky."
    if blocked:
        return f"Fine for most things — not for {_join(blocked[:2])}."
    return f"Mostly fine — {_join(shaky[:2])} may struggle."


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def analyze(metrics: Metrics) -> dict[str, Any]:
    if _num(metrics, "packet_loss") is None:
        # The internet ping didn't run, so there is nothing trustworthy to judge.
        reason = (metrics.get("errors") or {}).get("ping") or "The internet test could not run."
        return {
            "score": None,
            "status": "unmeasured",
            "headline": "NetLens couldn't measure this connection.",
            "location": {"where": "unknown", "detail": reason},
            "readings": readings(metrics),
            "tasks": [
                {"key": t.key, "label": t.label, "verdict": "unknown", "reason": "Not measured.", "untested": []}
                for t in TASKS
            ],
            "fixes": [],
        }

    score_value = score(metrics)
    status = status_for(score_value, metrics)
    location = locate_problem(metrics)
    tasks = evaluate_tasks(metrics)
    return {
        "score": score_value,
        "status": status,
        "headline": headline(status, tasks),
        "location": location,
        "readings": readings(metrics),
        "tasks": tasks,
        "fixes": recommend(metrics, location),
    }
