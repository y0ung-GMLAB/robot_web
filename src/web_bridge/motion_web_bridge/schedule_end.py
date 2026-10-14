"""스케줄이 끝나면 · 기준점 주차 → 서보 OFF · 수정 목록 36 (2026-10-06)

전에는 운영 시간이 끝나면 「현재 회차 후 정지」 만 했다 · 애니메이션 마지막
프레임 자세에서 서보가 켜진 채 밤새 서 있었다(발열·전력·사람이 만지면 버팀).

이제 이 PC 의 프로젝트 설정(`schedule_end_action`)을 따른다.

    park_servo_off (기본)   지금 애니 마무리 → 기준점(조인트 0°)으로 천천히 →
                            도달 확인 → AC 서보 OFF(브레이크) · 다이나믹셀 토크 OFF
    hold                    옛 동작 · 마지막 자세에서 서보 켠 채 정지

모터별로 「끝나면 서보 OFF」 를 끌 수 있다 (모터 설정 `config.schedule_end_servo_off`).

**주차가 안 되면 바로 끄지 않는다** · 알람·오류·거절·도달 실패·시간 초과면 홀드 + 기록
(모터 기록 「구간 끝 주차 실패 · 이유」 · 화면 「확인할 일」) · 약 1분 뒤 다시(모두 3번) ·
3번 다 안 되면 **그 자리에서** 서보 OFF · 수정 목록 131 (사용자 2026-10-13 · 실물 V-19 ·
초기 위치 이동이 「실행 컨텍스트 적용 대기」 로 거절됐는데 기록도 다시 시도도 없이 밤새 서보가 켜져 있었다).
**이미 멈춰 있던 로봇도** 구간 끝에 주차 → 서보 OFF (사용자 2026-10-13 · 전에는 돌던 것만) ·
이 PC 가 스케줄 모드일 때만 · 끌 모터가 없거나 서보가 꺼져 있으면 건드리지 않는다.
**다음 시작** · 여기서 끈 모터만 기억해 두었다가 시작(스케줄·수동·그룹 준비) 전에
켜고 켜진 것을 확인한다 · 사람이 손으로 끈 모터는 건드리지 않는다.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from motion_common import run_state

PARK_SERVO_OFF = 'park_servo_off'
HOLD = 'hold'
END_ACTIONS = (PARK_SERVO_OFF, HOLD)
DEFAULT_END_ACTION = PARK_SERVO_OFF

#: 회차가 끝나기를 기다리는 상한 · 긴 애니도 이 안에는 끝난다
CYCLE_WAIT_SEC = 30 * 60
#: 그룹 실행이 풀리기를 기다리는 상한 · 모든 PC 가 회차를 끝내야 풀린다
GROUP_RELEASE_WAIT_SEC = 5 * 60
#: 기준점 이동 시간 · 화면 선택지 중 가장 느린 값
PARK_MOVE_SEC = 10.0
PARK_WAIT_SEC = PARK_MOVE_SEC + 40.0
SERVO_ON_WAIT_SEC = 5.0
POLL_SEC = 0.5

#: 회차를 끝내고 멈춘 상태 · 여기서 주차를 시작한다
FINISHED_STATES = {'idle', 'ready', 'stopped', 'completed', 'motion_completed', 'initialized'}

STATE_FILE = 'schedule_end_state.json'

#: 구간 끝 주차 시도 횟수 · 첫 시도 + 약 1분 간격 두 번 · 수정 목록 131 (사용자 2026-10-13)
PARK_ATTEMPTS = 3
#: 스케줄 점검 주기(`RECONCILE_INTERVAL_SEC`)와 같다 · 「다음 점검 때 다시」
RETRY_INTERVAL_SEC = 60.0
#: 기다리는 동안은 시작 요청만 본다 · 무거운 상태 조회는 기다림이 끝난 뒤 한 번
RETRY_POLL_SEC = 5.0
#: 브리지가 다시 켜졌을 때 이보다 오래된 「다시 시도 중」 기록은 버린다 ·
#: 밤새 꺼져 있다 켜진 PC 가 아침에 혼자 주차하지 않게
RESUME_MAX_AGE_SEC = 15 * 60
#: 몇 번째 시도인가 · 포기 뒤 알림 · 브리지가 다시 켜져도 같은 구간 끝을 처음부터 세지 않는다
RETRY_FILE = 'schedule_end_retry.json'

#: 실패 뒤 다음 걸음
RETRY = 'retry'
GIVE_UP = 'give_up'

#: 포기 뒤 걸음
GIVE_UP_CANCEL = 'cancel'        # 누가 로봇을 맡았다 · 아무것도 안 함
GIVE_UP_KEEP = 'keep'            # 끄면 안 된다 · 켠 채 + 빨간 알림
GIVE_UP_NOTHING = 'nothing'      # 끌 서보가 없다 · 정리만
GIVE_UP_SERVO_OFF = 'servo_off'  # 그 자리에서 서보 OFF

#: 브리지가 다시 켜졌을 때
RESUME_NONE = 'none'
RESUME_RETRY = 'retry'      # 같은 구간 끝 · 남은 횟수만큼 1분 뒤부터
RESUME_NOTICE = 'notice'    # 포기 알림을 다시 띄운다(다음 시작까지)
RESUME_DROP = 'drop'        # 너무 오래됐거나 못 읽는다 · 버린다

#: 이 상태면 주차가 진행 중 · 시작을 막는다 · 다시 시도를 기다리는 동안(`retry_wait`)은 막지 않는다
ACTIVE_STATES = {'waiting_cycle', 'parking', 'powering_off'}


def normalize_end_action(value: Any) -> str:
    text = str(value or '').strip().lower()
    return text if text in END_ACTIONS else DEFAULT_END_ACTION


def motor_turns_off_at_end(entry: Dict[str, Any]) -> bool:
    """모터별 「끝나면 서보 OFF」 · 안 적었으면 켬(끈다) · AC·다이나믹셀 같은 규칙"""
    config = entry.get('config') if isinstance(entry.get('config'), dict) else {}
    return config.get('schedule_end_servo_off') is not False


#: 운전 모드 화면 글자 · 스케줄이 아니면 주차하지 않는다
_MODE_TEXT = {'manual': '수동', 'off': '끔'}


def mode_skip(run_mode: Optional[str]) -> Optional[Tuple[str, str]]:
    """이 PC 가 스케줄 모드가 아니면 주차하지 않는다 · 사람이 만지는 중일 수 있다 · 사용자 2026-10-13

    `None` = 모드를 읽지 않는 호출(옛 배선) · 판단하지 않는다 · 빈 값 = 못 읽음 · 안 움직인다.
    """
    if run_mode is None or run_mode == 'schedule':
        return None
    text = _MODE_TEXT.get(run_mode)
    if not text:
        return 'failed', '운전 모드를 확인할 수 없어 주차하지 않고 그대로 둡니다'
    return 'skipped', f'운영 종료 · 이 PC 는 {text} 모드라 주차하지 않고 그대로 둡니다'


def idle_park_skip(
    motors: List[Dict[str, Any]], flags: Dict[int, bool], alarm_grade: int,
) -> Optional[Tuple[str, str]]:
    """구간 끝에 **멈춰 있던** 로봇을 주차할 수 있나 · 못 하면 (상태, 글) · 사용자 2026-10-13

    주차는 서보가 켜져 있고 알람이 없어야 한다 · 억지로 켜지 않는다 ·
    끌 모터가 없으면(모터 설정 「끝나면 서보 끄기」 전부 끔) 움직일 까닭이 없다 ·
    기준점 · 앱솔루트 미확인은 기준점 이동이 거절하고 그 이유가 남는다.
    'failed' 는 실패로 세어 1분 뒤 다시 본다 · 수정 목록 131
    """
    if alarm_grade > 0:
        return 'failed', f'서보 알람 {alarm_grade}등급이라 주차하지 않았습니다'
    targets = [
        motor for motor in motors
        if motor.get('controller_index') is not None and flags.get(int(motor['controller_index']), True)
    ]
    if not targets:
        return 'skipped', '운영 종료 · 끝나면 서보를 끌 모터가 없어(모터 설정) 주차하지 않습니다'
    off = sorted(int(motor['controller_index']) for motor in targets if motor.get('servo_on') is False)
    if len(off) == len(targets):
        return 'skipped', '운영 종료 · 서보가 이미 꺼져 있어 그대로 둡니다'
    if off:
        return 'failed', f'서보가 꺼진 모터가 있어 주차하지 않았습니다 · {", ".join(map(str, off))}번'
    return None


# --------------------------------------------------------------------------- #
# 주차가 거절·실패했을 때 · 판단은 여기 · 수정 목록 131 (사용자 2026-10-13)
# --------------------------------------------------------------------------- #

def after_failure(attempts: int, max_attempts: int = PARK_ATTEMPTS) -> str:
    """몇 번째 실패인가 · 다 썼으면 포기(그 자리에서 서보 OFF 판단) · 아니면 1분 뒤 다시"""
    return GIVE_UP if int(attempts) >= int(max_attempts) else RETRY


def retry_cancel_reason(
    *, run_mode: Optional[str], running: bool, in_window: bool, start_requested: bool,
) -> str:
    """다시 시도를 그만둘 까닭 · 빈 글 = 계속 · 사람이나 스케줄이 로봇을 맡았으면 손대지 않는다

    `run_mode` None = 모드를 안 읽는 배선 · 빈 글(못 읽음)은 그만두지 않는다(시도가 다시 거른다).
    """
    if start_requested:
        return '시작 요청이 들어옴'
    if run_mode in _MODE_TEXT:
        return f'{_MODE_TEXT[run_mode]} 모드로 바뀜'
    if running:
        return '재생이 돌고 있음'
    if in_window:
        return '운영 구간이 다시 시작됨'
    return ''


def give_up_step(
    *, run_mode: Optional[str], running: bool, in_window: bool, start_requested: bool,
    alarm_grade: int, servo_on_targets: int,
) -> Tuple[str, str]:
    """주차를 끝내 못 했다 · 그 자리에서 서보를 끄나 · (걸음, 까닭)

    알람이면 끄지 않는다 · 알람 정지(Pr5.10 = 4 · 즉시 정지)가 이미 맡았다 · 모드를 못 읽으면
    끄지 않는다(사람이 만지는 중일 수 있다) · 끄는 것은 「끝나면 서보 끄기」 켠 모터 중 켜진 것.
    """
    cancel = retry_cancel_reason(
        run_mode=run_mode, running=running, in_window=in_window, start_requested=start_requested,
    )
    if cancel:
        return GIVE_UP_CANCEL, cancel
    if run_mode is not None and run_mode != 'schedule':
        return GIVE_UP_KEEP, '운전 모드를 확인할 수 없어 서보를 끄지 않음'
    if int(alarm_grade or 0) > 0:
        return GIVE_UP_KEEP, f'서보 알람 {int(alarm_grade)}등급이라 서보 끄기는 알람 처리에 맡김'
    if int(servo_on_targets) <= 0:
        return GIVE_UP_NOTHING, '끌 서보가 없음(이미 꺼짐 · 모터 설정)'
    return GIVE_UP_SERVO_OFF, ''


def resume_step(
    record: Optional[Dict[str, Any]], now: float, max_age_sec: float = RESUME_MAX_AGE_SEC,
) -> str:
    """저장된 기록으로 무엇을 이어 하나 · 횟수는 기록에 있으니 다시 켜져도 처음부터 세지 않는다"""
    if not isinstance(record, dict):
        return RESUME_NONE
    state = str(record.get('state') or '')
    if state == 'gave_up':
        return RESUME_NOTICE
    if state != 'retrying':
        return RESUME_DROP
    try:
        age = float(now) - float(record.get('updated_at') or 0.0)
        int(record.get('attempts') or 0)
    except (TypeError, ValueError):
        return RESUME_DROP
    if age < 0 or age > max_age_sec:
        return RESUME_DROP
    return RESUME_RETRY


def end_notice(
    state: str, *, attempts: int = 0, reason: str = '', detail: str = '', bad: bool = False,
    max_attempts: int = PARK_ATTEMPTS,
) -> Optional[Dict[str, str]]:
    """화면 「확인할 일」 한 줄 · 풀릴 때까지(다음 시작 · 다음 구간 끝 성공) 남는다"""
    if state == 'retry_wait':
        return {
            'tone': 'warn',
            'title': f'구간 끝 주차 실패 · {attempts}/{max_attempts}회',
            'detail': (
                f'{reason} · 약 1분 뒤 다시 시도합니다. {max_attempts}번 모두 안 되면 '
                '그 자리에서 서보를 끕니다(모터 설정 「끝나면 서보 끄기」 켠 모터만).'
            ),
        }
    if state == 'gave_up':
        if bad:
            return {
                'tone': 'bad',
                'title': '구간 끝 주차 못 함 · 서보가 켜진 채입니다',
                'detail': f'{detail} · {reason}' if detail else reason,
            }
        return {
            'tone': 'warn',
            'title': '구간 끝 주차 못 하고 그 자리에서 서보 끔',
            'detail': (
                f'{reason} · 기준점이 아닌 자세에서 껐습니다. 다음 시작 때 다시 켭니다. '
                '머리를 단 로봇은 처짐을 확인하세요.'
            ),
        }
    return None


class ScheduleEndService:
    def __init__(
        self,
        bridge: Any,
        *,
        fill_active_files: Callable[[Dict[str, Any]], Dict[str, Any]],
        ac_servo_control: Callable[..., Dict[str, Any]],
        dynamixel_torque_control: Callable[..., Dict[str, Any]],
        load_motor_registry: Callable[[], Dict[str, Any]],
        alarm_grade: Callable[[], int],
        run_mode: Optional[Callable[[], str]] = None,
        in_window: Optional[Callable[[], bool]] = None,
        record_event: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        # 브리지의 공개 메서드만 본다 · 속살은 부르는 쪽이 건네준다 (§6-170)
        self.bridge = bridge
        self._fill_active_files = fill_active_files
        self._ac_servo_control = ac_servo_control
        self._dynamixel_torque_control = dynamixel_torque_control
        self._load_motor_registry = load_motor_registry
        self._alarm_grade_reader = alarm_grade
        self._run_mode_reader = run_mode
        # 지금 운영 구간 안인가 · 마스터만 안다(스케줄 노드 상태) · 슬레이브는 늘 False ·
        # 슬레이브는 마스터의 그룹 시작이 `start_blocker` 로 다시 시도를 끊는다
        self._in_window_reader = in_window
        self._record_event = record_event
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        # 다시 시도를 기다리는 동안 시작 요청이 왔다 · 다음 확인에서 그만둔다
        self._start_requested = False
        self._status: Dict[str, Any] = {'state': 'idle', 'message': '', 'updated_at': None}

    # -- 상태 ------------------------------------------------------------ #

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def active(self) -> bool:
        with self._lock:
            return self._status.get('state') in ACTIVE_STATES

    def _set(self, state: str, message: str, **extra: Any) -> None:
        with self._lock:
            self._status = {'state': state, 'message': message, 'updated_at': time.time(), **extra}
        logger = getattr(self.bridge, 'get_logger', None)
        if callable(logger):
            log = logger()
            # rclpy 로거는 **부르는 줄마다 등급 하나** · 한 줄에서 info 뒤 warn 이면
            # 「Logger severity cannot be changed between calls」 로 스레드가 죽었다(수정 목록 137 · 실물 V-24) · 줄을 나눈다
            # 로그가 실패해도 주차 판단 · 다시 시도는 계속 · 상태는 위에서 이미 남겼다(④)
            try:
                if state in {'failed', 'retry_wait', 'gave_up'}:
                    log.warn(f'[스케줄 끝] {message}')
                else:
                    log.info(f'[스케줄 끝] {message}')
            except Exception:  # noqa: BLE001
                pass

    def _event(self, event_type: str, content: str, details: Optional[Dict[str, Any]] = None) -> None:
        """모터 기록(운영 로그)에 한 줄 · 못 써도 주차 판단은 계속 · 수정 목록 131"""
        if self._record_event is None:
            return
        try:
            self._record_event(event_type, content, dict(details or {}))
        except Exception:  # noqa: BLE001 · 기록 실패가 서보 처리를 막지 않는다
            pass

    # -- 설정 ------------------------------------------------------------ #

    def _runtime_dir(self) -> Optional[Path]:
        project_id = self.bridge.project_repository.selected_project_id()
        if not project_id:
            return None
        return Path(self.bridge.workspace_root) / 'motion_projects' / project_id / 'runtime'

    def end_action(self) -> str:
        runtime = self._runtime_dir()
        if runtime is None:
            return DEFAULT_END_ACTION
        try:
            data = json.loads((runtime / 'motion_automation.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return DEFAULT_END_ACTION
        return normalize_end_action(data.get('schedule_end_action') if isinstance(data, dict) else '')

    def _read_json_file(self, name: str) -> Optional[Dict[str, Any]]:
        runtime = self._runtime_dir()
        if runtime is None:
            return None
        try:
            data = json.loads((runtime / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write_json_file(self, name: str, record: Optional[Dict[str, Any]]) -> None:
        runtime = self._runtime_dir()
        if runtime is None:
            return
        path = runtime / name
        if record is None:
            try:
                path.unlink()
            except OSError:
                pass
            return
        try:
            runtime.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass   # 못 쓰면 다시 켜진 뒤 이어 하지 못할 뿐 · 지금 판단은 메모리로 계속

    def _read_powered_off(self) -> Dict[str, List[int]]:
        data = self._read_json_file(STATE_FILE) or {}
        return {
            kind: [int(axis) for axis in data.get(kind) or []]
            for kind in ('ac_servo', 'dynamixel')
        }

    def _write_powered_off(self, record: Optional[Dict[str, Any]]) -> None:
        self._write_json_file(STATE_FILE, record)

    def _write_retry(self, record: Optional[Dict[str, Any]]) -> None:
        self._write_json_file(RETRY_FILE, record)

    # -- 끝 ------------------------------------------------------------- #

    def begin(self) -> Dict[str, Any]:
        """회차 후 정지는 부른 쪽이 이미 보냈다 · 여기는 그 뒤를 맡는다.

        구간 끝 하나에 시도 묶음 하나 · 다시 시도를 기다리는 중이면(스레드가 살아 있다)
        새로 세지 않는다 · 1분마다 오는 스케줄 점검이 횟수를 되돌리지 못하게.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._status)
        action = self.end_action()
        if action == HOLD:
            self._settle('skipped', '운영 종료 · 설정에 따라 서보를 켠 채 마지막 자세에서 정지했습니다')
            return self.status()
        skip = self._skip()
        if skip and skip[0] == 'skipped':
            self._settle(*skip)
            return self.status()
        self._start_requested = False
        if skip:
            # 멈춰 있는데 지금은 주차할 수 없다(알람 · 꺼진 모터 · 모드 못 읽음) · 첫 실패로 센다
            self._write_retry({'state': 'retrying', 'attempts': 1, 'reason': skip[1], 'updated_at': time.time()})
            self._note_failure(1, skip[1])
            self._spawn(1, skip[1])
            return self.status()
        self._set('waiting_cycle', '운영 종료 · 현재 애니메이션을 마무리하는 중')
        self._spawn(0, '')
        return self.status()

    def _settle(self, state: str, message: str) -> None:
        """할 일 없음 · 다만 지난 포기 알림(그 자리에서 끈 서보)은 다음 시작까지 남긴다"""
        with self._lock:
            gave_up = self._status.get('state') == 'gave_up'
        if gave_up:
            logger = getattr(self.bridge, 'get_logger', None)
            if callable(logger):
                logger().info(f'[스케줄 끝] {message} · 지난 주차 못 함 알림은 그대로')
            return
        self._write_retry(None)
        self._set(state, message)

    def resume(self) -> None:
        """브리지가 다시 켜졌다 · 같은 구간 끝의 다시 시도 · 포기 알림을 이어 간다 · 수정 목록 131

        횟수는 파일에 있다 · 몇 번을 다시 켜져도 3번을 넘지 않는다(시도 **전에** 센다).
        """
        record = self._read_json_file(RETRY_FILE)
        step = resume_step(record, time.time())
        if step == RESUME_RETRY:
            attempts = int(record.get('attempts') or 0)
            reason = str(record.get('reason') or '') or '브리지가 다시 시작되어 결과를 모름'
            if attempts <= 0:
                attempts = 1
            self._start_requested = False
            self._note_failure(attempts, reason, log_event=False)
            # 켜진 직후는 모터 상태가 아직 없다 · 횟수를 다 썼어도 먼저 1분 기다린 뒤 판단
            self._spawn(attempts, reason, wait_first=True)
        elif step == RESUME_NOTICE:
            self._set(
                'gave_up', str(record.get('message') or '운영 종료 · 구간 끝 주차 못 함'),
                notice=record.get('notice') if isinstance(record.get('notice'), dict) else None,
            )
        elif step == RESUME_DROP:
            self._write_retry(None)
            self._event('schedule_end_retry_dropped', '구간 끝 주차 다시 시도 기록이 오래되어 버림', record or {})

    def _spawn(self, attempts: int, error: str, *, wait_first: bool = False) -> None:
        with self._lock:
            self._thread = threading.Thread(
                target=self._run, args=(attempts, error, wait_first), name='schedule-end', daemon=True,
            )
            thread = self._thread
        thread.start()

    def _run_mode(self) -> Optional[str]:
        if self._run_mode_reader is None:
            return None
        try:
            return str(self._run_mode_reader() or '')
        except Exception:  # noqa: BLE001 · 못 읽으면 움직이지 않는다
            return ''

    def _in_window(self) -> bool:
        if self._in_window_reader is None:
            return False
        try:
            return bool(self._in_window_reader())
        except Exception:  # noqa: BLE001 · 모르면 구간 밖으로 본다 · 다른 조건이 거른다
            return False

    def _running(self) -> bool:
        """사람이나 그룹이 로봇을 쓰는 중인가 · 로컬 재생 + 그룹 실행"""
        if run_state.is_running(self._motion_state()):
            return True
        try:
            return bool(self.bridge.coordination_execution_blocker())
        except Exception:  # noqa: BLE001
            return False

    def _skip(self) -> Optional[Tuple[str, str]]:
        """주차하지 않을 이유 · 도는 중이면 옛 동작(회차 끝을 기다림) · 멈춰 있으면 지금 볼 수 있는 것을 본다"""
        skip = mode_skip(self._run_mode())
        if skip or run_state.is_running(self._motion_state()):
            return skip
        if self.bridge.coordination_execution_blocker():
            return None   # 그룹 실행이 아직 안 풀렸다 · 회차 끝 기다림과 같은 길
        return idle_park_skip(self._detected_motors(), self._registry_flags(), self._alarm_grade())

    def _run(self, attempts: int, error: str, wait_first: bool = False) -> None:
        """구간 끝 한 번 · 시도 → 실패면 약 1분 뒤 다시 → 세 번째도 실패면 그 자리에서 서보 OFF

        `attempts` = 지금까지 한 시도 · `error` = 막 실패한 이유(있으면 기다렸다 다시) ·
        `wait_first` = 브리지가 다시 켜졌다 · 포기 판단도 1분 기다린 뒤 · 수정 목록 131
        """
        try:
            check_skip = False
            while True:
                if error:
                    if wait_first or after_failure(attempts) == RETRY:
                        wait_first = False
                        cancel = self._wait_retry()
                        if cancel:
                            self._cancel(cancel)
                            return
                    if after_failure(attempts) == GIVE_UP:
                        self._give_up(attempts, error)
                        return
                    check_skip = True   # 첫 시도 뒤에는 멈춰 있는 로봇을 다시 본다
                attempts += 1
                # 시도 **전에** 센다 · 도중에 브리지가 죽어도 다시 켜진 뒤 횟수가 는다(끝없이 돌지 않는다)
                self._write_retry({
                    'state': 'retrying', 'attempts': attempts, 'reason': error, 'updated_at': time.time(),
                })
                state, message = self._attempt(check_skip)
                if state == 'failed':
                    error = message
                    self._note_failure(attempts, error)
                    continue
                self._resolved(attempts, state, message)
                return
        except Exception as exc:  # noqa: BLE001 · 실패는 기록하고 홀드
            message = f'예기치 않은 오류: {exc}'
            self._set(
                'failed', f'운영 종료 · 서보를 끄지 않고 그대로 두었습니다 · {message}',
                notice=end_notice('gave_up', reason=message, detail='구간 끝 주차 중 오류', bad=True),
            )
            self._event('schedule_end_park_failed', f'구간 끝 주차 실패 · {message}', {})

    def _attempt(self, check_skip: bool) -> Tuple[str, str]:
        """한 번 해 본다 · ('done' | 'skipped' | 'failed', 글)"""
        if check_skip:
            if self._start_requested:
                return 'skipped', '운영 종료 · 시작 요청이 들어와 주차하지 않음'
            skip = self._skip()
            if skip:
                return skip
        error = self._park_and_power_off()
        if error:
            return 'failed', error
        return 'done', str(self.status().get('message') or '')

    def _note_failure(self, attempts: int, reason: str, *, log_event: bool = True) -> None:
        last = after_failure(attempts) == GIVE_UP
        tail = '' if last else ' · 약 1분 뒤 다시'
        self._set(
            'retry_wait',
            f'운영 종료 · 구간 끝 주차 실패 · {reason} ({attempts}/{PARK_ATTEMPTS}회{tail})',
            attempts=attempts, reason=reason,
            notice=end_notice('retry_wait', attempts=attempts, reason=reason),
        )
        if log_event:
            self._event(
                'schedule_end_park_failed',
                f'구간 끝 주차 실패 · {reason} ({attempts}/{PARK_ATTEMPTS}회{tail})',
                {'attempts': attempts, 'max_attempts': PARK_ATTEMPTS, 'reason': reason},
            )

    def _wait_retry(self) -> str:
        """약 1분 기다린다 · 시작 요청이 오면 바로 · 그 뒤 그만둘 까닭을 한 번 본다"""
        deadline = self._monotonic() + RETRY_INTERVAL_SEC
        while self._monotonic() < deadline and not self._start_requested:
            self._sleep(RETRY_POLL_SEC)
        return retry_cancel_reason(
            run_mode=self._run_mode(), running=self._running(),
            in_window=self._in_window(), start_requested=self._start_requested,
        )

    def _cancel(self, why: str) -> None:
        """사람이나 스케줄이 로봇을 맡았다 · 다시 시도 · 알림 모두 그만"""
        self._write_retry(None)
        self._set('cancelled', f'운영 종료 · 주차 다시 시도 그만둠 · {why}')
        self._event('schedule_end_retry_cancelled', f'구간 끝 주차 다시 시도 그만둠 · {why}', {'reason': why})

    def _resolved(self, attempts: int, state: str, message: str) -> None:
        self._write_retry(None)
        if state == 'skipped':
            # 다시 볼 때 할 일이 없어졌다(서보가 이미 꺼짐 · 모드 바뀜 …) · 글만 남긴다
            self._set('skipped', message)
            if attempts > 1:
                self._event('schedule_end_retry_cancelled', f'구간 끝 주차 다시 시도 그만둠 · {message}', {})
            return
        if attempts > 1:
            self._event(
                'schedule_end_parked', f'구간 끝 주차 성공 ({attempts}번째 시도) · {message}',
                {'attempts': attempts},
            )

    def _give_up(self, attempts: int, reason: str) -> None:
        """3번 다 못 했다 · 「끝나면 서보 끄기」 켠 모터를 **그 자리에서** 끈다 · 수정 목록 131

        정상 길과 같은 서보 OFF(`_power_off_flagged`) · 끈 모터는 다음 시작 때 다시 켠다.
        처짐 · AC 서보는 브레이크 Pr4.37 = 150 ms(서보 OFF 뒤 브레이크가 물 때까지 버팀)로 막는다 ·
        머리를 단 로봇에서 처짐이 없는지는 아직 실물 미확인(실물 시험 R-21) · 다이나믹셀은 브레이크가
        없어 처질 수 있는 축이면 모터 설정에서 「끝나면 서보 끄기」 를 끈다.
        """
        on_targets = self._servo_on_targets()
        step, why = give_up_step(
            run_mode=self._run_mode(), running=self._running(), in_window=self._in_window(),
            start_requested=self._start_requested, alarm_grade=self._alarm_grade(),
            servo_on_targets=len(on_targets),
        )
        if step == GIVE_UP_CANCEL:
            self._cancel(why)
            return
        if step == GIVE_UP_NOTHING:
            self._write_retry(None)
            self._set('skipped', f'운영 종료 · 주차는 못 했지만 {why} · {reason}')
            self._event('schedule_end_gave_up', f'구간 끝 주차 못 함 · {why} · {reason}', {'reason': reason})
            return
        if step == GIVE_UP_KEEP:
            notice = end_notice('gave_up', reason=reason, detail=why, bad=True)
            message = f'운영 종료 · 주차 못 하고 서보 켠 채 둠 · {why} · {reason}'
            self._finish_give_up(message, notice, attempts, reason)
            self._event('schedule_end_gave_up', f'주차 못 하고 서보 켠 채 둠 · {why} · {reason}', {'reason': reason})
            return
        self._set('powering_off', '운영 종료 · 주차 못 함 · 그 자리에서 서보 끄는 중')
        done, failures, _kept = self._power_off_flagged(only=on_targets)
        if failures:
            notice = end_notice(
                'gave_up', reason=reason,
                detail=f'그 자리에서 서보 끄기 실패 {", ".join(map(str, failures))}번', bad=True,
            )
        else:
            notice = end_notice('gave_up', reason=reason)
        message = (
            '운영 종료 · 주차 못 하고 그 자리에서 서보 끔'
            + _axes_text('AC', done['ac_servo']) + _axes_text('다이나믹셀', done['dynamixel'])
            + (f' · 끄기 실패 {", ".join(map(str, failures))}번' if failures else '')
            + f' · {reason}'
        )
        self._finish_give_up(message, notice, attempts, reason, powered_off=done)
        self._event(
            'schedule_end_servo_off_in_place', f'주차 못 하고 그 자리에서 서보 끔 · {reason}',
            {'reason': reason, 'powered_off': done, 'failures': failures, 'attempts': attempts},
        )

    def _finish_give_up(
        self, message: str, notice: Optional[Dict[str, str]], attempts: int, reason: str, **extra: Any,
    ) -> None:
        # 알림은 다음 시작(또는 다음 구간 끝 성공)까지 · 브리지가 다시 켜져도 남게 파일에
        self._write_retry({
            'state': 'gave_up', 'attempts': attempts, 'reason': reason, 'message': message,
            'notice': notice, 'updated_at': time.time(),
        })
        self._set('gave_up', message, attempts=attempts, reason=reason, notice=notice, **extra)

    def _motion_status(self) -> Dict[str, Any]:
        result = self.bridge.motion_run_status()
        status = result.get('status') if isinstance(result, dict) else {}
        return status if isinstance(status, dict) else {}

    def _motion_state(self) -> str:
        return str(self._motion_status().get('state') or '').strip().lower()

    def _alarm_grade(self) -> int:
        try:
            return int(self._alarm_grade_reader() or 0)
        except (TypeError, ValueError):
            return 0

    def _wait(self, predicate: Callable[[], bool], timeout_sec: float) -> bool:
        deadline = self._monotonic() + timeout_sec
        while True:
            if predicate():
                return True
            if self._monotonic() >= deadline:
                return False
            self._sleep(POLL_SEC)

    def _park_and_power_off(self) -> str:
        # 1 · 지금 회차가 끝날 때까지
        # 오류로 끝나도 기다림은 끝이다 · 끄지는 않는다(아래에서 거른다)
        if not self._wait(
            lambda: self._motion_state() in FINISHED_STATES | {'error', 'blocked'},
            CYCLE_WAIT_SEC,
        ):
            return '회차 종료 대기 시간 초과'
        if not self._wait(lambda: not self.bridge.coordination_execution_blocker(), GROUP_RELEASE_WAIT_SEC):
            return '그룹 재생이 해제되지 않음'
        if self._motion_state() == 'error':
            return '재생이 오류로 끝남'
        if self._alarm_grade() > 0:
            return f'서보 알람 {self._alarm_grade()}등급'

        # 2 · 기준점으로 천천히 · 도달 확인은 초기 위치 이동이 한다
        self._set('parking', f'운영 종료 · 기준점(0°)으로 {PARK_MOVE_SEC:g}초 동안 이동 중')
        payload = self._fill_active_files({
            'initial_mode_override': 'reference',
            'initial_move_time_sec': PARK_MOVE_SEC,
            'request_source': 'schedule_end',
        })
        sent_at = time.time()
        result = self.bridge.motion_run_initialize(payload)
        if not isinstance(result, dict) or result.get('success') is False:
            # 거절 · 예 「실행 컨텍스트 적용 대기」(실물 V-19) · 부른 쪽이 기록하고 1분 뒤 다시 · 수정 목록 131
            message = result.get('message') if isinstance(result, dict) else ''
            return f'기준점 이동 거절 · {message or "응답 없음"}'
        seen: List[str] = []

        def parked() -> bool:
            # 보낸 직후에는 옛 상태(멈춤·초기 위치 완료)가 남아 있다 · **이번** 이동이
            # 끝난 것만 센다 · 단계 시작 시각이 보낸 뒤인가로 가린다
            status = self._motion_status()
            state = str(status.get('state') or '').strip().lower()
            started = max(
                float(status.get('phase_started_at') or 0.0),
                float(status.get('phase_finished_at') or 0.0),   # 오류는 끝난 시각만 있다
            )
            fresh = started >= sent_at - 1.0
            seen.append(state if fresh else '')
            return fresh and state in {'initialized', 'error', 'stopped'}

        if not self._wait(parked, PARK_WAIT_SEC):
            # 이번 이동이 아직 도는 중이면 멈춘다 · 그대로 두면 다음 시도가 「재생이 돌고 있음」 으로
            # 그만두고 서보가 켠 채 남는다 · 수정 목록 131
            if seen and seen[-1] and run_state.is_running(seen[-1]):
                stop = getattr(self.bridge, 'motion_run_stop', None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:  # noqa: BLE001 · 못 멈춰도 실패로 센다
                        pass
            return '기준점 도달 확인 시간 초과'
        if seen[-1] != 'initialized':
            return f'기준점 이동이 끝나지 않음({seen[-1]})'
        if self._alarm_grade() > 0:
            return f'서보 알람 {self._alarm_grade()}등급'

        # 3 · 서보 OFF · 모터별 설정
        self._set('powering_off', '운영 종료 · 기준점 도달 · 서보 끄는 중')
        done, failures, kept = self._power_off_flagged()
        message = (
            '운영 종료 · 기준점 이동 후 서보 OFF '
            + _axes_text('AC', done['ac_servo']) + _axes_text('다이나믹셀', done['dynamixel'])
            + (f' · 켠 채 둠(모터 설정) {", ".join(map(str, kept))}번' if kept else '')
        )
        if failures:
            return message + f' · 끄기 실패 {", ".join(map(str, failures))}번'
        self._set('done', message, powered_off=done)
        return ''

    def _power_off_flagged(
        self, only: Optional[List[int]] = None,
    ) -> Tuple[Dict[str, List[int]], List[int], List[int]]:
        """「끝나면 서보 끄기」 켠 모터를 끈다 · 끈 것은 다음 시작 때 켜려고 적어 둔다 · (끈 것, 실패, 켠 채 둔 것)

        `only` = 이 모터만(그 자리에서 끌 때 · 이미 꺼진 모터는 사람이 끈 것일 수 있어 적지 않는다)
        """
        ac_axes, dxl_axes = self._axes_to_power_off()
        if only is not None:
            ac_axes = [axis for axis in ac_axes if axis in only]
            dxl_axes = [axis for axis in dxl_axes if axis in only]
        done: Dict[str, List[int]] = {'ac_servo': [], 'dynamixel': []}
        failures: List[int] = []
        for axis in ac_axes:
            reply = self._ac_servo_control('servo_off', axis, 'selected')
            (done['ac_servo'] if reply.get('success') else failures).append(axis)
        if dxl_axes:
            reply = self._dynamixel_torque_control('torque_off', dxl_axes)
            if reply.get('success'):
                done['dynamixel'] = list(dxl_axes)
            else:
                failures.extend(dxl_axes)
        if done['ac_servo'] or done['dynamixel']:
            previous = self._read_powered_off()
            merged = {
                kind: sorted(set(previous.get(kind) or []) | set(done[kind]))
                for kind in ('ac_servo', 'dynamixel')
            }
            self._write_powered_off({**merged, 'at': time.time()})
        kept = sorted(set(self._all_axes()) - set(ac_axes) - set(dxl_axes))
        return done, failures, kept

    def _servo_on_targets(self) -> List[int]:
        """「끝나면 서보 끄기」 켠 모터 중 서보가 켜져 있는(꺼짐이 아닌) 것"""
        flags = self._registry_flags()
        return sorted(
            int(motor['controller_index']) for motor in self._detected_motors()
            if motor.get('controller_index') is not None
            and flags.get(int(motor['controller_index']), True)
            and motor.get('servo_on') is not False
        )

    def _registry_flags(self) -> Dict[int, bool]:
        try:
            registry = self._load_motor_registry() or {}
        except Exception:  # noqa: BLE001 · 못 읽으면 기본(끈다)
            return {}
        flags = {}
        for entry in registry.get('motors') or []:
            if isinstance(entry, dict) and entry.get('axis') is not None:
                flags[int(entry['axis'])] = motor_turns_off_at_end(entry)
        return flags

    def _detected_motors(self) -> List[Dict[str, Any]]:
        state = self.bridge.motion_state()
        motors = state.get('motors') if isinstance(state, dict) else []
        return [
            motor for motor in motors or []
            if isinstance(motor, dict) and str(motor.get('state') or '') == 'detected'
        ]

    def _all_axes(self) -> List[int]:
        return [
            int(motor['controller_index']) for motor in self._detected_motors()
            if motor.get('controller_index') is not None
        ]

    def _axes_to_power_off(self) -> tuple[List[int], List[int]]:
        from . import motor_config_rules

        flags = self._registry_flags()
        ac_axes, dxl_axes = [], []
        for motor in self._detected_motors():
            axis = motor.get('controller_index')
            if axis is None or flags.get(int(axis), True) is False:
                continue
            if motor_config_rules.is_ac_servo_motor(motor):
                ac_axes.append(int(axis))
            elif motor_config_rules.is_dynamixel_motor(motor):
                dxl_axes.append(int(axis))
        return sorted(ac_axes), sorted(dxl_axes)

    # -- 다음 시작 ------------------------------------------------------- #

    def _take_over(self) -> None:
        """시작 요청이 왔다 · 다시 시도는 그만 · 포기 알림은 풀린다(끈 서보는 아래에서 다시 켠다) · 수정 목록 131"""
        with self._lock:
            state = self._status.get('state')
            has_notice = bool(self._status.get('notice'))
            if state == 'retry_wait':
                self._start_requested = True   # 기다리던 스레드가 다음 확인에서 그만둔다
        if state == 'retry_wait' or has_notice:
            self._write_retry(None)
            self._set('idle', '운영 종료 · 시작 요청이 들어와 주차 다시 시도 · 알림을 거둠')

    def start_blocker(self) -> str:
        """시작 전에 부른다 · 주차 중이면 막고 · 여기서 끈 모터는 켜고 확인한다."""
        if self.active():
            return '운영 종료 동작(기준점 이동 → 서보 OFF)이 진행 중입니다. 끝난 뒤 다시 시도하세요'
        self._take_over()
        record = self._read_powered_off()
        ac_axes = record.get('ac_servo') or []
        dxl_axes = record.get('dynamixel') or []
        if not ac_axes and not dxl_axes:
            return ''
        for axis in ac_axes:
            reply = self._ac_servo_control('servo_on', axis, 'selected')
            if reply.get('success') is False:
                return f'운영 종료 때 끈 {axis}번 모터의 서보를 켜지 못했습니다 · {reply.get("message") or ""}'
        if dxl_axes:
            reply = self._dynamixel_torque_control('torque_on', dxl_axes)
            if reply.get('success') is False:
                return f'운영 종료 때 끈 다이나믹셀 토크를 켜지 못했습니다 · {reply.get("message") or ""}'

        def servos_on() -> bool:
            by_axis = {
                int(motor['controller_index']): motor for motor in self._detected_motors()
                if motor.get('controller_index') is not None
            }
            return all(bool((by_axis.get(axis) or {}).get('servo_on')) for axis in ac_axes)

        if not self._wait(servos_on, SERVO_ON_WAIT_SEC):
            return '운영 종료 때 끈 서보가 켜지지 않았습니다. 모터 상태를 확인하세요'
        self._write_powered_off(None)
        self._set('idle', '운영 종료 때 끈 서보를 다시 켰습니다', restored={'ac_servo': ac_axes, 'dynamixel': dxl_axes})
        return ''


def _axes_text(label: str, axes: List[int]) -> str:
    return f' · {label} {", ".join(map(str, axes))}번' if axes else ''
