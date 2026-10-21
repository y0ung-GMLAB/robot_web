"""Feetech (STS) 물리 검색 · SCS/STS 패킷 직접 Ping · 수정 목록 158 (`docs/SERIAL_SERVO_DESIGN.md` §5)

다이나믹셀 검색(`dynamixel_scanner.py`)과 같은 원칙 · 실제 직렬 포트를 열고 장치 응답만 담는다 ·
물리 응답이 없으면 이전 값을 쓰지 않고 실패로 남긴다 (`docs/MOTOR_SCAN_CONTRACT.md` I-4 · I-5).

    포트마다   /dev/serial/by-id → /dev/ttyUSB* → /dev/ttyACM* → 모터 설정 파일의 직렬 포트
    속도       1 Mbps 먼저 → 500000 → 115200 · 한 속도에서 찾으면 그 포트는 거기서 멈춘다
    ID         0~253 개별 Ping(0x01) · 응답한 ID 만 모델 번호 읽기(READ 0x02 · 주소 3 · 2 바이트 · little)
    금지       RESET(0x06 = 공장 초기화) · WRITE(0x03) · 검색은 PING · READ 만 보낸다

패킷 · `FF FF ID LEN INST PARAMS CHK` · LEN = 파라미터 수 + 2 · CHK = ~(ID + LEN + INST + Σ파라미터) & 0xFF
상태 패킷 · `FF FF ID LEN ERR PARAMS CHK`

실물 미검증 · 설계 §9 F-1 (U2D2 + STS3215 · 모델 번호 777)
"""

from __future__ import annotations

import os
import select
import termios
import time
from typing import Any, Dict, List, Optional

from motion_common import serial_servo_models

from .dynamixel_scanner import DynamixelScanner

#: 검색 규약 · 화면과 `scan_contract` 가 같은 값을 쓴다
FEETECH_SCAN_BAUDRATES = (1000000, 500000, 115200)
FEETECH_SCAN_MAX_ID = 253
FEETECH_SCAN_PROTOCOL = 'scs'
FEETECH_SCAN_RULE = (
    'auto serial port, baudrate 1000000 then 500000 then 115200 (stop at first answering baudrate), '
    'ping ID 0-253 each, read model number (addr 3, 2 bytes); no RESET, no WRITE'
)

INST_PING = 0x01
INST_READ = 0x02
#: 검색이 보낼 수 있는 명령 · 이 밖의 명령(특히 0x03 WRITE · 0x06 RESET)은 만들지 않는다
ALLOWED_SCAN_INSTRUCTIONS = (INST_PING, INST_READ)
MODEL_NUMBER_ADDRESS = 3
MODEL_NUMBER_LENGTH = 2
BROADCAST_ID = 0xFE
HEADER = b'\xFF\xFF'


def feetech_checksum(body: bytes) -> int:
    """`~(ID + LEN + INST/ERR + Σ파라미터) & 0xFF` · body = ID 부터 마지막 파라미터까지."""
    return (~sum(int(byte) for byte in body)) & 0xFF


def build_packet(device_id: int, instruction: int, params: bytes = b'') -> bytes:
    """명령 패킷 · 검색은 PING · READ 만 · 다른 명령은 ValueError."""
    if instruction not in ALLOWED_SCAN_INSTRUCTIONS:
        raise ValueError(f'Feetech 검색은 PING · READ 만 보낸다 (0x{int(instruction):02X} 거절)')
    if not 0 <= int(device_id) <= BROADCAST_ID:
        raise ValueError(f'Feetech ID 범위 밖 · {device_id}')
    params = bytes(params)
    body = bytes([int(device_id) & 0xFF, len(params) + 2, int(instruction) & 0xFF]) + params
    return HEADER + body + bytes([feetech_checksum(body)])


def ping_packet(device_id: int) -> bytes:
    return build_packet(device_id, INST_PING)


