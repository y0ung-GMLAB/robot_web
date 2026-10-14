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

재투입 뒤 읽기 · 다시 읽기 · 이어서 하기 · 수정 목록 134 (실물 2026-10-14 floating4 S-4)
    재투입으로 돌아온 드라이브는 IgH 마스터가 스스로 SDO 사전을 읽는다(우리 잠금 밖) · 그 사이
    4/7 의 0x3015 읽기가 Input/output error 로 한 번에 끝나 다회전 클리어를 못 했고 · 다시 누르면
    「이미 정상」 이라 이어서 할 길이 없었다 · 그래서
    ① 돌아온 뒤 대상 슬레이브 OP(모터 프로그램이 돌 때) + 「버스 설정 중」 표시 꺼짐 + 그 상태로
       `SETTLE_AFTER_RETURN_SEC` 조용할 때까지 · 상태나 표시가 바뀌면 처음부터 다시 센다 ·
    ② 읽기(0x3015 · 0x603F · 0x6064 · 0x4D00 되읽기)는 실패하면 1 s 간격으로 10 s 까지 다시 ·
       값이 틀린 것은 다시 안 읽는다 · 쓰기는 보내지 않고 돌려받은 것(버스 설정 중 · 잠금)만 다시 ·
    ③ EEPROM 에 0 을 저장한 뒤(3/7~7/7)에서 실패하면 그 작업의 드라이브 · 단계를 파일에 남기고
       「이어서 하기」 로 **그 드라이브만** 이어 간다 · 3/7 은 3/7 부터 · 4/7 · 5/7 은 4/7 부터(클리어 전) ·
       6/7 · 7/7 은 그 단계부터(클리어는 이미 함) · 확인 필요 · 24 시간 · 드라이브(시리얼)가 바뀌면 지운다.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from motion_common import ethercat_mailbox, minas_absolute

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
#: 돌아온 뒤 조용한 시간 · 대상 상태 · 「버스 설정 중」 표시가 이만큼 그대로여야 읽는다 · 134 ·
#: IgH 마스터는 슬레이브가 PREOP 가 되고 몇 초 뒤 스스로 SDO 사전을 읽는다(우리 잠금 밖 · 객체가 수백 개라 몇 초) ·
#: 실물 V-18 · 설정 끝 표시가 꺼진 뒤 4~6 s 까지 충돌 · 5 → 10 s · 표시가 꺼진 때부터 세므로 4 s 여유
SETTLE_AFTER_RETURN_SEC = 10.0
#: 모터 프로그램이 돌면 돌아온 드라이브가 OP 가 될 때까지 더 기다린다 · 설정 중 SDO 는 그 설정을 망친다 · 125
RECONFIGURE_WAIT_SEC = 60.0
#: 읽기 실패는 이 간격으로 · 이 시간까지 다시 · 읽기만(값이 틀린 것 · 쓰기는 아님) · 134
READ_RETRY_INTERVAL_SEC = 1.0
READ_RETRY_WINDOW_SEC = 10.0
#: 마지막 검증에서 오류 코드가 사라지길 기다리는 시간(재투입 직후 통신 알람 Err88 이 잠깐 뜬다)
VERIFY_RETRY_SEC = 20.0
#: 서보 OFF 가 상태에 보일 때까지
SERVO_OFF_TIMEOUT_SEC = 5.0
#: 「이어서 하기」 기록을 두는 시간 · 134
RESUME_EXPIRE_SEC = 24 * 3600.0
RESUME_VERSION = 1

