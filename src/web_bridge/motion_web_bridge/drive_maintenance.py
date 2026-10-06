"""MINAS 드라이브 정비 · EEPROM 저장 · 앱솔루트 방식 · 다회전 클리어 · 수정 목록 15 + 34-3

모터 상태 조회·부팅 SDO 로는 할 수 없는 일 셋이다.

    EEPROM 저장          0x1010:01 = 0x65766173 ("save")
                         드라이브 RAM 값을 전원을 꺼도 남게 · 최대 10초
    앱솔루트 방식 바꾸기  Pr0.15(0x3015) 쓰기 → EEPROM 저장 → **드라이브 전원 재투입**
                         속성 C · 재투입 때 EEPROM 에서 다시 읽는다 · 그래서 부팅 RAM
                         쓰기로는 반영이 안 됐다(수정 목록 34-1)
    다회전 클리어         0x4D01 = 0x0031 → 0x4D00:01 bit9 0→1 · **서보 OFF 일 때만** ·
                         끝나면 드라이브 전원 재투입 + 기준점 다시 캡처

출처 · Panasonic SX-DSV03241 R10.0 (Pr0.15 p.176) · SX-DSV03242 R10.1 (1010h · 4D00h/4D01h p.259)

길 · Motor Manager 를 멈춰 EtherCAT 마스터를 풀고 → `ethercat download` → 다시 띄운다 ·
모터 검색과 같은 길이다(`scan_orchestrator`) · motion_system 은 고치지 않는다 ·
이 예외 길은 사용자 승인(2026-10-02) · 정비는 사람이 확인(`confirmed`)해야 한다.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, List, Optional

MINAS_VENDOR_ID = 0x066F

EEPROM_SAVE = 'eeprom_save'
ABSOLUTE_MODE = 'absolute_mode'
ABSOLUTE_CLEAR = 'absolute_clear'
ACTIONS = (EEPROM_SAVE, ABSOLUTE_MODE, ABSOLUTE_CLEAR)

#: Pr0.15 값 · 매뉴얼 p.176
ABSOLUTE_MODES = {0: '절대', 1: '인크리멘털', 2: '절대 · 다회전 넘침 무시', 3: '절대 · 한 바퀴만', 4: '절대 · 연속 회전'}

#: EEPROM 저장은 매뉴얼상 최대 10초
COMMAND_TIMEOUT_SEC = 15.0

LABELS = {
    EEPROM_SAVE: 'EEPROM 저장',
    ABSOLUTE_MODE: '앱솔루트 방식 바꾸기',
    ABSOLUTE_CLEAR: '앱솔루트 다회전 클리어',
}


def command_plan(action: str, master: int, position: int, value: Optional[int] = None) -> List[List[str]]:
    """보낼 `ethercat download` 명령들 · 순서대로 · 하나라도 실패하면 거기서 멈춘다."""
    base = ['ethercat', 'download', '-m', str(int(master)), '-p', str(int(position))]
    save = base + ['-t', 'uint32', '0x1010', '1', '0x65766173']
    if action == EEPROM_SAVE:
        return [save]
    if action == ABSOLUTE_MODE:
        if value not in ABSOLUTE_MODES:
            raise ValueError('앱솔루트 방식은 0~4 중 하나입니다')
        return [base + ['-t', 'int16', '0x3015', '0', str(int(value))], save]
    if action == ABSOLUTE_CLEAR:
        return [
            base + ['-t', 'uint16', '0x4D01', '0', '0x0031'],
            # 0 을 먼저 써서 bit9 를 0→1 로 올린다 · 이미 1 이면 일어나지 않는다
            base + ['-t', 'uint16', '0x4D00', '1', '0'],
            base + ['-t', 'uint16', '0x4D00', '1', '0x0200'],
        ]
    raise ValueError(f'지원하지 않는 드라이브 정비입니다: {action}')


def after_message(action: str, value: Optional[int] = None) -> str:
    if action == EEPROM_SAVE:
        return 'EEPROM 저장 완료 · 드라이브 전원을 꺼도 지금 값이 남습니다'
    if action == ABSOLUTE_MODE:
        return (
            f'앱솔루트 방식 {value} ({ABSOLUTE_MODES.get(value, "?")}) 저장 완료 · '
            '드라이브 전원을 껐다 켜야 적용됩니다 · 켠 뒤 모터 검색으로 값을 확인하세요'
        )
    return (
        '다회전 클리어 완료 · 드라이브 전원을 껐다 켠 뒤 기준점을 다시 캡처하세요 · '
        '그 전에는 위치가 맞지 않을 수 있어 재생하지 마세요'
    )


class DriveMaintenance:
    def __init__(
        self,
        *,
        runner: Callable[..., Any] = subprocess.run,
        read_slaves: Callable[[], List[Dict[str, Any]]],
        registry_motor: Callable[[int], Optional[Dict[str, Any]]],
        current_motor: Callable[[int], Optional[Dict[str, Any]]],
        safety_blocker: Callable[[], str],
        lifecycle_lock: Any,
        motor_service: Callable[[], str],
        service_active: Callable[[str], bool],
        run_service: Callable[[str, str], None],
        wait_release: Callable[[], None],
        wait_recovery: Callable[[str, List[int]], Dict[str, Any]],
        expected_axes: Callable[[], List[int]],
        record: Callable[[Dict[str, Any]], None],
    ) -> None:
        self._runner = runner
        self._read_slaves = read_slaves
        self._registry_motor = registry_motor
        self._current_motor = current_motor
        self._safety_blocker = safety_blocker
        self._lock = lifecycle_lock
        self._motor_service = motor_service
        self._service_active = service_active
        self._run_service = run_service
        self._wait_release = wait_release
        self._wait_recovery = wait_recovery
        self._expected_axes = expected_axes
        self._record = record

    # -- 대상 ------------------------------------------------------------ #

    def _target(self, axis: int) -> Dict[str, int]:
        entry = self._registry_motor(axis)
        if not entry:
            raise ValueError(f'{axis}번 모터가 모터 설정에 없습니다')
        identity = entry.get('identity') if isinstance(entry.get('identity'), dict) else {}
        config = entry.get('config') if isinstance(entry.get('config'), dict) else {}
        try:
            position = int(identity.get('slave_position'))
            master = int(identity.get('ethercat_master_index', config.get('ethercat_master_index', 0)) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{axis}번 모터의 EtherCAT 슬레이브 위치를 모릅니다 · 모터 검색 먼저') from exc
        # 지금 그 자리에 **MINAS 가** 있는지 다시 본다 · 랜선을 옮겨 꽂았으면 남의 드라이브다
        matches = [
            slave for slave in self._read_slaves()
            if int(slave.get('master_index', 0) or 0) == master
            and int(slave.get('slave_position', -1)) == position
        ]
        if len(matches) != 1:
            raise ValueError(f'{axis}번 모터 자리(마스터 {master} · 슬레이브 {position})에 드라이브가 보이지 않습니다')
        vendor = matches[0].get('vendor_id')
        try:
            vendor_id = int(str(vendor), 0) if isinstance(vendor, str) else int(vendor)
        except (TypeError, ValueError):
            vendor_id = -1
        if vendor_id != MINAS_VENDOR_ID:
            raise ValueError(f'{axis}번 모터 자리의 드라이브가 MINAS 가 아닙니다 (vendor {vendor})')
        return {'master': master, 'position': position}

    # -- 실행 ------------------------------------------------------------ #

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = str(payload.get('action') or '').strip()
        if action not in ACTIONS:
            return {'success': False, 'message': f'지원하지 않는 드라이브 정비입니다: {action}'}
        if payload.get('confirmed') is not True:
            return {'success': False, 'message': f'{LABELS[action]} · 확인이 필요합니다'}
        try:
            axis = int(payload.get('axis'))
        except (TypeError, ValueError):
            return {'success': False, 'message': '모터 번호가 필요합니다'}
        value = payload.get('value')
        try:
            value = None if value is None else int(value)
            target = self._target(axis)
            commands = command_plan(action, target['master'], target['position'], value)
        except ValueError as exc:
            return {'success': False, 'message': f'{LABELS[action]} 불가 · {exc}'}

        blocker = self._safety_blocker()
        if blocker:
            return {'success': False, 'message': f'{LABELS[action]} 불가 · {blocker}'}
        if action == ABSOLUTE_CLEAR:
            motor = self._current_motor(axis) or {}
            if motor.get('servo_on') is not False:
                return {
                    'success': False,
                    'message': f'{LABELS[action]} 불가 · {axis}번 모터 서보를 먼저 끄세요 (매뉴얼 · 서보 OFF 일 때만)',
                }
        if not self._lock.acquire(blocking=False):
            return {'success': False, 'message': f'{LABELS[action]} 불가 · 다른 모터 작업이 진행 중입니다'}
        try:
            return self._run_locked(action, axis, value, target, commands)
        finally:
            self._lock.release()

    def _run_locked(self, action, axis, value, target, commands) -> Dict[str, Any]:
        service = self._motor_service()
        was_active = bool(service) and self._service_active(service)
        # 멈추기 **전에** 지금 보이는 축을 적어 둔다 · 다시 띄운 뒤 그 축들을 기다린다
        axes = list(self._expected_axes()) if was_active else []
        outputs = []
        error = ''
        restore_error = ''
        recovery: Dict[str, Any] = {}
        try:
            if was_active:
                self._run_service('stop', service)
                self._wait_release()
            for command in commands:
                result = self._runner(
                    command, check=False, capture_output=True, text=True,
                    timeout=COMMAND_TIMEOUT_SEC,
                )
                outputs.append({'command': ' '.join(command), 'returncode': result.returncode})
                if result.returncode != 0:
                    error = (result.stderr or result.stdout or '').strip() or f'종료 코드 {result.returncode}'
                    break
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error = str(exc)
        finally:
            if was_active:
                try:
                    self._run_service('start', service)
                    recovery = self._wait_recovery(service, axes) or {}
                    if not recovery.get('service_active', True):
                        restore_error = 'Motor Manager 가 다시 실행되지 않았습니다'
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    restore_error = str(exc)
        success = not error and not restore_error
        message = (
            after_message(action, value) if not error
            else f'{LABELS[action]} 실패 · {error}'
        )
        if restore_error:
            message += f' / Motor Manager 복구 실패: {restore_error}'
        self._record({
            'event_type': f'minas_{action}',
            'axis': axis,
            'slave_position': target['position'],
            'master_index': target['master'],
            'value': value,
            'success': success,
            'message': message,
            'commands': outputs,
        })
        return {
            'success': success,
            'message': message,
            'action': action,
            'axis': axis,
            'power_cycle_required': action in (ABSOLUTE_MODE, ABSOLUTE_CLEAR) and not error,
            'commands': outputs,
            'motor_runtime_recovery': recovery,
        }
