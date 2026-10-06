"""스케줄이 끝나면 · 기준점 주차 → 서보 OFF · 수정 목록 36 (2026-10-06)

전에는 운영 시간이 끝나면 「현재 회차 후 정지」 만 했다 · 애니메이션 마지막
프레임 자세에서 서보가 켜진 채 밤새 서 있었다(발열·전력·사람이 만지면 버팀).

이제 이 PC 의 프로젝트 설정(`schedule_end_action`)을 따른다.

    park_servo_off (기본)   지금 애니 마무리 → 기준점(조인트 0°)으로 천천히 →
                            도달 확인 → AC 서보 OFF(브레이크) · 다이나믹셀 토크 OFF
    hold                    옛 동작 · 마지막 자세에서 서보 켠 채 정지

모터별로 「끝나면 서보 OFF」 를 끌 수 있다 (모터 설정 `config.schedule_end_servo_off`).

**주차가 안 되면 끄지 않는다** · 알람·오류·도달 실패·시간 초과면 홀드 + 기록.
**다음 시작** · 여기서 끈 모터만 기억해 두었다가 시작(스케줄·수동·그룹 준비) 전에
켜고 켜진 것을 확인한다 · 사람이 손으로 끈 모터는 건드리지 않는다.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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


def normalize_end_action(value: Any) -> str:
    text = str(value or '').strip().lower()
    return text if text in END_ACTIONS else DEFAULT_END_ACTION


def motor_turns_off_at_end(entry: Dict[str, Any]) -> bool:
    """모터별 「끝나면 서보 OFF」 · 안 적었으면 켬(끈다) · AC·다이나믹셀 같은 규칙"""
    config = entry.get('config') if isinstance(entry.get('config'), dict) else {}
    return config.get('schedule_end_servo_off') is not False


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
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status: Dict[str, Any] = {'state': 'idle', 'message': '', 'updated_at': None}

    # -- 상태 ------------------------------------------------------------ #

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def active(self) -> bool:
        with self._lock:
            return self._status.get('state') in {'waiting_cycle', 'parking', 'powering_off'}

    def _set(self, state: str, message: str, **extra: Any) -> None:
        with self._lock:
            self._status = {'state': state, 'message': message, 'updated_at': time.time(), **extra}
        logger = getattr(self.bridge, 'get_logger', None)
        if callable(logger):
            log = logger()
            (log.warn if state == 'failed' else log.info)(f'[스케줄 끝] {message}')

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

    def _read_powered_off(self) -> Dict[str, List[int]]:
        runtime = self._runtime_dir()
        if runtime is None:
            return {}
        try:
            data = json.loads((runtime / STATE_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            kind: [int(axis) for axis in data.get(kind) or []]
            for kind in ('ac_servo', 'dynamixel')
        }

    def _write_powered_off(self, record: Optional[Dict[str, Any]]) -> None:
        runtime = self._runtime_dir()
        if runtime is None:
            return
        path = runtime / STATE_FILE
        if record is None:
            try:
                path.unlink()
            except OSError:
                pass
            return
        runtime.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')

    # -- 끝 ------------------------------------------------------------- #

    def begin(self) -> Dict[str, Any]:
        """회차 후 정지는 부른 쪽이 이미 보냈다 · 여기는 그 뒤를 맡는다."""
        action = self.end_action()
        if action == HOLD:
            self._set('skipped', '스케줄 끝 · 설정이 「서보 유지」 · 마지막 자세에서 정지')
            return self.status()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._status)
            self._thread = threading.Thread(target=self._run, name='schedule-end', daemon=True)
        self._set('waiting_cycle', '스케줄 끝 · 지금 애니메이션을 마무리하는 중')
        self._thread.start()
        return self.status()

    def _run(self) -> None:
        try:
            error = self._park_and_power_off()
        except Exception as exc:  # noqa: BLE001 · 실패는 기록하고 홀드
            error = f'예기치 않은 오류: {exc}'
        if error:
            self._set('failed', f'스케줄 끝 · 서보를 끄지 않고 그대로 둠 · {error}')

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
            return '회차가 끝나기를 기다리다 시간 초과'
        if not self._wait(lambda: not self.bridge.coordination_execution_blocker(), GROUP_RELEASE_WAIT_SEC):
            return '그룹 실행이 풀리지 않음'
        if self._motion_state() == 'error':
            return '재생이 오류로 끝남'
        if self._alarm_grade() > 0:
            return f'Servo 알람 {self._alarm_grade()}등급'

        # 2 · 기준점으로 천천히 · 도달 확인은 초기 위치 이동이 한다
        self._set('parking', f'스케줄 끝 · 기준점(0°)으로 {PARK_MOVE_SEC:g}초 동안 이동')
        payload = self._fill_active_files({
            'initial_mode_override': 'reference',
            'initial_move_time_sec': PARK_MOVE_SEC,
            'request_source': 'schedule_end',
        })
        sent_at = time.time()
        result = self.bridge.motion_run_initialize(payload)
        if result.get('success') is False:
            return f'기준점 이동 시작 실패 · {result.get("message") or "응답 없음"}'
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
            return '기준점 도달 확인 시간 초과'
        if seen[-1] != 'initialized':
            return f'기준점 이동이 끝나지 않음({seen[-1]})'
        if self._alarm_grade() > 0:
            return f'Servo 알람 {self._alarm_grade()}등급'

        # 3 · 서보 OFF · 모터별 설정
        self._set('powering_off', '스케줄 끝 · 기준점 도달 · 서보 OFF')
        ac_axes, dxl_axes = self._axes_to_power_off()
        done: Dict[str, List[int]] = {'ac_servo': [], 'dynamixel': []}
        failures = []
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
            self._write_powered_off({**done, 'at': time.time()})
        kept = sorted(set(self._all_axes()) - set(ac_axes) - set(dxl_axes))
        message = (
            '스케줄 끝 · 기준점 주차 · 서보 OFF '
            + _axes_text('AC', done['ac_servo']) + _axes_text('다이나믹셀', done['dynamixel'])
            + (f' · 켠 채 둠(모터 설정) {", ".join(map(str, kept))}번' if kept else '')
        )
        if failures:
            return message + f' · 끄기 실패 {", ".join(map(str, failures))}번'
        self._set('done', message, powered_off=done)
        return ''

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

    def start_blocker(self) -> str:
        """시작 전에 부른다 · 주차 중이면 막고 · 여기서 끈 모터는 켜고 확인한다."""
        if self.active():
            return '스케줄 끝 동작(기준점 주차 → 서보 OFF) 중입니다 · 끝난 뒤 다시'
        record = self._read_powered_off()
        ac_axes = record.get('ac_servo') or []
        dxl_axes = record.get('dynamixel') or []
        if not ac_axes and not dxl_axes:
            return ''
        for axis in ac_axes:
            reply = self._ac_servo_control('servo_on', axis, 'selected')
            if reply.get('success') is False:
                return f'스케줄 끝에 끈 {axis}번 모터 서보를 켜지 못했습니다 · {reply.get("message") or ""}'
        if dxl_axes:
            reply = self._dynamixel_torque_control('torque_on', dxl_axes)
            if reply.get('success') is False:
                return f'스케줄 끝에 끈 다이나믹셀 토크를 켜지 못했습니다 · {reply.get("message") or ""}'

        def servos_on() -> bool:
            by_axis = {
                int(motor['controller_index']): motor for motor in self._detected_motors()
                if motor.get('controller_index') is not None
            }
            return all(bool((by_axis.get(axis) or {}).get('servo_on')) for axis in ac_axes)

        if not self._wait(servos_on, SERVO_ON_WAIT_SEC):
            return '스케줄 끝에 끈 서보가 켜지지 않았습니다 · 모터 상태를 확인하세요'
        self._write_powered_off(None)
        self._set('idle', '스케줄 끝에 끈 서보를 다시 켬', restored={'ac_servo': ac_axes, 'dynamixel': dxl_axes})
        return ''


def _axes_text(label: str, axes: List[int]) -> str:
    return f' · {label} {", ".join(map(str, axes))}번' if axes else ''