STEPS = (
    ('servo_off', '서보 끄기'),
    ('write_mode', '앱솔루트 쓰기 · EEPROM 저장'),
    ('power_cycle_1', '드라이브 전원 껐다 켜기 1'),
    ('check_mode', '앱솔루트 방식 확인'),
    ('clear', '다회전 클리어'),
    ('power_cycle_2', '드라이브 전원 껐다 켜기 2'),
    ('verify', '최종 확인'),
)
STEP_LABELS = dict(STEPS)
STEP_ORDER = [key for key, _label in STEPS]
#: 실패한 단계 → 이어서 할 단계 · EEPROM 에 0 을 저장한 뒤만 · 134 ·
#: 재투입 1 을 못 끝냈으면 그 단계부터(재투입 전 0x3015 는 RAM 값이라 믿을 수 없다) ·
#: 클리어 전(4/7 · 5/7)이면 4/7 부터(클리어를 두 번 해도 같다) · 클리어 뒤면 그 단계부터
RESUME_FROM = {
    'power_cycle_1': 'power_cycle_1',
    'check_mode': 'check_mode',
    'clear': 'check_mode',
    'power_cycle_2': 'power_cycle_2',
    'verify': 'verify',
}
NO_RESUME_MESSAGE = '이어서 할 앱솔루트 설정이 없습니다'
#: 드라이브가 같은지 · `ethercat slaves -v` 에서 읽는 값
IDENTITY_FIELDS = ('serial_number', 'vendor_id', 'product_code')


