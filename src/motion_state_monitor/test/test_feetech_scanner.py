"""Feetech (STS) 검색 · 패킷 · 체크섬 · 가짜 서보(pty) · 수정 목록 158

물리 검색 자체(U2D2 + STS3215)는 실물 미검증 (설계 §9 F-1) · 여기서는
패킷 모양 · 체크섬 · 상태 패킷 읽기 · 「PING · READ 만 보낸다」 · 포트·속도 순서를 본다.
"""

import os
import threading
import time
from types import SimpleNamespace

import pytest

from motion_state_monitor import feetech_scanner as ft
from motion_state_monitor.feetech_scanner import FeetechScanner


def test_checksum_and_ping_packet_bytes():
    # FF FF ID LEN INST CHK · LEN = 파라미터 + 2 · CHK = ~(ID+LEN+INST) & 0xFF
    assert ft.ping_packet(1) == bytes([0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB])
    assert ft.feetech_checksum(bytes([0x01, 0x02, 0x01])) == 0xFB
    # READ 주소 3 · 2 바이트 · ID 1 → ~(1+4+2+3+2) = ~12 = 0xF3
    assert ft.read_packet(1, 3, 2) == bytes([0xFF, 0xFF, 0x01, 0x04, 0x02, 0x03, 0x02, 0xF3])


def test_scan_never_builds_write_or_reset():
    for instruction in (0x03, 0x04, 0x05, 0x06, 0x83):
        with pytest.raises(ValueError):
            ft.build_packet(1, instruction)
    with pytest.raises(ValueError):
        ft.build_packet(0xFF, ft.INST_PING)


def _status(device_id, error=0, params=b''):
    body = bytes([device_id, len(params) + 2, error]) + bytes(params)
    return b'\xFF\xFF' + body + bytes([ft.feetech_checksum(body)])


def test_status_packets_are_parsed_and_bad_checksums_dropped():
    data = bytearray(b'\x00\x13' + _status(1) + _status(7, params=b'\x09\x03'))
    bad = bytearray(_status(2))
    bad[-1] ^= 0xFF
    data += bad + _status(3, error=0x20)
    packets = ft.extract_status_packets(data)
    assert [(p['id'], p['error'], bytes(p['params'])) for p in packets] == [
        (1, 0, b''), (7, 0, b'\x09\x03'), (3, 0x20, b''),
    ]
    assert ft.parse_model_number(b'\x09\x03') == 777
    assert ft.parse_model_number(b'\x09') is None


def test_status_packet_split_across_reads():
    whole = _status(5, params=b'\x09\x0B')
    data = bytearray(whole[:4])
    assert ft.extract_status_packets(data) == []
    data += whole[4:]
    assert ft.extract_status_packets(data)[0]['params'] == b'\x09\x0B'


def test_ports_answering_both_protocols_are_reported():
    dxl = {'devices': [{'id': 1, 'port': '/dev/ttyUSB0'}]}
    fts = {'devices': [{'id': 3, 'port': '/dev/ttyUSB0'}, {'id': 4, 'port': '/dev/ttyUSB1'}]}
    assert ft.ports_answering_both(dxl, fts) == ['/dev/ttyUSB0']
    assert ft.ports_answering_both({'devices': []}, fts) == []


def _monitor():
    events = []
    monitor = SimpleNamespace(
        motor_config_file='',
        feetech_scan_max_id=6,
        feetech_scan_timeout_sec=0.05,
        feetech_scan_settle_sec=0.0,
        _publish_scan_progress=lambda phase, message, **kw: events.append(phase),
        get_logger=lambda: SimpleNamespace(warn=lambda *_: None, error=lambda *_: None),
    )
    return monitor, events


def test_skipped_and_no_port_sections_are_failures_not_old_values():
    monitor, _ = _monitor()
    scanner = FeetechScanner(monitor)
    scanner._serial_ports = lambda: []
    result = scanner._scan_feetech_motors()
    assert result['available'] is False and result['devices'] == [] and result['error']
    assert result['scan_rule'] == ft.FEETECH_SCAN_RULE
    skipped = scanner._skipped_feetech_scan(1.0)
    assert skipped['skipped'] is True and skipped['devices_count'] == 0


@pytest.mark.skipif(not hasattr(os, 'openpty'), reason='pty 없음')
def test_fake_servos_on_a_pty_are_found_with_model_numbers_and_only_ping_read_is_sent():
    master, slave = os.openpty()
    port = os.ttyname(slave)
    servos = {1: 777, 4: 1234}
    seen_instructions = []
    stop = threading.Event()

    def responder():
        buffer = bytearray()
        while not stop.is_set():
            try:
                chunk = os.read(master, 256)
            except OSError:
                return
            buffer.extend(chunk)
            # 명령 패킷 모양은 상태 패킷과 같다 (FF FF ID LEN X … CHK)
            for packet in ft.extract_status_packets(buffer):
                instruction = packet['error']
                seen_instructions.append(instruction)
                model = servos.get(packet['id'])
                if model is None:
                    continue
                if instruction == ft.INST_PING:
                    os.write(master, _status(packet['id']))
                elif instruction == ft.INST_READ and bytes(packet['params']) == b'\x03\x02':
                    os.write(master, _status(packet['id'], params=bytes([model & 0xFF, model >> 8])))

    thread = threading.Thread(target=responder, daemon=True)
    thread.start()
    try:
        monitor, events = _monitor()
        scanner = FeetechScanner(monitor)
        scanner._serial_ports = lambda: [{'port': port, 'source': 'test', 'resolved': port}]
        started = time.time()
        result = scanner._scan_feetech_motors()
    finally:
        stop.set()
        os.close(slave)
        os.close(master)
    assert time.time() - started < 10
    assert result['available'] is True and result['complete'] is True
    devices = {d['id']: d for d in result['devices']}
    assert set(devices) == {1, 4}
    assert devices[1]['model_name'] == 'STS3215' and devices[1]['model_confirm'] is False
    assert devices[4]['model_name'] == 'Feetech (버전 1234)' and devices[4]['model_confirm'] is True
    assert devices[1]['baudrate'] == 1000000 and devices[1]['source'] == 'id_ping'
    assert devices[1]['serial_port'] == port and devices[1]['bus_id'] == 1
    # 첫 속도에서 찾았으니 다른 속도는 안 본다
    assert result['ports'][0]['baudrates_tried'] == [1000000]
    assert result['ports'][0]['baudrate'] == 1000000
    assert set(seen_instructions) <= {ft.INST_PING, ft.INST_READ}
    assert 'feetech_device' in events