def read_packet(device_id: int, address: int, length: int) -> bytes:
    return build_packet(device_id, INST_READ, bytes([address & 0xFF, length & 0xFF]))


def extract_status_packets(data: bytearray) -> List[Dict[str, Any]]:
    """버퍼에서 상태 패킷을 꺼낸다 · 체크섬이 맞는 것만 · 쓴 만큼 버퍼에서 지운다.

    돌려주는 칸 · id · error · params(bytes)
    """
    packets: List[Dict[str, Any]] = []
    while True:
        index = bytes(data).find(HEADER)
        if index < 0:
            if len(data) > 1:
                del data[:-1]
            break
        if index > 0:
            del data[:index]
        # 헤더 FF FF 뒤에 FF 가 더 오면(앞 패킷 꼬리 · 잡음) 한 바이트씩 민다
        if len(data) >= 3 and data[2] == 0xFF:
            del data[:1]
            continue
        if len(data) < 4:
            break
        length = data[3]
        if length < 2:
            del data[:2]
            continue
        total = 4 + length
        if len(data) < total:
            break
        packet = bytes(data[:total])
        body = packet[2:-1]
        if feetech_checksum(body) != packet[-1]:
            del data[:2]
            continue
        del data[:total]
        packets.append({
            'id': packet[2],
            'error': packet[4],
            'params': packet[5:-1],
        })
    return packets


def parse_model_number(params: bytes) -> Optional[int]:
    """READ(주소 3 · 2 바이트) 답 · little-endian."""
    if len(params) != MODEL_NUMBER_LENGTH:
        return None
    return int(params[0]) | (int(params[1]) << 8)


