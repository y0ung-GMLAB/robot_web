"""MINAS 드라이브 정비 · EEPROM 저장 · 앱솔루트 방식 · 다회전 클리어 · 수정 목록 15 + 34-3

모터 상태 조회·부팅 SDO 로는 할 수 없는 일 셋이다.

    EEPROM 저장          0x1010:01 = 0x65766173 ("save")
                         드라이브 RAM 값을 전원을 꺼도 남게 · 최대 10초
    앱솔루트 방식 바꾸기  Pr0.15(0x3015) 쓰기 → EEPROM 저장 → **드라이브 전원 재투입**
                         속성 C · 재투입 때 EEPROM 에서 다시 읽는다 · 그래서 부팅 RAM
                         쓰기로는 반영이 안 됐다(수정 목록 34-1)
    다회전 클리어         0x4D01 = 0x0031 → 0x4D00:01 bit9 0→1 · **서보 OFF 일 때만** ·
                         0x4D00:01 되읽어 bit9 확인(수정 목록 66) ·
                         끝나면 드라이브 전원 재투입 + 기준점 다시 캡처

출처 · Panasonic SX-DSV03241 R10.0 (Pr0.15 p.176) · SX-DSV03242 R10.1 (1010h · 4D00h/4D01h p.259)

게인 쓰기 · 수정 목록 108 (다) (2026-10-13)
    자동조정(Pr0.02) · 강성(Pr0.03) · 추정 속도(Pr6.31) · Motor Manager 를 **멈추지 않고** `ethercat download` ·
    강성은 여러 번 바꿔 보며 맞추는 값이라 매번 재시작(토크 풀림)하면 안 된다 · 2026-10-12 floating4 에서
    Motor Manager 가 돌 때 0x3002 · 0x3003 쓰기 · 되읽기 같음(108 경과) · 쓰기는 드라이브 RAM 에만 ·
    전원을 꺼도 남기려면 EEPROM 저장(이건 기존처럼 Motor Manager 를 멈추는 길 · 모든 축이면 한 번만).
    모터가 움직이는 동안(재생 · 초기 이동 · 수동 조작)은 거절 · 쓰고 나면 되읽어 같은지 본다.

길 · Motor Manager 를 멈춰 EtherCAT 마스터를 풀고 → `ethercat download` → 다시 띄운다 ·
모터 검색과 같은 길이다(`scan_orchestrator`) · motion_system 은 고치지 않는다 ·
이 예외 길은 사용자 승인(2026-10-02) · 정비는 사람이 확인(`confirmed`)해야 한다.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, List, Optional

from motion_common import ethercat_mailbox

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
    ABSOLUTE_MODE: '앱솔루트 방식 변경',
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
            # 0x4D00:01 은 uint32(객체 사전) · uint16 이면 SDO 0x06070010 거부 · 수정 목록 66
            base + ['-t', 'uint32', '0x4D00', '1', '0'],
            base + ['-t', 'uint32', '0x4D00', '1', '0x0200'],
        ]
    raise ValueError(f'지원하지 않는 드라이브 정비입니다: {action}')


#: 다회전 클리어 시작 비트 · 0x4D00:01 bit9
ABSOLUTE_CLEAR_BIT = 0x0200

#: 화면에서 쓰는 게인 · 이름 → (객체, 최소, 최대) · int16 · A6 기술 자료 SX-DSV03031 p.107-108
#: Pr0.02 5(부하 특성 측정) · 6(사용자 정의) 은 뺀다 · 위치·속도 게인(Pr1.xx)은 자동조정이 정하므로 안 연다
GAIN_FIELDS: Dict[str, tuple] = {
    'auto_tuning': (0x3002, 0, 4),
    'stiffness': (0x3003, 0, 31),
    'estimation_speed': (0x3631, 0, 3),
}
GAIN_LABELS = {'auto_tuning': '자동조정(Pr0.02)', 'stiffness': '강성(Pr0.03)', 'estimation_speed': '추정 속도(Pr6.31)'}


def gain_commands(master: int, position: int, values: Dict[str, Any]) -> List[tuple]:
    """(이름, 값, 쓰기 명령, 되읽기 명령) 목록 · 범위 밖 · 모르는 이름은 ValueError"""
    if not values:
        raise ValueError('바꿀 게인이 없습니다')
    base = ['-m', str(int(master)), '-p', str(int(position)), '-t', 'int16']
    plan = []
    for name, raw in values.items():
        if name not in GAIN_FIELDS:
            raise ValueError(f'화면에서 바꿀 수 없는 게인입니다: {name}')
        index, low, high = GAIN_FIELDS[name]
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{GAIN_LABELS[name]} 값이 숫자가 아닙니다') from exc
        if not low <= value <= high:
            raise ValueError(f'{GAIN_LABELS[name]} 는 {low}~{high} 사이여야 합니다')
        obj = f'0x{index:04X}'
        plan.append((name, value, ['ethercat', 'download', *base, obj, '0', str(value)],
                     ['ethercat', 'upload', *base, obj, '0']))
    return plan


def parse_upload_last(text: str) -> Optional[int]:
    """`ethercat upload -t int16` 출력(`0x000d 13`) 마지막 칸 = 10진 값 · 못 읽으면 None"""
    tokens = str(text or '').split()
    if not tokens:
        return None
    try:
        return int(tokens[-1], 0)
    except ValueError:
        return None


def verify_command(action: str, master: int, position: int) -> Optional[List[str]]:
    """쓰기 뒤 되읽기 · 다회전 클리어만 · 0x4D00:01 bit9 가 1 인지 본다 · 수정 목록 66"""
    if action != ABSOLUTE_CLEAR:
        return None
    return [
        'ethercat', 'upload', '-m', str(int(master)), '-p', str(int(position)),
        '-t', 'uint32', '0x4D00', '1',
    ]


def parse_upload_value(text: str) -> Optional[int]:
    """`ethercat upload` 출력 첫 칸(`0x00000200 512`) · 못 읽으면 None"""
    tokens = str(text or '').split()
    if not tokens:
        return None
    try:
        return int(tokens[0], 0)
    except ValueError:
        return None


def after_message(action: str, value: Optional[int] = None) -> str:
    if action == EEPROM_SAVE:
        return 'EEPROM에 저장했습니다. 드라이브 전원을 꺼도 현재 값이 유지됩니다'
    if action == ABSOLUTE_MODE:
        return (
            f'앱솔루트 방식 {value} ({ABSOLUTE_MODES.get(value, "?")})을 저장했습니다. '
            '드라이브 전원을 껐다 켜야 적용됩니다. 전원을 켠 뒤 모터 검색으로 값을 확인하세요'
        )
    return (
        '다회전 클리어를 마쳤습니다. 드라이브 전원을 껐다 켜세요. 위치 값이 바뀌므로 모든 프로젝트의 이 축 기준점이 무효입니다. '
        '몸을 정면·수평에 맞추고 기준점을 다시 지정해 저장하기 전까지 재생·초기 위치 이동·스케줄·그룹 참가가 막힙니다'
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
        record_clear: Optional[Callable[[List[Dict[str, Any]]], Any]] = None,
    ) -> None:
        # SDO 는 다른 프로세스와 한 번에 하나 · 버스 설정 중이면 안 보냄 · 수정 목록 125
        self._runner = ethercat_mailbox.guarded(runner)
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
        #: 다회전 클리어만 하는 길(드라이브 정비)도 앱솔루트 설정과 같은 PC 단위 표시를 남긴다 · 수정 목록 140 ④
        self._record_clear = record_clear or (lambda _drives: None)

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
            raise ValueError(f'{axis}번 모터의 EtherCAT 슬레이브 위치를 알 수 없습니다. 먼저 모터 검색을 실행하세요') from exc
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
            raise ValueError(f'{axis}번 모터 자리의 드라이브가 MINAS가 아닙니다(vendor {vendor})')
        return {'master': master, 'position': position, 'serial': matches[0].get('serial_number')}

    # -- 실행 ------------------------------------------------------------ #

    def write_gains(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """게인 쓰기 · Motor Manager 를 멈추지 않는다 · 축 하나 또는 여러 축(axes) · 108 (다)"""
        if payload.get('confirmed') is not True:
            return {'success': False, 'message': '게인 쓰기 · 확인이 필요합니다'}
        values = payload.get('values') if isinstance(payload.get('values'), dict) else {}
        raw_axes = payload.get('axes') if isinstance(payload.get('axes'), list) else [payload.get('axis')]
        try:
            axes = [int(axis) for axis in raw_axes]
        except (TypeError, ValueError):
            return {'success': False, 'message': '모터 번호가 필요합니다'}
        if not axes:
            return {'success': False, 'message': '모터 번호가 필요합니다'}
        try:
            plans = {axis: (self._target(axis), None) for axis in axes}
            plans = {axis: (target, gain_commands(target['master'], target['position'], values))
                     for axis, (target, _) in plans.items()}
        except ValueError as exc:
            return {'success': False, 'message': f'게인 쓰기 불가 · {exc}'}
        blocker = self._safety_blocker()
        if blocker:
            return {'success': False, 'message': f'게인 쓰기 불가 · {blocker}'}
        if not self._lock.acquire(blocking=False):
            return {'success': False, 'message': '게인 쓰기 불가 · 다른 모터 작업이 진행 중입니다'}
        results = []
        try:
            for axis, (target, plan) in plans.items():
                read_back: Dict[str, Optional[int]] = {}
                errors = []
                for name, value, write, read in plan:
                    try:
                        done = self._runner(write, check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SEC)
                        if done.returncode != 0:
                            errors.append(f'{GAIN_LABELS[name]} 쓰기 실패 · '
                                          + ((done.stderr or done.stdout or '').strip() or f'종료 코드 {done.returncode}'))
                            continue
                        got = self._runner(read, check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SEC)
                        read_back[name] = parse_upload_last(got.stdout) if got.returncode == 0 else None
                        if read_back[name] != value:
                            errors.append(f'{GAIN_LABELS[name]} 되읽기 {read_back[name]} ≠ {value}')
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        errors.append(f'{GAIN_LABELS[name]} · {exc}')
                ok = not errors
                record = {
                    'event_type': 'minas_gain_write', 'axis': axis,
                    'slave_position': target['position'], 'master_index': target['master'],
                    'values': dict(values), 'read_back': read_back, 'success': ok,
                    'message': '게인을 썼습니다(드라이브 RAM)' if ok else ' / '.join(errors),
                }
                self._record(record)
                results.append(record)
        finally:
            self._lock.release()
        failed = [r for r in results if not r['success']]
        axes_text = ' · '.join(f"{r['axis']}번" for r in results)
        return {
            'success': not failed,
            'message': (
                f'{axes_text} 게인을 썼습니다. 지금부터 적용됩니다(전원을 끄면 사라짐 · 남기려면 EEPROM 저장).'
                if not failed else
                ' / '.join(f"{r['axis']}번 {r['message']}" for r in failed)
            ),
            'results': results,
        }

    def save_eeprom_all(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """모든 MINAS 축 EEPROM 저장 · Motor Manager 를 **한 번만** 멈췄다 띄운다 · 108 (다)"""
        if payload.get('confirmed') is not True:
            return {'success': False, 'message': 'EEPROM 저장 · 확인이 필요합니다'}
        axes = [int(axis) for axis in (payload.get('axes') or [])]
        if not axes:
            return {'success': False, 'message': '저장할 모터가 없습니다'}
        try:
            targets = {axis: self._target(axis) for axis in axes}
        except ValueError as exc:
            return {'success': False, 'message': f'EEPROM 저장 불가 · {exc}'}
        blocker = self._safety_blocker()
        if blocker:
            return {'success': False, 'message': f'EEPROM 저장 불가 · {blocker}'}
        if not self._lock.acquire(blocking=False):
            return {'success': False, 'message': 'EEPROM 저장 불가 · 다른 모터 작업이 진행 중입니다'}
        try:
            commands = []
            for axis, target in targets.items():
                commands.extend(command_plan(EEPROM_SAVE, target['master'], target['position']))
            first = axes[0]
            result = self._run_locked(EEPROM_SAVE, first, None, targets[first], commands)
        finally:
            self._lock.release()
        result['axes'] = axes
        if result.get('success'):
            result['message'] = f"{' · '.join(f'{a}번' for a in axes)} EEPROM에 저장했습니다. 드라이브 전원을 꺼도 지금 값이 유지됩니다"
        return result

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
                    'message': f'{LABELS[action]} 불가 · {axis}번 모터의 서보를 먼저 끄세요(서보가 꺼져 있을 때만 할 수 있습니다)',
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
            if action == ABSOLUTE_CLEAR:
                # 명령 전에 남긴다 · 중간에 끊겨도 막는 쪽 · 그 축 기준점을 다시 지정해 저장할 때까지 재생 막힘 · 140 ④
                self._record_clear([{
                    'axis': axis, 'serial': target.get('serial'), 'master_index': target['master'],
                    'slave_position': target['position'], 'source': 'drive_maintenance',
                }])
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
            verify = verify_command(action, target['master'], target['position'])
            if verify and not error:
                result = self._runner(
                    verify, check=False, capture_output=True, text=True,
                    timeout=COMMAND_TIMEOUT_SEC,
                )
                read_value = parse_upload_value(result.stdout) if result.returncode == 0 else None
                outputs.append({
                    'command': ' '.join(verify),
                    'returncode': result.returncode,
                    'value': read_value,
                })
                if read_value is None:
                    error = '되읽기 실패 · 0x4D00:01 · ' + (
                        (result.stderr or result.stdout or '').strip() or f'종료 코드 {result.returncode}'
                    )
                elif not read_value & ABSOLUTE_CLEAR_BIT:
                    error = f'되읽기 불일치 · 0x4D00:01 = 0x{read_value:08X} · bit9가 1이 아닙니다'
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error = str(exc)
        finally:
            if was_active:
                try:
                    self._run_service('start', service)
                    recovery = self._wait_recovery(service, axes) or {}
                    if not recovery.get('service_active', True):
                        restore_error = 'Motor Manager가 다시 실행되지 않았습니다'
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    restore_error = str(exc)
        success = not error and not restore_error
        message = (
            after_message(action, value) if not error
            else f'{LABELS[action]} 실패 · {error}'
        )
        if restore_error:
            message += f' / Motor Manager 복구 실패: {restore_error}'
        elif recovery.get('servo_waiting_axes'):
            waiting = ' · '.join(f'{axis}번' for axis in recovery['servo_waiting_axes'])
            message += f' / {waiting} 서보가 아직 켜지는 중입니다 · 잠시 뒤 모터 표에서 확인하세요'
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
