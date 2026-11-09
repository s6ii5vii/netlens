import subprocess

import measure

WINDOWS_OUTPUT = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=24ms TTL=117
Reply from 8.8.8.8: bytes=32 time=31ms TTL=117
Request timed out.
Reply from 8.8.8.8: bytes=32 time<1ms TTL=117

Ping statistics for 8.8.8.8:
    Packets: Sent = 4, Received = 3, Lost = 1 (25% loss),
Approximate round trip times in milli-seconds:
    Minimum = 1ms, Maximum = 31ms, Average = 18ms
"""

WINDOWS_GERMAN_OUTPUT = """
Ping wird ausgeführt für 8.8.8.8 mit 32 Bytes Daten:
Antwort von 8.8.8.8: Bytes=32 Zeit=20ms TTL=117
Antwort von 8.8.8.8: Bytes=32 Zeit=22ms TTL=117
"""

WINDOWS_UNREACHABLE = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 192.168.1.1: Destination host unreachable.
Reply from 192.168.1.1: Destination host unreachable.
"""

LINUX_OUTPUT = """
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=14.2 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=18.6 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=18.9 ms (DUP!)
64 bytes from 8.8.8.8: icmp_seq=3 ttl=117 time=12.0 ms

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 12.0/14.9/18.6/2.7 ms
"""

MACOS_OUTPUT = """
PING 8.8.8.8 (8.8.8.8): 56 data bytes
64 bytes from 8.8.8.8: icmp_seq=0 ttl=116 time=21.312 ms
64 bytes from 8.8.8.8: icmp_seq=1 ttl=116 time=19.004 ms
Request timeout for icmp_seq 2
"""


def test_parses_windows_replies_including_sub_millisecond():
    assert measure.parse_ping_replies(WINDOWS_OUTPUT) == [24.0, 31.0, 1.0]


def test_parses_localized_windows_output():
    assert measure.parse_ping_replies(WINDOWS_GERMAN_OUTPUT) == [20.0, 22.0]


def test_unreachable_replies_are_not_counted_as_success():
    assert measure.parse_ping_replies(WINDOWS_UNREACHABLE) == []


def test_parses_linux_and_ignores_duplicates():
    assert measure.parse_ping_replies(LINUX_OUTPUT) == [14.2, 18.6, 12.0]


def test_parses_macos():
    assert measure.parse_ping_replies(MACOS_OUTPUT) == [21.312, 19.004]


def test_ping_commands_per_platform():
    assert measure.build_ping_command("1.1.1.1", 8, "Windows")[:3] == ["ping", "-n", "8"]
    assert measure.build_ping_command("1.1.1.1", 8, "Linux")[:3] == ["ping", "-c", "8"]
    assert measure.build_ping_command("1.1.1.1", 8, "Darwin")[:3] == ["ping", "-c", "8"]


def test_jitter_is_mean_consecutive_difference():
    assert measure.jitter_ms([10, 20, 10, 30]) == round((10 + 10 + 20) / 3, 1)
    assert measure.jitter_ms([10]) is None


def _runner(stdout="", raises=None):
    def run(*_args, **_kwargs):
        if raises:
            raise raises
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    return run


def test_ping_result_from_output():
    result = measure.ping("8.8.8.8", count=4, runner=_runner(WINDOWS_OUTPUT))
    assert result.ok
    assert result.loss == 25.0
    assert result.latency == round((24 + 31 + 1) / 3, 1)


def test_no_replies_is_full_loss_not_an_error():
    result = measure.ping("8.8.8.8", count=2, runner=_runner(WINDOWS_UNREACHABLE))
    assert result.ok and result.loss == 100.0 and result.latency is None


def test_missing_ping_is_reported_not_faked():
    result = measure.ping("8.8.8.8", runner=_runner(raises=FileNotFoundError()))
    assert not result.ok
    assert result.loss is None and result.latency is None


def test_linux_route_table():
    table = (
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
        "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\n"
        "eth0\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\n"
    )
    assert measure.parse_linux_route_table(table) == "192.168.1.1"


def test_macos_route():
    assert measure.parse_macos_route("   route to: default\n    gateway: 10.0.0.1\n") == "10.0.0.1"


def test_windows_route_print_picks_lowest_metric():
    text = """
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.0.1    192.168.0.20     55
          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.10     25
"""
    assert measure.parse_windows_route_print(text) == "192.168.1.1"