class FeetechScanner:
    def __init__(self, monitor: Any) -> None:
        self.monitor = monitor

    # --- 설정 값 · 노드 파라미터가 없으면(시험 스텁) 기본값 ---------------------------------- #
    def _param(self, name: str, default: Any) -> Any:
        return getattr(self.monitor, name, default)

    def _timeout(self) -> float:
        # USB 직렬 지연(FTDI latency_timer 기본 16 ms) · 다이나믹셀 개별 Ping 과 같은 20 ms
        return max(0.001, float(self._param('feetech_scan_timeout_sec', 0.02)))

    def _max_id(self) -> int:
        return max(0, min(FEETECH_SCAN_MAX_ID, int(self._param('feetech_scan_max_id', FEETECH_SCAN_MAX_ID))))

    # --- 포트 ---------------------------------------------------------------------------------- #
    def _serial_ports(self) -> List[Dict[str, str]]:
        """다이나믹셀 검색과 같은 포트 목록 (by-id 우선 · 같은 장치는 한 번)."""
        helper = DynamixelScanner(self.monitor)
        config: Dict[str, Any] = {}
        path_text = str(self._param('motor_config_file', '') or '')
        if path_text:
            from pathlib import Path

            import yaml

            path = Path(path_text).expanduser()
            if path.is_file():
                try:
                    loaded = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
                    if isinstance(loaded, dict):
                        config = loaded
                except (OSError, yaml.YAMLError) as exc:
                    self.monitor.get_logger().warn(f'Failed to read Feetech scan YAML: {exc}')
        return helper._dynamixel_serial_ports(config)

    def _scan_targets(self) -> List[Dict[str, Any]]:
        max_id = self._max_id()
        return [
            {
                'port': port_info['port'],
                'port_source': port_info.get('source', ''),
                'resolved': port_info.get('resolved', port_info['port']),
                'baudrates': list(FEETECH_SCAN_BAUDRATES),
                'protocol': FEETECH_SCAN_PROTOCOL,
                'ids': list(range(0, max_id + 1)),
                'id_range': f'ID 0-{max_id} ping',
            }
            for port_info in self._serial_ports()
        ]

    # --- 한 장치 ------------------------------------------------------------------------------- #
    def _exchange(self, fd: int, packet: bytes, device_id: int, timeout_sec: float) -> Optional[Dict[str, Any]]:
        """명령 하나 보내고 그 ID 의 상태 패킷 하나 · 없으면 None."""
        termios.tcflush(fd, termios.TCIOFLUSH)
        if not DynamixelScanner._write_dynamixel_packet(fd, packet, timeout_sec=0.02):
            return None
        deadline = time.time() + max(timeout_sec, 0.001)
        data = bytearray()
        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                break
            try:
                chunk = os.read(fd, 256)
            except BlockingIOError:
                continue
            if not chunk:
                continue
            data.extend(chunk)
            for status in extract_status_packets(data):
                if int(status['id']) == (device_id & 0xFF):
                    return status
        return None

    def _ping_id(self, fd: int, device_id: int, timeout_sec: float) -> Optional[Dict[str, Any]]:
        status = self._exchange(fd, ping_packet(device_id), device_id, timeout_sec)
        if status is None or len(status.get('params') or b'') != 0:
            return None   # PING 답장은 파라미터 0 바이트
        return status

    def _read_model_number(self, fd: int, device_id: int, timeout_sec: float) -> Optional[int]:
        status = self._exchange(
            fd, read_packet(device_id, MODEL_NUMBER_ADDRESS, MODEL_NUMBER_LENGTH), device_id, timeout_sec,
        )
        if status is None:
            return None
        return parse_model_number(status.get('params') or b'')

    # --- 검색 ---------------------------------------------------------------------------------- #
    def _scan_feetech_motors(self) -> Dict[str, Any]:
        started_at = time.time()
        self.monitor._publish_scan_progress(
            'feetech_targets',
            'Feetech 직렬 포트와 검색 대상을 확인합니다',
            transport='feetech',
        )
        targets = self._scan_targets()
        if not targets:
            self.monitor._publish_scan_progress(
                'feetech_unavailable',
                'Feetech 직렬 포트를 찾지 못해 실제 Ping을 실행할 수 없습니다',
                transport='feetech',
            )
            return self._section(
                started_at, available=False, complete=False, targets=[], ports=[], devices=[],
                error=(
                    'Feetech 직렬 포트를 찾지 못했습니다. '
                    '/dev/serial/by-id, /dev/ttyUSB*, /dev/ttyACM* 경로를 확인했습니다.'
                ),
            )

        timeout_sec = self._timeout()
        devices: List[Dict[str, Any]] = []
        ports: List[Dict[str, Any]] = []
        errors: List[str] = []
        for target in targets:
            port = str(target.get('port') or '')
            port_row: Dict[str, Any] = {
                'port': port,
                'resolved': target.get('resolved', port),
                'port_source': target.get('port_source', ''),
                'baudrate': None,
                'baudrates_tried': [],
                'devices_count': 0,
                'error': '',
            }
            ports.append(port_row)
            for baudrate in target.get('baudrates') or []:
                port_row['baudrates_tried'].append(baudrate)
                self.monitor._publish_scan_progress(
                    'feetech_port',
                    f'{port} @ {baudrate}bps에서 ID 0~{self._max_id()} 직접 Ping을 시작합니다',
                    transport='feetech',
                    details={'port': port, 'baudrate': baudrate},
                )
                try:
                    fd = DynamixelScanner._open_dynamixel_port(port, baudrate)
                except (OSError, AttributeError, termios.error) as exc:
                    message = f'{port}@{baudrate}: {exc}'
                    port_row['error'] = message
                    errors.append(message)
                    break   # 포트를 못 열면 다른 속도도 못 연다
                found: List[Dict[str, Any]] = []
                try:
                    settle = float(self._param('feetech_scan_settle_sec', 0.05))
                    if settle > 0:
                        time.sleep(settle)
                    for device_id in target.get('ids') or []:
                        reply = self._ping_id(fd, int(device_id), timeout_sec)
                        if reply is None:
                            continue
                        model_number = self._read_model_number(fd, int(device_id), timeout_sec)
                        model_name = serial_servo_models.feetech_model_name(model_number) if model_number is not None else ''
                        device = {
                            'id': int(device_id),
                            'bus_id': int(device_id),
                            'port': port,
                            'serial_port': port,
                            'baudrate': baudrate,
                            'serial_baudrate': baudrate,
                            'model_number': model_number,
                            'model_name': model_name,
                            'model_confirm': model_number not in serial_servo_models.FEETECH_MODEL_NAMES,
                            'packet_error': int(reply.get('error') or 0),
                            'protocol': FEETECH_SCAN_PROTOCOL,
                            'source': 'id_ping',
                        }
                        found.append(device)
                        self.monitor._publish_scan_progress(
                            'feetech_device',
                            f'Feetech ID {device_id}: 실제 Ping 응답 확인',
                            transport='feetech',
                            details={'id': device_id, 'model_number': model_number, 'port': port},
                        )
                finally:
                    os.close(fd)
                if found:
                    port_row['baudrate'] = baudrate
                    port_row['devices_count'] = len(found)
                    devices.extend(found)
                    break   # 이 포트는 이 속도 · 다음 속도는 보지 않는다

        return self._section(
            started_at,
            available=bool(devices),
            complete=bool(devices) and not errors,
            targets=targets,
            ports=ports,
            devices=devices,
            error='; '.join(errors) if errors else ('' if devices else '직접 Ping에 응답한 Feetech가 없습니다'),
        )

    def _section(
        self,
        scanned_at: float,
        *,
        available: bool,
        complete: bool,
        targets: List[Dict[str, Any]],
        ports: List[Dict[str, Any]],
        devices: List[Dict[str, Any]],
        error: str,
        skipped: bool = False,
    ) -> Dict[str, Any]:
        section = {
            'available': available,
            'complete': complete,
            'direct': True,
            'scanned_at': scanned_at,
            'mode': 'direct_ping',
            'protocol': FEETECH_SCAN_PROTOCOL,
            'scan_rule': FEETECH_SCAN_RULE,
            'baudrates': list(FEETECH_SCAN_BAUDRATES),
            'id_min': 0,
            'id_max': self._max_id(),
            'error': error,
            'warning': '',
            'targets': targets,
            'ports': ports,
            'devices_count': len(devices),
            'devices': devices,
        }
        if skipped:
            section['skipped'] = True
        return section

    def _safe_scan_feetech_motors(self) -> Dict[str, Any]:
        try:
            return self._scan_feetech_motors()
        except Exception as exc:  # noqa: BLE001 · 검색 실패는 결과로 남긴다
            self.monitor.get_logger().error(f'Feetech scan failed: {exc}')
            return self._section(
                time.time(), available=False, complete=False, targets=[], ports=[], devices=[],
                error=str(exc),
            )

    def _skipped_feetech_scan(self, scanned_at: float) -> Dict[str, Any]:
        return self._section(
            scanned_at, available=False, complete=False, targets=[], ports=[], devices=[],
            error='', skipped=True,
        )


def ports_answering_both(dynamixel_scan: Dict[str, Any], feetech_scan: Dict[str, Any]) -> List[str]:
    """한 포트에서 다이나믹셀 · Feetech 둘 다 응답 · 한 포트 = 한 종류 위반 (설계 §5)."""
    def port_keys(section: Dict[str, Any]) -> Dict[str, str]:
        keys: Dict[str, str] = {}
        for device in (section or {}).get('devices') or []:
            if not isinstance(device, dict):
                continue
            port = str(device.get('port') or device.get('serial_port') or '')
            if not port:
                continue
            try:
                resolved = os.path.realpath(port)
            except OSError:
                resolved = port
            keys.setdefault(resolved, port)
        return keys

    dynamixel_ports = port_keys(dynamixel_scan)
    feetech_ports = port_keys(feetech_scan)
    return sorted(feetech_ports[key] for key in set(dynamixel_ports) & set(feetech_ports))