def step_index(key: str) -> int:
    return STEP_ORDER.index(key) + 1


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
            return [], [], f'마스터 {master} 슬레이브 {position}에 MINAS 드라이브가 보이지 않습니다'
        drives = chosen
    targets = [drive for drive in drives if drive.get('status') != minas_absolute.DRIVE_OK]
    skipped = [drive for drive in drives if drive.get('status') == minas_absolute.DRIVE_OK]
    if not targets:
        return [], skipped, '이미 앱솔루트 방식으로 정상입니다. 다시 클리어하면 기준점이 사라지므로 하지 않습니다'
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
        bus_configuring: Callable[[], bool] = ethercat_mailbox.configuring,
        resume_file: Optional[Union[str, Path]] = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        # SDO 는 다른 프로세스와 한 번에 하나 · 버스 설정 중이면 안 보냄 · 수정 목록 125
        self._runner = ethercat_mailbox.guarded(runner)
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
        self._bus_configuring = bus_configuring
        self._wall = wall_clock
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._job: Dict[str, Any] = {'state': 'idle'}
        #: 「이어서 하기」 · 웹 브리지를 다시 띄워도 남게 파일로 · None = 메모리만(시험) · 134
        self._resume_file = Path(resume_file) if resume_file else None
        self._resume: Optional[Dict[str, Any]] = self._read_resume_file()

    # -- 바깥에서 부른다 ---------------------------------------------------- #

    def active(self) -> bool:
        with self._lock:
            return self._job.get('state') == 'running'

    def blocker(self) -> str:
        return '앱솔루트 설정 진행 중입니다. 끝날 때까지 모터 동작을 차단합니다' if self.active() else ''

    def status(self) -> Dict[str, Any]:
        with self._lock:
            job = dict(self._job)
            job['targets'] = [dict(item) for item in job.get('targets') or []]
            job['skipped'] = [dict(item) for item in job.get('skipped') or []]
        job['resume'] = self._resume_view()
        return job

    def preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """확인 창에 띄울 처리 대상 · 건너뜀 목록"""
        if payload.get('resume') is True:
            return self._resume_preview(payload)
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
            return {'success': False, 'message': '앱솔루트 설정을 하려면 확인이 필요합니다'}
        if payload.get('resume') is True:
            return self._start_resume(payload)
        scope, master, position, error = self._scope(payload)
        if error:
            return {'success': False, 'message': error}
        blocker = self._safety_blocker()
        if blocker:
            return {'success': False, 'message': f'앱솔루트 설정을 할 수 없습니다: {blocker}'}
        targets, skipped, reason = plan_targets(
            self._minas(), scope=scope, master=master, position=position,
        )
        if reason:
            return {'success': False, 'message': f'앱솔루트 설정을 할 수 없습니다: {reason}'}
        started = self._begin(
            scope=scope, first=STEP_ORDER[0],
            targets=[self._view(drive) for drive in targets],
            skipped=[self._view(drive) for drive in skipped],
        )
        if not started:
            return {'success': False, 'message': '앱솔루트 설정이 이미 진행 중입니다'}
        return {'success': True, 'message': f'앱솔루트 설정을 시작했습니다 · 대상 {len(targets)}대', 'job': self.status()}

    def cancel(self) -> Dict[str, Any]:
        """전원 재투입을 기다리는 동안만 의미가 있다 · 쓰는 중에는 그 단계가 끝나야 선다"""
        if not self.active():
            return {'success': False, 'message': '진행 중인 앱솔루트 설정이 없습니다'}
        self._cancel.set()
        return {'success': True, 'message': '앱솔루트 설정 취소를 요청했습니다. 현재 단계가 끝나면 중지합니다'}

    # -- 이어서 하기 · 134 -------------------------------------------------- #

    def _resume_plan(self, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], str]:
        """(기록 · 이어서 할 드라이브 · 거절 사유) · 그 작업의 드라이브만 · 같은 드라이브(시리얼)인지 확인"""
        record = self._current_resume()
        if not record:
            return None, [], NO_RESUME_MESSAGE
        minas = self._minas()
        if isinstance(minas, dict) and str(minas.get('state') or '') == minas_absolute.STATE_CHECKING:
            return None, [], minas_absolute.CHECKING_MESSAGE
        targets = [dict(item) for item in record['targets']]
        if str(payload.get('scope') or 'all').strip() == 'one':
            scope, master, position, error = self._scope(payload)
            if error:
                return None, [], error
            if [drive_key(item) for item in targets] != [(int(master or 0), int(position))]:
                return None, [], (
                    f'마스터 {master} 슬레이브 {position}는 이어서 할 작업의 드라이브가 아닙니다. '
                    f'이어서 하기는 실패한 작업의 드라이브 {len(targets)}대를 함께 진행합니다'
                )
        slaves = self._visible_slaves()
        if slaves is None:
            return None, [], '슬레이브 목록을 읽지 못해 같은 드라이브인지 확인할 수 없습니다. 잠시 뒤 다시 하세요'
        by_key = {
            (int(slave.get('master_index') or 0), int(slave.get('slave_position'))): slave
            for slave in slaves if slave.get('slave_position') is not None
        }
        missing = [item['label'] for item in targets if drive_key(item) not in by_key]
        if missing:
            return None, [], f'{", ".join(missing)} 드라이브가 보이지 않습니다. 전원을 켜고 다시 하세요'
        changed = [
            item['label'] for item in targets
            if self._identity_changed(item.get('identity'), by_key[drive_key(item)])
        ]
        if changed:
            self._drop_resume()
            return None, [], (
                f'{", ".join(changed)} 드라이브가 실패했을 때와 다릅니다(시리얼). '
                '이어서 하기를 지웠습니다. 앱솔루트 설정을 처음부터 하세요'
            )
        # 번호(축)는 지금 등록 기준 · 서보 끄기에 쓴다
        drives = {
            drive_key(drive): drive for drive in (minas.get('drives') if isinstance(minas, dict) else None) or []
            if isinstance(drive, dict) and drive.get('slave_position') is not None
        }
        for item in targets:
            now = drives.get(drive_key(item))
            if now:
                fresh = self._view(now)
                item.update(axis=fresh['axis'], label=fresh['label'], status=fresh['status'], problem=fresh['problem'])
        return record, targets, ''

    def _resume_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record, targets, reason = self._resume_plan(payload)
        if reason:
            return {'success': False, 'message': reason, 'resume': True}
        first = record['resume_from']
        return {
            'success': True,
            'resume': True,
            'message': f'이어서 하기 · {step_index(first)}/{len(STEPS)} {STEP_LABELS[first]}부터 · 대상 {len(targets)}대',
            'targets': [self._public_target(item) for item in targets],
            'skipped': [],
            'steps': [label for key, label in STEPS if step_index(key) >= step_index(first)],
            'from_step': first,
            'from_index': step_index(first),
            'step_count': len(STEPS),
            'failed_step': record['failed_step'],
            'failed_index': step_index(record['failed_step']),
            'failed_label': STEP_LABELS[record['failed_step']],
            'error': record.get('error') or '',
            'clear_done': step_index(first) > step_index('clear'),
        }

    def _start_resume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        blocker = self._safety_blocker()
        if blocker:
            return {'success': False, 'message': f'앱솔루트 설정을 할 수 없습니다: {blocker}'}
        if self.active():
            return {'success': False, 'message': '앱솔루트 설정이 이미 진행 중입니다'}
        record, targets, reason = self._resume_plan(payload)
        if reason:
            return {'success': False, 'message': f'이어서 할 수 없습니다: {reason}'}
        first = record['resume_from']
        if not self._begin(scope=record.get('scope') or 'all', first=first, targets=targets, skipped=[], resumed=True):
            return {'success': False, 'message': '앱솔루트 설정이 이미 진행 중입니다'}
        return {
            'success': True,
            'message': f'앱솔루트 설정을 이어서 합니다 · {step_index(first)}/{len(STEPS)} {STEP_LABELS[first]}부터 · 대상 {len(targets)}대',
            'job': self.status(),
        }

    @staticmethod
    def _identity_changed(saved: Any, slave: Dict[str, Any]) -> bool:
        """남긴 값과 지금 값이 둘 다 있는데 다르면 바뀐 것 · 남긴 값이 없으면(그때 못 읽음) 위치만 본다"""
        if not isinstance(saved, dict):
            return False
        return any(
            saved.get(field) is not None and slave.get(field) is not None and saved.get(field) != slave.get(field)
            for field in IDENTITY_FIELDS
        )

    def _resume_view(self) -> Optional[Dict[str, Any]]:
        record = self._current_resume()
        if not record:
            return None
        first, failed = record['resume_from'], record['failed_step']
        return {
            'from_step': first,
            'from_index': step_index(first),
            'from_label': STEP_LABELS[first],
            'step_count': len(STEPS),
            'failed_step': failed,
            'failed_index': step_index(failed),
            'failed_label': STEP_LABELS[failed],
            'error': record.get('error') or '',
            'failed_at': record.get('failed_at'),
            'expires_at': float(record.get('failed_at') or 0.0) + RESUME_EXPIRE_SEC,
            'targets': [self._public_target(item) for item in record['targets']],
        }

    @staticmethod
    def _public_target(item: Dict[str, Any]) -> Dict[str, Any]:
        return {key: item.get(key) for key in ('master_index', 'slave_position', 'axis', 'label', 'status', 'problem')}

    def _current_resume(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._resume
        if not record:
            return None
        if self._wall() - float(record.get('failed_at') or 0.0) > RESUME_EXPIRE_SEC:
            self._drop_resume()
            return None
        return record

    def _save_resume(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self._resume = record
        if self._resume_file is None:
            return
        try:
            self._resume_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._resume_file.with_name(f'.{self._resume_file.name}.{os.getpid()}')
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(temporary, self._resume_file)
        except OSError:
            pass        # 파일을 못 써도 이 프로세스가 도는 동안은 이어서 할 수 있다

    def _drop_resume(self) -> None:
        with self._lock:
            self._resume = None
        if self._resume_file is None:
            return
        try:
            self._resume_file.unlink()
        except OSError:
            pass

    def _read_resume_file(self) -> Optional[Dict[str, Any]]:
        if self._resume_file is None:
            return None
        try:
            record = json.loads(self._resume_file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            record = None
        if not self._valid_resume(record):
            try:
                self._resume_file.unlink()
            except OSError:
                pass
            return None
        return record

    @staticmethod
    def _valid_resume(record: Any) -> bool:
        if not isinstance(record, dict) or record.get('version') != RESUME_VERSION:
            return False
        if record.get('failed_step') not in RESUME_FROM or record.get('resume_from') != RESUME_FROM[record['failed_step']]:
            return False
        try:
            float(record.get('failed_at'))
            targets = record.get('targets')
            return bool(targets) and all(
                isinstance(item, dict) and isinstance(item.get('label'), str) and drive_key(item) is not None
                for item in targets
            )
        except (TypeError, ValueError):
            return False

    # -- 단계 ------------------------------------------------------------- #

    def _begin(
        self, *, scope: str, first: str, targets: List[Dict[str, Any]], skipped: List[Dict[str, Any]],
        resumed: bool = False,
    ) -> bool:
        with self._lock:
            if self._job.get('state') == 'running':
                return False
            self._cancel.clear()
            self._job = {
                'state': 'running',
                'scope': scope,
                'step': first,
                'step_label': STEP_LABELS[first],
                'step_index': step_index(first),
                'step_count': len(STEPS),
                'message': f'{step_index(first)}/{len(STEPS)}부터 이어서 시작' if resumed else '시작',
                'started_at': time.time(),
                'targets': targets,
                'skipped': skipped,
                'resumed': resumed,
                'resume_from': first if resumed else '',
                'error': '',
            }
        self._spawn(self._run)
        return True

    def _run(self) -> None:
        job = self.status()
        targets = job['targets']
        resumed = bool(job.get('resumed'))
        first = step_index(job.get('resume_from') or STEP_ORDER[0])

        def due(key: str) -> bool:
            return step_index(key) >= first

        try:
            if not resumed:
                targets = self._remember_identity(targets)
            if due('servo_off'):
                self._step('servo_off', '대상 모터의 서보를 끕니다')
                self._servo_off_targets(targets)
            if due('write_mode'):
                self._step('write_mode', 'Motor Manager를 정지하고 Pr0.15 = 0을 EEPROM에 저장합니다')
                self._with_motor_manager_stopped(lambda: self._write_mode(targets))
            if due('power_cycle_1'):
                self._step('power_cycle_1', '드라이브 전원을 껐다 켜세요. 대상 드라이브가 꺼졌다가 다시 연결되면 다음 단계로 넘어갑니다')
                if resumed:
                    self._servo_off_targets(targets)
                self._wait_power_cycle(targets)
            if due('check_mode'):
                self._step('check_mode', '전원을 다시 켠 뒤 Pr0.15를 다시 읽습니다')
                if first == step_index('check_mode'):
                    self._wait_settled(targets)
                self._check_mode(targets)
            if due('clear'):
                self._step('clear', '서보 끄기 → Motor Manager 정지 → 다회전 클리어')
                self._servo_off_targets(targets)
                self._with_motor_manager_stopped(lambda: self._clear(targets))
            if due('power_cycle_2'):
                self._step('power_cycle_2', '드라이브 전원을 한 번 더 껐다 켜세요. 그래야 다회전 클리어가 적용됩니다')
                if resumed:
                    self._servo_off_targets(targets)
                self._wait_power_cycle(targets)
            self._step('verify', 'Pr0.15 · 오류 · 위치를 다시 읽습니다')
            if first == step_index('verify'):
                self._wait_settled(targets)
            self._verify(targets)
        except _Stop as stop:
            self._finish('failed', str(stop), resumable=stop.resumable)
            return
        except Exception as exc:  # noqa: BLE001 · 어떤 실패도 그 단계에서 멈추고 남긴다
            self._finish('failed', f'예상하지 못한 오류: {exc}')
            return
        self._finish('done', '앱솔루트 설정을 마쳤습니다. 위치 값이 바뀌었으니 기준점을 다시 캡처하세요')

    def _remember_identity(self, targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """쓰기 전 드라이브 시리얼 · 이어서 하기가 같은 드라이브인지 볼 때 쓴다 · 못 읽으면 위치만 · 134"""
        try:
            slaves = self._visible_slaves() or []
        except Exception:  # noqa: BLE001 · 못 읽어도 설정은 한다
            slaves = []
        by_key = {
            (int(slave.get('master_index') or 0), int(slave.get('slave_position'))): slave
            for slave in slaves if isinstance(slave, dict) and slave.get('slave_position') is not None
        }
        updated = []
        for item in targets:
            slave = by_key.get(drive_key(item)) or {}
            updated.append({**item, 'identity': {field: slave.get(field) for field in IDENTITY_FIELDS}})
        with self._lock:
            self._job['targets'] = [dict(item) for item in updated]
        return updated

    def _step(self, key: str, message: str) -> None:
        if self._cancel.is_set():
            raise _Stop('사용자가 취소했습니다')
        with self._lock:
            self._job.update({
                'step': key, 'step_label': STEP_LABELS[key], 'step_index': step_index(key), 'message': message,
            })

    def _note(self, message: str) -> None:
        with self._lock:
            self._job['message'] = message

    def _finish(self, state: str, message: str, *, resumable: bool = True) -> None:
        with self._lock:
            self._job.update({
                'state': state,
                'message': message,
                'error': message if state == 'failed' else '',
                'finished_at': time.time(),
            })
            job = dict(self._job)
        resume_from = RESUME_FROM.get(str(job.get('step') or '')) if state == 'failed' and resumable else None
        keys = {drive_key(item) for item in job.get('targets') or []}
        if resume_from:
            self._save_resume({
                'version': RESUME_VERSION,
                'failed_at': self._wall(),
                'failed_step': job.get('step'),
                'resume_from': resume_from,
                'error': message,
                'scope': job.get('scope') or 'all',
                'targets': [dict(item) for item in job.get('targets') or []],
            })
        else:
            existing = self._current_resume()
            # 이어서 한 작업이 끝났거나 더 이어 갈 수 없게 실패 · 새 작업이 그 드라이브를 끝냄 → 지운다 ·
            # 새 작업이 앞 단계(1/7 · 2/7)에서 실패하면 다른 드라이브의 기록은 그대로
            if existing and (
                job.get('resumed')
                or (state == 'done' and keys & {drive_key(item) for item in existing['targets']})
            ):
                self._drop_resume()
        self._record({
            'event_type': 'minas_absolute_setup_done' if state == 'done' else 'minas_absolute_setup_failed',
            'success': state == 'done',
            'message': f'{job.get("step_label") or ""} · {message}' if state == 'failed' else message,
            'targets': job.get('targets') or [],
            'step': job.get('step'),
            'resumed': bool(job.get('resumed')),
            'resume_from': resume_from or '',
        })

    def _servo_off_targets(self, targets: List[Dict[str, Any]]) -> None:
        axes = [int(item['axis']) for item in targets if item.get('axis') is not None]
        for axis in axes:
            motor = self._current_motor(axis) or {}
            if motor.get('servo_on') is False:
                continue
            reply = self._servo_off(axis) or {}
            if reply.get('success') is False:
                raise _Stop(f'{axis}번 모터 서보 끄기 실패 · {reply.get("message") or "응답 없음"}')
        deadline = self._clock() + SERVO_OFF_TIMEOUT_SEC
        while True:
            still_on = [axis for axis in axes if (self._current_motor(axis) or {}).get('servo_on') is not False]
            if not still_on:
                return
            if self._clock() >= deadline:
                raise _Stop(f'{", ".join(str(axis) for axis in still_on)}번 모터의 서보가 꺼지지 않았습니다')
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
                            restore = 'Motor Manager가 다시 실행되지 않았습니다'
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
                raise _Stop(f'{item["label"]} Pr0.15를 다시 읽은 값이 {value}입니다. 0이어야 합니다')
            self._cli(base + ['-t', 'uint32', '0x1010', '1', '0x65766173'], item)

    def _check_mode(self, targets: List[Dict[str, Any]]) -> None:
        for item in targets:
            value = self._upload(int(item['master_index']), int(item['slave_position']), '0x3015', 'int16', item)
            if value != 0:
                # EEPROM 에 0 이 없다 · 이어서 해도 같은 값 · 상태 모니터가 「앱솔루트 아님」 으로 보므로 처음부터 다시
                raise _Stop(
                    f'{item["label"]} 전원을 다시 켠 뒤 Pr0.15 = {value}입니다. EEPROM에 저장되지 않았습니다',
                    resumable=False,
                )

    def _clear(self, targets: List[Dict[str, Any]]) -> None:
        for item in targets:
            master, position = int(item['master_index']), int(item['slave_position'])
            for command in command_plan(ABSOLUTE_CLEAR, master, position):
                self._cli(command, item)
            verify = verify_command(ABSOLUTE_CLEAR, master, position)
            value = self._read(verify, parse_upload_value, item, '0x4D00:01')
            if not value & ABSOLUTE_CLEAR_BIT:
                raise _Stop(f'{item["label"]} 다회전 클리어 확인 실패 · 0x4D00:01 = {value}')

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
            self._note('최종 확인 · ' + ' · '.join(problems) + ' · 다시 확인합니다')
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
            problems.append(f'{item["label"]} 위치 {where} count · 한 바퀴를 넘음(다회전 값이 남아 있음)')
        return problems

    def _wait_power_cycle(self, targets: List[Dict[str, Any]]) -> None:
        keys = {(int(item['master_index']), int(item['slave_position'])) for item in targets}
        gone: set = set()
        deadline = self._clock() + POWER_CYCLE_TIMEOUT_SEC
        while True:
            if self._cancel.is_set():
                raise _Stop('전원을 껐다 켜기를 기다리던 중에 사용자가 취소했습니다')
            if self._clock() >= deadline:
                raise _Stop('30분 안에 드라이브 전원을 껐다 켜지 않아 중지했습니다')
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
                    self._note('대상 드라이브가 모두 다시 연결됐습니다. EtherCAT 마스터가 다시 설정할 때까지 잠시 기다립니다')
                    self._wait_reconfigured(keys, slaves)
                    self._settle(keys)
                    return
                parts = []
                if waiting_off:
                    parts.append('전원 꺼짐 대기 ' + ', '.join(f'슬레이브 {p}' for _m, p in waiting_off))
                if waiting_on:
                    parts.append('다시 켜짐 대기 ' + ', '.join(f'슬레이브 {p}' for _m, p in waiting_on))
                self._note('드라이브 전원을 껐다 켜세요 · ' + ' · '.join(parts))
            self._sleep(POLL_SEC)

    def _wait_settled(self, targets: List[Dict[str, Any]]) -> None:
        """이어서 하기 · 재투입을 기다리지 않고 읽는 단계부터 · 그래도 버스가 자리 잡았는지 먼저 본다 · 134"""
        keys = {drive_key(item) for item in targets}
        self._note('버스가 자리 잡을 때까지 잠시 기다립니다')
        self._wait_reconfigured(keys, self._visible_slaves() or [])
        self._settle(keys)

    def _wait_reconfigured(self, keys: set, slaves: List[Dict[str, Any]]) -> None:
        """모터 프로그램이 돌면 돌아온 드라이브가 OP 가 될 때까지 · 그동안 마스터가 설정 SDO 를 쓴다 · 125

        모터 프로그램이 없으면(PREOP 그대로) · 상태를 모르면 · `RECONFIGURE_WAIT_SEC` 이 지나면 그냥 넘어간다 ·
        다음 읽기가 실패하면 다시 읽고(134) 그래도 안 되면 그 단계에서 멈추고 이유를 남긴다.
        """
        deadline = self._clock() + RECONFIGURE_WAIT_SEC
        while True:
            if not self._configuring():
                service = self._motor_service()
                if not (service and self._service_active(service)):
                    return
                states = {
                    (int(slave.get('master_index') or 0), int(slave.get('slave_position'))): slave.get('device_state')
                    for slave in slaves or [] if slave.get('slave_position') is not None
                }
                found = [states.get(key) for key in keys]
                if any(state is None for state in found) or all(str(state).upper() == 'OP' for state in found):
                    return
            if self._clock() >= deadline:
                return
            self._sleep(POLL_SEC)
            slaves = self._visible_slaves() or []

    def _settle(self, keys: set) -> None:
        """조용한 시간 · 대상 상태와 「버스 설정 중」 표시가 `SETTLE_AFTER_RETURN_SEC` 그대로일 때까지 · 134

        마스터가 OP 뒤 스스로 SDO 사전을 읽는 동안(우리 잠금 밖) 우리 읽기가 끼지 않게 · 바뀌면 처음부터 다시 센다 ·
        목록을 못 읽은 때(None)는 그대로로 본다 · 길어도 `RECONFIGURE_WAIT_SEC` 이면 넘어간다(읽기는 다시 읽기로 버틴다).
        """
        started = self._clock()
        since = started
        last: Any = None
        while True:
            slaves = self._visible_slaves()
            now = self._clock()
            if slaves is not None:
                states = {
                    (int(slave.get('master_index') or 0), int(slave.get('slave_position'))): str(slave.get('device_state') or '')
                    for slave in slaves if slave.get('slave_position') is not None
                }
                snapshot = (self._configuring(), tuple(states.get(key) for key in sorted(keys)))
                if snapshot != last:
                    last, since = snapshot, now
            quiet = now - since
            if last is not None and not last[0] and quiet >= SETTLE_AFTER_RETURN_SEC:
                return
            if now - started >= RECONFIGURE_WAIT_SEC:
                return
            self._note(f'대상 드라이브가 다시 연결됐습니다. 마스터가 드라이브 정보를 읽는 동안 기다립니다 ({quiet:.0f}/{SETTLE_AFTER_RETURN_SEC:.0f} s)')
            self._sleep(POLL_SEC)

    def _configuring(self) -> bool:
        try:
            return bool(self._bus_configuring())
        except Exception:  # noqa: BLE001 · 표시를 못 읽으면 없는 것으로
            return False

    # -- ethercat ----------------------------------------------------------- #

    def _call(self, command: List[str]) -> Any:
        try:
            return self._runner(
                command, check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SEC,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _Stop(f'{" ".join(command[1:3])} 실패 · {exc}') from exc

    def _cli(self, command: List[str], item: Dict[str, Any]) -> None:
        """쓰기 · 보낸 것은 다시 안 보낸다 · 보내지 않고 돌려받은 것(버스 설정 중 · 잠금)만 다시 · 134"""
        deadline = self._clock() + READ_RETRY_WINDOW_SEC
        while True:
            result = self._call(command)
            if not (ethercat_mailbox.is_refused(result) and self._clock() < deadline):
                break
            self._sleep(READ_RETRY_INTERVAL_SEC)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip() or f'종료 코드 {result.returncode}'
            raise _Stop(f'{item["label"]} {" ".join(command[6:])} 실패 · {detail}')

    def _upload(self, master: int, position: int, index: str, data_type: str, item: Dict[str, Any]) -> int:
        command = ['ethercat', 'upload', '-m', str(master), '-p', str(position), '-t', data_type, index, '0']
        return self._read(command, _last_int, item, index)

    def _read(
        self, command: List[str], parse: Callable[[str], Optional[int]], item: Dict[str, Any], what: str,
    ) -> int:
        """읽기 · 실패(오류 · 응답 없음 · 못 알아봄)면 `READ_RETRY_INTERVAL_SEC` 간격으로 `READ_RETRY_WINDOW_SEC` 까지 다시 · 134

        재투입 직후 마스터가 스스로 SDO 사전을 읽는 동안 「Input/output error」 가 난다(실물 S-4) ·
        값은 판단하지 않는다(부른 쪽이 본다 · 틀린 값은 다시 읽어도 같다) · 적어도 두 번은 해 본다.
        """
        deadline = self._clock() + READ_RETRY_WINDOW_SEC
        attempt = 0
        while True:
            attempt += 1
            try:
                result = self._call(command)
            except _Stop as stop:
                detail = str(stop)
            else:
                if result.returncode == 0:
                    value = parse(result.stdout or '')
                    if value is not None:
                        return value
                    detail = f'응답을 읽지 못함: {(result.stdout or "").strip()!r}'
                else:
                    detail = (result.stderr or result.stdout or '').strip() or f'종료 코드 {result.returncode}'
            if attempt >= 2 and self._clock() >= deadline:
                raise _Stop(f'{item["label"]} {what} 읽기 실패 · {detail} ({attempt}번 시도)')
            self._note(f'{item["label"]} {what} 읽기 실패 · 다시 읽습니다 ({attempt}번째) · {detail}')
            self._sleep(READ_RETRY_INTERVAL_SEC)

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


def _last_int(text: str) -> Optional[int]:
    """`0x0000 0` · 마지막 칸(10진 · 부호 있음)"""
    parts = (text or '').split()
    try:
        return int(parts[-1], 0)
    except (IndexError, ValueError):
        return None


class _Stop(RuntimeError):
    """그 단계에서 멈춘다 · 글은 사람이 읽는 원인 · resumable 거짓이면 「이어서 하기」 를 남기지 않는다(다시 해도 같은 결과)"""

    def __init__(self, message: str, *, resumable: bool = True) -> None:
        super().__init__(message)
        self.resumable = resumable
