import analysis

HEALTHY = {
    "latency_ms": 25, "jitter_ms": 3, "packet_loss": 0, "dns_ms": 20,
    "download_mbps": 80, "upload_mbps": 20, "gateway_ms": 2, "gateway_loss": 0, "gateway_jitter_ms": 1,
}


def with_(**changes):
    return {**HEALTHY, **changes}


def verdicts(metrics):
    return {task["key"]: task["verdict"] for task in analysis.evaluate_tasks(metrics)}


def test_healthy_connection():
    result = analysis.analyze(HEALTHY)
    assert result["score"] == 100
    assert result["status"] == "good"
    assert result["location"]["where"] == "none"
    assert set(verdicts(HEALTHY).values()) == {"yes"}
    assert result["fixes"] == []
    assert result["headline"] == "Everything you'd normally do will work."


def test_offline():
    result = analysis.analyze(with_(packet_loss=100, latency_ms=None, jitter_ms=None))
    assert result["score"] == 0 and result["status"] == "offline"
    assert result["location"]["where"] == "isp"  # router answered
    assert set(verdicts(with_(packet_loss=100)).values()) == {"no"}
    assert result["fixes"][0]["id"] == "restart_router"


def test_wifi_problem_is_located_locally():
    metrics = with_(gateway_ms=85, gateway_loss=6, latency_ms=140, packet_loss=6)
    result = analysis.analyze(metrics)
    assert result["location"]["where"] == "local"
    assert result["fixes"][0]["id"] == "move_closer"


def test_isp_problem_when_router_is_fine():
    metrics = with_(latency_ms=320, packet_loss=4)
    result = analysis.analyze(metrics)
    assert result["location"]["where"] == "isp"
    assert "contact_isp" in [fix["id"] for fix in result["fixes"]]
    assert "move_closer" not in [fix["id"] for fix in result["fixes"]]


def test_video_call_limited_by_jitter():
    task = analysis.evaluate_task(analysis.TASKS_BY_KEY["video_call"], with_(jitter_ms=45))
    assert task["verdict"] == "shaky"
    assert "jitter" in task["reason"]


def test_skipped_throughput_is_not_penalised_or_guessed():
    metrics = with_(download_mbps=None, upload_mbps=None)
    assert analysis.score(metrics) == 100
    upload = analysis.evaluate_task(analysis.TASKS_BY_KEY["upload_large"], metrics)
    assert upload["verdict"] == "yes"
    assert "upload" in upload["untested"]
    streaming = analysis.evaluate_task(analysis.TASKS_BY_KEY["video_4k"], metrics)
    assert "download" in streaming["untested"]


def test_task_with_nothing_measured_is_unknown():
    task = analysis.evaluate_task(analysis.TASKS_BY_KEY["hd_video"], {})
    assert task["verdict"] == "unknown"


def test_upload_estimate():
    task = analysis.evaluate_task(analysis.TASKS_BY_KEY["upload_large"], with_(upload_mbps=4))
    assert task["verdict"] == "shaky"
    assert task["reason"].startswith("About 33 min")


def test_score_drops_with_loss_and_latency():
    assert analysis.score(with_(packet_loss=5)) < analysis.score(with_(packet_loss=1)) < 100
    assert analysis.score(with_(latency_ms=250)) < analysis.score(with_(latency_ms=100))


def test_match_task():
    assert analysis.match_task("Can I join a Zoom meeting?").key == "video_call"
    assert analysis.match_task("whatsapp call my mum").key == "voice_call"
    assert analysis.match_task("send a whatsapp").key == "messaging"
    assert analysis.match_task("upload my assignment").key == "upload_large"
    assert analysis.match_task("watch 4k youtube").key == "video_4k"
    assert analysis.match_task("talk to the admin") is None


def test_slow_dns_recommends_dns_switch():
    result = analysis.analyze(with_(dns_ms=300))
    assert [fix["id"] for fix in result["fixes"]] == ["switch_dns"]


def test_readings_rating():
    assert analysis.rate_reading("latency_ms", 40) == "good"
    assert analysis.rate_reading("latency_ms", 100) == "fair"
    assert analysis.rate_reading("download_mbps", 3) == "poor"
    assert analysis.rate_reading("upload_mbps", None) == "unknown"


def test_bad_but_online_connection_is_not_scored_like_offline():
    terrible = with_(packet_loss=12.5, latency_ms=168, jitter_ms=41, download_mbps=6.4, upload_mbps=1.4)
    assert 0 < analysis.score(terrible) < 55


def test_nothing_measured_is_not_reported_as_healthy():
    result = analysis.analyze({"errors": {"ping": "The ping command is not available on this system."}})
    assert result["score"] is None and result["status"] == "unmeasured"
    assert "couldn't measure" in result["headline"]
    assert {task["verdict"] for task in result["tasks"]} == {"unknown"}
    assert result["location"]["detail"].startswith("The ping command")
