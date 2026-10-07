"""MINAS 「앱솔루트 설정」 · 버튼 하나로 앱솔루트 + 다회전 클리어 · 수정 목록 62 ③④

대상은 EtherCAT 에 연결된 MINAS 드라이브 중 앱솔루트로 확인되지 않은 것 · 상태 모니터가
싣는 `minas_absolute.drives` 의 `status ≠ ok` (Pr0.15 ≠ 0 · 확인 불가 · Err40) · 등록 안 한
드라이브도 · 정상 드라이브는 건너뛴다(다시 클리어하면 기준점이 사라진다).

    1 서보 OFF        등록된 대상 축 · 끄고 꺼졌는지 확인
    2 앱솔루트 쓰기    Motor Manager 멈춤 → 0x3015 = 0 → 되읽기 0 → EEPROM 저장 → 다시 띄움
    3 전원 재투입 1    사람이 드라이브 전원을 껐다 켬 · 대상 슬레이브가 빠졌다 돌아오면 다음
    4 방식 확인        0x3015 되읽기 = 0 (재투입 뒤 EEPROM 값)
    5 다회전 클리어    서보 OFF → 멈춤 → 0x4D01 = 0x0031 → 0x4D00:01 0 → 0x200 → 되읽기 bit9 → 다시 띄움
    6 전원 재투입 2    3 과 같음
    7 검증            0x3015 = 0 · 0x603F = 0 · |0x6064| < 1 바퀴(8,388,608 count) · 몇 초 다시 봄

어느 단계든 실패하면 거기서 멈추고 원인을 남긴다 · Motor Manager 는 반드시 다시 띄운다 ·
전체 버튼은 대상 드라이브를 함께 처리한다(같은 전원이면 재투입 두 번으로 끝).
차단 해제는 상태 모니터가 재투입 뒤 다시 읽어 판정한다(이 모듈은 해제하지 않는다) ·
기준점 다시 캡처는 안내만 한다.

전원 재투입 자동화 · 부팅·적용 때 자동 쓰기 · `src/motion_system` 수정은 하지 않는다 ·
`ethercat` CLI 예외 경로는 드라이브 정비(15)와 같은 승인(2026-10-02).
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from motion_common import minas_absolute

from .drive_maintenance import (
    ABSOLUTE_CLEAR,
    ABSOLUTE_CLEAR_BIT,
    COMMAND_TIMEOUT_SEC,
    command_plan,
    parse_upload_value,
    verify_command,
)

#: 한 바퀴 count · MINAS 23 bit 엔코더 (수정 목록 62 ④)
ONE_TURN_COUNTS = 8_388_608

#: 전원 재투입을 기다리는 최대 시간
POWER_CYCLE_TIMEOUT_SEC = 30 * 60
#: 슬레이브 목록을 보는 간격
POLL_SEC = 1.0
#: 돌아온 뒤 마스터가 다시 설정할 때까지 · 그 전 SDO 는 실패하기 쉽다
SETTLE_AFTER_RETURN_SEC = 5.0
#: 마지막 검증에서 오류 코드가 사라지길 기다리는 시간(재투입 직후 통신 알람 Err88 이 잠깐 뜬다)
VERIFY_RETRY_SEC = 20.0
#: 서보 OFF 가 상태에 보일 때까지
SERVO_OFF_TIMEOUT_SEC = 5.0

STEPS = (
    ('servo_off', '서보 OFF'),
    ('write_mode', '앱솔루트 쓰기 · EEPROM 저장'),
    ('power_cycle_1', '드라이브 전원 재투입 1'),
    ('check_mode', '앱솔루트 방식 확인'),
    ('clear', '다회전 클리어'),
    ('power_cycle_2', '드라이브 전원 재투입 2'),
    ('verify', '검증'),
)
STEP_LABELS = dict(STEPS)


def drive_key(drive: Dict[str, Any]) -> Tuple[int, int]:
    return int(drive.get('master_index') or 0), int(drive.get('slave_position'))


def plan_targets(
    minas: Any, *, scope: str, master: Optional[int] = None, position: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """(처리 대상 · 정상이라 건너뜀 · 거절 사유) · 판정은 상태 모니터가 읽은 값 그대로"""
    if not isinstance(minas, dict):
        return [], [], minas_absolute.MISSING_MESSAGE
    if str(minas.get('state') or '') == minas_absolute.STATE_CHECKING:
        return [], [], minas_absolute.CHECKING_MESSAGE
    drives = [dict(drive) for drive in minas.get('drives') or [] if isinstance(drive, dict)]
    if not drives:
        return [], [], '연결된 MINAS 드라이브가 없습니다'
    if scope == 'one':
        chosen = [drive for drive in drives if drive_key(drive) == (int(master or 0), int(position))]
        if not chosen:
            return [], [], f'마스터 {master} 슬레이브 {position} 에 MINAS 드라이브가 보이지 않습니다'
        drives = chosen
    targets = [drive for drive in drives if drive.get('status') != minas_absolute.DRIVE_OK]
    skipped = [drive for drive in drives if drive.get('status') == minas_absolute.DRIVE_OK]
    if not targets:
        return [], skipped, '정상 · 이미 앱솔루트입니다(다시 클리어하면 기준점이 사라져 하지 않습니다)'
    return targets, skipped, ''


class AbsoluteSetup:
    def __init__(
        self,
        *,
        runner: Callable[..., Any] = subprocess.run,
        minas_absolute_state: Callable[[], Any],
        visible_slaves: Callable[[], Optional[List[Dict[str, Any]]]],
        current_motor: Callable[[int], Optional[Dict[str, Any]]],
        servo_off: Callable[[int], Dict[str, Any]],
        safety_blocker: Callable[[], str],
        lifecycle_lock: Any,
        motor_service: Callable[[], str],
        service_active: Callable[[str], bool],
        run_service: Callable[[str, str], None],
        wait_release: Callable[[], None],
        wait_recovery: Callable[[str, List[int]], Dict[str, Any]],
        expected_axes: Callable[[], List[int]],
        record: Callable[[Dict[str, Any]], None],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        spawn: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self._runner = runner
        self._minas = minas_absolute_state
        self._visible_slaves = visible_slaves
        self._current_motor = current_motor
        self._servo_off = servo_off
        self._safety_blocker = safety_blocker
        self._lifecycle_lock = lifecycle_lock
        self._motor_service = motor_service
        self._service_active = service_active
        self._run_service = run_service
        self._wait_release = wait_release
        self._wait_recovery = wait_recovery
        self._expected_axes = expected_axes
        self._record = record
        self._clock = clock
        self._sleep = sleep
        self._spawn = spawn or (lambda target: threading.Thread(
            target=target, name='minas-absolute-setup', daemon=True,
        ).start())
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._job: Dict[str, Any] = {'state': 'idle'}

    # -- 바깥에서 부른다 ---------------------------------------------------- #

    def active(self) -> bool:
        with self._lock:
            return self._job.get('state') == 'running'

    def blocker(self) -> str:
        return '앱솔루트 설정 진행 중 · 끝날 때까지 모터 동작을 막습니다' if self.active() else ''

    def status(self) -> Dict[str, Any]:
        with self._lock:
            job = dict(self._job)
            job['targets'] = [dict(item) for item in job.get('targets') or []]
            job['skipped'] = [dict(item) for item in job.get('skipped') or []]
        return job

    def preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """확인 창에 띄울 처리 대상 · 건너뜀 목록"""
        scope, master, position, error = self._scope(payload)
        if error:
            return {'success': False, 'message': error}
        targets, skipped, reason = plan_targets(
            self._minas(), scope=scope, master=master, position=position,
        )
        return {
            'success': not reason,
            'message': reason or f'처리 {len(targets)}대 · 건너뜀 {len(skipped)}대',
            'targets': [self._view(drive) for drive in targets],
            'skipped': [self._view(drive) for drive in skipped],
            'steps': [label for _key, label in STEPS],
        }

    def start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get('confirmed') is not True:
            return {'success': False, 'message': '앱솔루트 설정 · 확인이 필요합니다'}
        scope, master, position, error = self._scope(payload)
        if error:
            return {'success': False, 'message': error}
        blocker = self._safety_blocker()
        if blocker:
            return {'success': False, 'message': f'앱솔루트 설정 불가 · {blocker}'}
        targets, skipped, reason = plan_targets(
            self._minas(), scope=scope, master=master, position=position,
        )
        if reason:
            return {'success': False, 'message': f'앱솔루트 설정 불가 · {reason}'}
        with self._lock:
            if self._job.get('state') == 'running':
                return {'success': False, 'message': '앱솔루트 설정이 이미 진행 중입니다'}
            self._cancel.clear()
            self._job = {
                'state': 'running',
                'scope': scope,
                'step': STEPS[0][0],
                'step_label': STEPS[0][1],
                'step_index': 1,
                'step_count': len(STEPS),
                'message': '시작',
                'started_at': time.time(),
                'targets': [self._view(drive) for drive in targets],
                'skipped': [self._view(drive) for drive in skipped],
                'error': '',
            }
        self._spawn(self._run)
        return {'success': True, 'message': f'앱솔루트 설정 시작 · 처리 {len(targets)}대', 'job': self.status()}

    def cancel(self) -> Dict[str, Any]:
        """전원 재투입을 기다리는 동안만 의미가 있다 · 쓰는 중에는 그 단계가 끝나야 선다"""
        if not self.active():
            return {'success': False, 'message': '진행 중인 앱솔루트 설정이 없습니다'}
        self._cancel.set()
        return {'success': True, 'message': '앱솔루트 설정 취소 요청 · 지금 단계가 끝나면 멈춥니다'}

    # -- 단계 ------------------------------------------------------------- #

    def _run(self) -> None:
        targets = self.status()['targets']
        try:
            self._step('servo_off', '대상 축 서보를 끕니다')
            self._servo_off_targets(targets)
            self._step('write_mode', 'Motor Manager 를 멈추고 Pr0.15 = 0 · EEPROM 저장')
            self._with_motor_manager_stopped(lambda: self._write_mode(targets))
            self._step('power_cycle_1', '드라이브 전원을 껐다 켜세요 · 대상 드라이브가 빠졌다 돌아오면 다음 단계로 갑니다')
            self._wait_power_cycle(targets)
            self._step('check_mode', '재투입 뒤 Pr0.15 되읽기')
            self._check_mode(targets)
            self._step('clear', '서보 OFF → Motor Manager 멈춤 → 다회전 클리어')
            self._servo_off_targets(targets)
            self._with_motor_manager_stopped(lambda: self._clear(targets))
            self._step('power_cycle_2', '드라이브 전원을 한 번 더 껐다 켜세요 · 다회전 클리어 적용')
            self._wait_power_cycle(targets)
            self._step('verify', 'Pr0.15 · 오류 · 위치 되읽기')
            self._verify(targets)
        except _Stop as stop:
            self._finish('failed', str(stop))
            return
        except Exception as exc:  # noqa: BLE001 · 어떤 실패도 그 단계에서 멈추고 남긴다
            self._finish('failed', f'예상하지 못한 오류 · {exc}')
            return
        self._finish('done', '앱솔루트 설정 완료 · 기준점을 다시 캡처하세요(클리어로 위치가 바뀌었습니다)')

    def _step(self, key: str, message: str) -> None:
        if self._cancel.is_set():
            raise _Stop('사용자 취소')
        index = [step for step, _label in STEPS].index(key) + 1
        with self._lock:
            self._job.update({
                'step': key, 'step_label': STEP_LABELS[key], 'step_index': index, 'message': message,
            })

    def _note(self, message: str) -> None:
        with self._lock:
            self._job['message'] = message

    def _finish(self, state: str, message: str) -> None:
        with self._lock:
            self._job.update({
                'state': state,
                'message': message,
                'error': message if state == 'failed' else '',
                'finished_at': time.time(),
            })
            job = dict(self._job)
        self._record({
            'event_type': 'minas_absolute_setup_done' if state == 'done' else 'minas_absolute_setup_failed',
            'success': state == 'done',
            'message': f'{job.get("step_label") or ""} · {message}' if state == 'failed' else message,
            'targets': job.get('targets') or [],
            'step': job.get('step'),
        })

    def _servo_off_targets(self, targets: List[Dict[str, Any]]) -> None:
        axes = [int(item['axis']) for item in targets if item.get('axis') is not None]
        for axis in axes:
            motor = self._current_motor(axis) or {}
            if motor.get('servo_on') is False:
                continue
            reply = self._servo_off(axis) or {}
            if reply.get('success') is False:
                raise _Stop(f'{axis}번 모터 서보 OFF 실패 · {reply.get("message") or "응답 없음"}')
        deadline = self._clock() + SERVO_OFF_TIMEOUT_SEC
        while True:
            still_on = [axis for axis in axes if (self._current_motor(axis) or {}).get('servo_on') is not False]
            if not still_on:
                return
            if self._clock() >= deadline:
                raise _Stop(f'서보가 꺼지지 않았습니다 · {", ".join(str(axis) for axis in still_on)}번 모터')
            self._sleep(0.2)

    def _with_motor_manager_stopped(self, work: Callable[[], None]) -> None:
        if not self._lifecycle_lock.acquire(blocking=False):
            raise _Stop('다른 모터 작업이 진행 중입니다')
        try:
            service = self._motor_service()
            was_active = bool(service) and self._service_active(service)
            axes = list(self._expected_axes()) if was_active else []
            error: Optional[BaseException] = None
            restore = ''
            try:
                if was_active:
                    self._run_service('stop', service)
                    self._wait_release()
                work()
            except BaseException as exc:  # noqa: BLE001 · 다시 띄운 뒤 그대로 올린다
                error = exc
            finally:
                if was_active:
                    try:
                        self._run_service('start', service)
                        recovery = self._wait_recovery(service, axes) or {}
                        if not recovery.get('service_active', True):
                            restore = 'Motor Manager 가 다시 실행되지 않았습니다'
                    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                        restore = f'Motor Manager 복구 실패: {exc}'
            if error is not None:
                if restore:
                    raise _Stop(f'{error} / {restore}') from error
                raise error
            if restore:
                raise _Stop(restore)
        finally:
            self._lifecycle_lock.release()

    def _write_mode(self, targets: List[Dict[str, Any]]) -> None:
        for item in targets:
            master, position = int(item['master_index']), int(item['slave_position'])
            base = ['ethercat', 'download', '-m', str(master), '-p', str(position)]
            self._cli(base + ['-t', 'int16', '0x3015', '0', '0'], item)
            value = self._upload(master, position, '0x3015', 'int16', item)
            if value != 0:
                raise _Stop(f'{item["label"]} Pr0.15 되읽기 {value} · 0 이 아닙니다')
            self._cli(base + ['-t', 'uint32', '0x1010', '1', '0x65766173'], item)

    def _check_mode(self, targets: List[Dict[str, Any]]) -> None:
        for item in targets:
            value = self._upload(int(item['master_index']), int(item['slave_position']), '0x3015', 'int16', item)
            if value != 0:
                raise _Stop(f'{item["label"]} 재투입 뒤 Pr0.15 = {value} · EEPROM 에 저장되지 않았습니다')

    def _clear(self, targets: List[Dict[str, Any]]) -> None:
        for item in targets:
            master, position = int(item['master_index']), int(item['slave_position'])
            for command in command_plan(ABSOLUTE_CLEAR, master, position):
                self._cli(command, item)
            verify = verify_command(ABSOLUTE_CLEAR, master, position)
            result = self._call(verify)
            value = parse_upload_value(result.stdout) if result.returncode == 0 else None
            if value is None or not value & ABSOLUTE_CLEAR_BIT:
                raise _Stop(f'{item["label"]} 다회전 클리어 되읽기 실패 · 0x4D00:01 = {value}')

    def _verify(self, targets: List[Dict[str, Any]]) -> None:
        deadline = self._clock() + VERIFY_RETRY_SEC
        while True:
            problems = []
            for item in targets:
                master, position = int(item['master_index']), int(item['slave_position'])
                problems += self._verify_one(master, position, item)
            if not problems:
                return
            if self._clock() >= deadline:
                raise _Stop(' · '.join(problems))
            self._note('검증 · ' + ' · '.join(problems) + ' · 다시 봅니다')
            self._sleep(1.0)

    def _verify_one(self, master: int, position: int, item: Dict[str, Any]) -> List[str]:
        try:
            mode = self._upload(master, position, '0x3015', 'int16', item)
            code = self._upload(master, position, '0x603F', 'uint16', item)
            where = self._upload(master, position, '0x6064', 'int32', item)
        except _Stop as stop:
            return [str(stop)]
        problems = []
        if mode != 0:
            problems.append(f'{item["label"]} Pr0.15 = {mode}')
        if code != 0:
            problems.append(f'{item["label"]} 오류 0x{code & 0xFFFF:04X}')
        if abs(int(where)) >= ONE_TURN_COUNTS:
            problems.append(f'{item["label"]} 위치 {where} count · 한 바퀴 넘음(다회전 값이 남음)')
        return problems

    def _wait_power_cycle(self, targets: List[Dict[str, Any]]) -> None:
        keys = {(int(item['master_index']), int(item['slave_position'])) for item in targets}
        gone: set = set()
        deadline = self._clock() + POWER_CYCLE_TIMEOUT_SEC
        while True:
            if self._cancel.is_set():
                raise _Stop('사용자 취소 · 전원 재투입 대기 중')
            if self._clock() >= deadline:
                raise _Stop('전원 재투입을 기다리다 시간 초과(30분)')
            slaves = self._visible_slaves()
            if slaves is not None:
                seen = {
                    (int(slave.get('master_index') or 0), int(slave.get('slave_position')))
                    for slave in slaves if slave.get('slave_position') is not None
                }
                gone |= keys - seen
                back = {key for key in gone if key in seen}
                waiting_off = sorted(keys - gone)
                waiting_on = sorted(gone - back)
                if not waiting_off and not waiting_on:
                    self._note('대상 드라이브가 모두 돌아왔습니다 · 마스터가 다시 설정할 때까지 잠시 기다립니다')
                    self._sleep(SETTLE_AFTER_RETURN_SEC)
                    return
                parts = []
                if waiting_off:
                    parts.append('전원 꺼짐 대기 ' + ', '.join(f'슬레이브 {p}' for _m, p in waiting_off))
                if waiting_on:
                    parts.append('다시 켜짐 대기 ' + ', '.join(f'슬레이브 {p}' for _m, p in waiting_on))
                self._note('드라이브 전원을 껐다 켜세요 · ' + ' · '.join(parts))
            self._sleep(POLL_SEC)

    # -- ethercat ----------------------------------------------------------- #

    def _call(self, command: List[str]) -> Any:
        try:
            return self._runner(
                command, check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SEC,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _Stop(f'{" ".join(command[1:3])} 실패 · {exc}') from exc

    def _cli(self, command: List[str], item: Dict[str, Any]) -> None:
        result = self._call(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip() or f'종료 코드 {result.returncode}'
            raise _Stop(f'{item["label"]} {" ".join(command[6:])} 실패 · {detail}')

    def _upload(self, master: int, position: int, index: str, data_type: str, item: Dict[str, Any]) -> int:
        command = ['ethercat', 'upload', '-m', str(master), '-p', str(position), '-t', data_type, index, '0']
        result = self._call(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip() or f'종료 코드 {result.returncode}'
            raise _Stop(f'{item["label"]} {index} 읽기 실패 · {detail}')
        parts = (result.stdout or '').split()
        try:
            # `0x0000 0` · 마지막 칸(10진 · 부호 있음)
            return int(parts[-1], 0)
        except (IndexError, ValueError) as exc:
            raise _Stop(f'{item["label"]} {index} 응답을 읽지 못함: {(result.stdout or "").strip()!r}') from exc

    # -- 도움 --------------------------------------------------------------- #

    @staticmethod
    def _scope(payload: Dict[str, Any]) -> Tuple[str, Optional[int], Optional[int], str]:
        scope = str(payload.get('scope') or 'all').strip()
        if scope not in ('all', 'one'):
            return scope, None, None, f'지원하지 않는 범위입니다: {scope}'
        if scope == 'all':
            return scope, None, None, ''
        try:
            return scope, int(payload.get('master_index') or 0), int(payload.get('slave_position')), ''
        except (TypeError, ValueError):
            return scope, None, None, '개별 앱솔루트 설정에는 슬레이브 위치가 필요합니다'

    @staticmethod
    def _view(drive: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'master_index': int(drive.get('master_index') or 0),
            'slave_position': int(drive.get('slave_position')),
            'axis': drive.get('axis'),
            'label': minas_absolute.drive_label(drive),
            'status': drive.get('status'),
            'problem': drive.get('problem') or minas_absolute.drive_problem(drive),
        }


class _Stop(RuntimeError):
    """그 단계에서 멈춘다 · 글은 사람이 읽는 원인"""
