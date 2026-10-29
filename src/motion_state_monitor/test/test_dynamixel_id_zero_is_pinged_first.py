"""다이나믹셀 ID 0 을 못 찾던 것 · 수정 목록 162 (chicken2 실물 2026-10-29)

    XM430-W350 · ID 0 · FW 48 · 1 Mbps
    개별 PING (손 스크립트 · 100 ms)   늘 답함
    Broadcast PING (0xFE)              한 번도 답 안 함 (손 스크립트로도 같음 · 서보·버스 쪽)
    robot_web 검색                     ID 1 · 2 만

검색은 Broadcast 를 0.5 s 기다린 **바로 뒤** 개별 Ping 을 0 번부터 쐈다 · 두 회차 모두
ID 0 은 「Broadcast 직후 첫 질문」 이었다 · Broadcast 답장 차례를 기다리는 서보가 그동안
들어온 질문을 흘린다고 보면 실물과 들어맞는다 (원인 실물 미확인).

이제 첫 회차의 개별 Ping 을 Broadcast **앞**에 한다 · 아래 가짜 버스는 그 가설대로
「Broadcast 바로 다음 질문은 ID 0 이 흘린다」 로 움직인다.
"""

import os
from types import SimpleNamespace

import pytest

termios = pytest.importorskip('termios')

from motion_state_monitor import dynamixel_scanner as dx  # noqa: E402

U2D2 = '/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT1-if00-port0'


class _Bus:
    """1 Mbps 에 ID 0 · 1 · 2 · ID 0 은 Broadcast 에 안 답하고, Broadcast 바로 다음 질문도 흘린다."""

    def __init__(self):
        self.baudrate = None
        self.log = []
        self.last = ''

    def open(self, _port, baudrate):
        self.baudrate = baudrate
        return os.open(os.devnull, os.O_RDWR)

    def broadcast(self, _fd, _timeout):
        self.log.append(('broadcast', self.baudrate))
        self.last = 'broadcast'
        if self.baudrate != 1000000:
            return []
        return [self._reply(bus_id, 'broadcast_ping') for bus_id in (1, 2)]

    def ping(self, _fd, bus_id, _timeout):
        self.log.append(('ping', bus_id))
        after_broadcast = self.last == 'broadcast'
        self.last = 'ping'
        if bus_id == 0 and after_broadcast:
            return None
        return self._reply(bus_id, 'id_ping') if bus_id in (0, 1, 2) else None

    @staticmethod
    def _reply(bus_id, source):
        return {'id': bus_id, 'packet_error': 0, 'model_number': 1020, 'firmware_version': 48, 'source': source}


def _scanner(monkeypatch, bus):
    monitor = SimpleNamespace(
        dynamixel_scan_attempts=2,
        dynamixel_scan_settle_sec=0.0,
        dynamixel_broadcast_timeout_sec=0.5,
        dynamixel_scan_id_fallback=True,
        dynamixel_scan_timeout_sec=0.02,
        _publish_scan_progress=lambda *_args, **_kwargs: None,
    )
    scanner = dx.DynamixelScanner(monitor)
    ids = list(range(0, dx.DYNAMIXEL_SCAN_MAX_ID + 1))
    scanner._dynamixel_scan_targets = lambda: [
        {'port': U2D2, 'resolved': U2D2, 'baudrate': baudrate, 'ids': ids}
        for baudrate in dx.DYNAMIXEL_SCAN_BAUDRATES
    ]
    monkeypatch.setattr(dx.DynamixelScanner, '_open_dynamixel_port', staticmethod(bus.open))
    scanner._broadcast_ping_dynamixel = bus.broadcast
    scanner._ping_dynamixel_id = bus.ping
    return scanner


def test_id_zero_is_found(monkeypatch):
    """**이것이 그 버그다** · 전에는 결과가 ID 1 · 2 뿐이었다."""
    bus = _Bus()
    result = _scanner(monkeypatch, bus)._scan_dynamixel_motors()

    assert sorted(device['id'] for device in result['devices']) == [0, 1, 2]
    zero = next(device for device in result['devices'] if device['id'] == 0)
    assert zero['source'] == 'id_ping'
    assert zero['baudrate'] == 1000000 and zero['port'] == U2D2


def test_the_first_individual_ping_does_not_follow_a_broadcast(monkeypatch):
    bus = _Bus()
    _scanner(monkeypatch, bus)._scan_dynamixel_motors()

    assert bus.log[0] == ('ping', 0), '첫 회차는 개별 Ping 이 먼저'
    first_broadcast = bus.log.index(('broadcast', 1000000))
    pinged_before = [entry[1] for entry in bus.log[:first_broadcast]]
    assert pinged_before == list(range(0, dx.DYNAMIXEL_SCAN_MAX_ID + 1)), '0~252 를 한 번씩'


def test_found_ids_are_not_pinged_again_nor_overwritten_by_the_broadcast(monkeypatch):
    bus = _Bus()
    result = _scanner(monkeypatch, bus)._scan_dynamixel_motors()

    first_broadcast = bus.log.index(('broadcast', 1000000))
    second_round = [entry[1] for entry in bus.log[first_broadcast + 1:] if entry[0] == 'ping']
    assert not {0, 1, 2} & set(second_round), '찾은 ID 는 둘째 회차에 다시 묻지 않는다'
    sources = {device['id']: device['source'] for device in result['devices']}
    assert sources == {0: 'id_ping', 1: 'id_ping', 2: 'id_ping'}


def test_extra_baudrates_stay_broadcast_only(monkeypatch):
    bus = _Bus()
    _scanner(monkeypatch, bus)._scan_dynamixel_motors()

    extra = [entry for entry in bus.log if entry[0] == 'broadcast' and entry[1] != 1000000]
    assert sorted({entry[1] for entry in extra}) == sorted(dx.DYNAMIXEL_SCAN_BAUDRATES[1:])
    pings_after_first_baud = bus.log[bus.log.index(extra[0]):]
    assert all(entry[0] == 'broadcast' for entry in pings_after_first_baud)
