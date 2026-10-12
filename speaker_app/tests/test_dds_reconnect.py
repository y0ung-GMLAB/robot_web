"""스피커 DDS · Wi-Fi 가 바뀌거나 끊겼다 다른 주소로 붙으면 저절로 다시 연동 (2026-10-12)

Fast DDS 는 참가자를 만드는 순간의 주소만 광고한다 · 주소가 바뀌면 옛 주소를 광고한 채
남아 로봇 PC 를 영영 못 찾았다 · 스피커는 모터가 없어 다시 시작해도 안전하다.
"""
import os
import sys
import threading
import time
import types

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import dds_listener  # noqa: E402
import sysinfo  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def add(self, text):
        self.lines.append(text)


def _fake_ros(monkeypatch, inits):
    """rclpy · 메시지 대역 · init 할 때마다 기록"""
    rclpy = types.ModuleType("rclpy")
    rclpy.init = lambda context=None, domain_id=0: inits.append(domain_id)
    rclpy.shutdown = lambda context=None: None

    class Node:
        def create_subscription(self, *_a):
            return None

        def count_publishers(self, _topic):
            return 1

        def destroy_node(self):
            pass

    rclpy.create_node = lambda *_a, **_k: Node()
    context = types.ModuleType("rclpy.context")
    context.Context = object

    class Executor:
        def __init__(self, context=None):
            pass

        def add_node(self, _node):
            pass

        def spin_once(self, timeout_sec=0.0):
            time.sleep(0.01)

        def shutdown(self):
            pass

    executors = types.ModuleType("rclpy.executors")
    executors.SingleThreadedExecutor = Executor
    qos = types.ModuleType("rclpy.qos")
    for name in ("DurabilityPolicy", "HistoryPolicy", "ReliabilityPolicy"):
        setattr(qos, name, types.SimpleNamespace(VOLATILE=0, KEEP_LAST=0, BEST_EFFORT=0))
    qos.QoSProfile = lambda **_k: None
    msgs = types.ModuleType("motion_coordination_interfaces.msg")
    msgs.GroupCommand = msgs.GroupEvent = object
    pkg = types.ModuleType("motion_coordination_interfaces")
    pkg.msg = msgs
    for name, module in {"rclpy": rclpy, "rclpy.context": context, "rclpy.executors": executors,
                         "rclpy.qos": qos, "motion_coordination_interfaces": pkg,
                         "motion_coordination_interfaces.msg": msgs}.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(dds_listener, "NET_WAIT_SEC", 0)
    monkeypatch.setattr(dds_listener, "NET_RECHECK_SEC", 0.02)
    monkeypatch.setattr(dds_listener, "NET_RETRY_POLL_SEC", 0.02)


def _wait(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _net(monkeypatch, holder):
    monkeypatch.setattr(sysinfo, "network", lambda force=False: holder["value"])
    monkeypatch.setattr(sysinfo, "network_ready",
                        lambda force=False: holder["value"][1] != "-" and not holder["value"][0].startswith("127."))


def test_address_change_restarts_dds(monkeypatch):
    inits = []
    _fake_ros(monkeypatch, inits)
    net = {"value": ("192.168.0.20", "wlan0")}
    _net(monkeypatch, net)
    log = Log()
    listener = dds_listener.DdsListener(log)
    listener.start(21, "test1", on_trigger=lambda _m: None)
    try:
        assert _wait(lambda: listener.init["ip"] == "192.168.0.20")
        # 끊긴 동안(주소 없음)은 그대로 기다린다
        net["value"] = ("127.0.0.1", "-")
        time.sleep(0.15)
        assert len(inits) == 1
        # 다른 주소로 붙으면 다시 시작해 새 주소로 광고한다
        net["value"] = ("192.168.1.33", "wlan0")
        assert _wait(lambda: listener.init["ip"] == "192.168.1.33")
        assert len(inits) == 2
        assert any("네트워크가 바뀌었습니다" in line for line in log.lines)
        assert listener.status == dds_listener.CONNECTED
    finally:
        listener.stop()
    assert listener.status == dds_listener.OFF


def test_same_address_after_drop_keeps_running(monkeypatch):
    inits = []
    _fake_ros(monkeypatch, inits)
    net = {"value": ("192.168.0.20", "wlan0")}
    _net(monkeypatch, net)
    listener = dds_listener.DdsListener(Log())
    listener.start(21, "test1", on_trigger=lambda _m: None)
    try:
        assert _wait(lambda: listener.init["ok"] is True)
        net["value"] = ("127.0.0.1", "-")
        time.sleep(0.1)
        net["value"] = ("192.168.0.20", "wlan0")
        time.sleep(0.15)
        assert len(inits) == 1
    finally:
        listener.stop()


def test_no_network_at_start_retries_when_it_appears(monkeypatch):
    """예전에는 30초 기다린 뒤 포기 · 「재시작 필요」 로 끝났다"""
    inits = []
    _fake_ros(monkeypatch, inits)
    net = {"value": ("127.0.0.1", "-")}
    _net(monkeypatch, net)
    log = Log()
    listener = dds_listener.DdsListener(log)
    listener.start(21, "test1", on_trigger=lambda _m: None)
    try:
        assert _wait(lambda: listener.init["ok"] is False)
        assert inits == []
        assert "저절로 다시 시작" in listener.error
        net["value"] = ("192.168.0.20", "wlan0")
        assert _wait(lambda: listener.init["ok"] is True)
        assert inits == [21]
    finally:
        listener.stop()


def test_stop_ends_the_thread(monkeypatch):
    inits = []
    _fake_ros(monkeypatch, inits)
    _net(monkeypatch, {"value": ("127.0.0.1", "-")})
    listener = dds_listener.DdsListener(Log())
    listener.start(21, "test1", on_trigger=lambda _m: None)
    time.sleep(0.1)
    listener.stop()
    assert not any(t.name and t.is_alive() and t is listener._thread for t in threading.enumerate())
    assert listener.status == dds_listener.OFF
