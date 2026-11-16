"""시간표 재생 · 이 PC 혼자 시간표대로 재생 · 수정 목록 186 (2026-11-09)

사용자 결정(설계 2-3 · 7장) · 마스터 신호 없이 각 PC 가 시간표의 회차 시각에 스스로 초기 이동 → 재생.

- 회차 하나 = 시각이 박힌 명령 하나(`group_cycle_at` · 「k 회차를 T 에 시작 · 다음 회차 N」) · 초기 이동 시작
  (T − 이 PC 실제 초기 이동 − 여유 `timed_cycle.INITIAL_MOVE_SETTLE_SEC`)과 시작을 로컬 재생 관리자가 제 시계로 ·
  여기는 보내고 결과만 본다 · 수정 목록 206 · 실행 번호 = 시간표 이름(모든 PC 같음)
  전에는 초기 이동 예약(`group_initialize_at`)을 보내고 로컬 상태로 끝을 본 뒤 시작 예약(`group_start_at`)을 따로
  보냈다 · 그 왕복이 시작 여유를 먹어 188 ⑥ 이 여유를 2 → 4 s 로 늘렸다
- 초기 이동이 늦게 끝나면 그 PC 만 끝나는 대로 늦게 시작(쉼 아님 · 늦음 기록 · 다음 회차는 다시 시간표대로) ·
  너무 늦어 다음 회차 준비를 먹을 때만 재생 관리자가 그 회차를 쉰다(`group_cycle_skipped` · 이유 기록) ·
  사용자 결정 2026-11-16 · 다른 PC · 스피커는 기다리지 않는다
- 1회차는 처음 준비(`group_prepare`) · 2회차부터 들어가는 PC(재부팅 · 늦게 켬 · 쉬었다 옴)는 복귀 길
  (`group_join` · 회차 명령이 합류 확정을 겸함)로 「앞 회차를 끝낸 것처럼」 서서 그 회차 초기 위치로 간다 · 그래서
  로컬 회차 번호 · 재생 목록 순서가 시간표와 같다 · 들어가는 명령과 첫 회차 명령은 같은 틱에
- 회차 중간 합류 없음 · 준비가 늦으면 그 회차는 쉬고 다음 경계 · **이 PC 만**(다른 PC 는 그대로)
- 회차 끝(장벽) · 다음 회차가 시간표에 있으면 그 회차 명령 · 없으면(운영시간 끝 · 회차 후 정지) 놓는다 ·
  운영시간 끝이면 기준점 주차 → 서보 OFF(평소 운영 종료와 같음)
- 사람의 즉시 정지 · 이 PC 가 그 시간표를 쥐고 있으면 바로 정지

판단에 시간 짐작을 쓰지 않는다 · 수정 목록 199 · 201 · 205
- 로컬 상태는 보낸 명령의 응답 표시(`status_stamp`) 이상일 때만 그 명령 뒤의 상태로 읽는다 · 그 앞 상태로는 아무것도
  정하지 않는다(옛 3 s 기다림 `STATUS_GRACE_SEC`) · 회차 끝 장벽 전 틈도 끝난 상태가 아니다(옛 5 s 확인 `ENDED_CONFIRM_SEC`)
- 그룹 정지로 선 PC 의 주차는 그 운영시간 끝 시각에(옛 「2분 못 보면 잊음」 `STOPPED_FORGET_SEC`)
- 초기 이동 시간은 묶음에 정한 값 → 이 PC 조인트 매핑 값 → 모르면 가장 긴 선택지(`motion_common.timing`)
- 남은 시간 기준 · 응답 표시가 끝내 안 오는 것(`ECHO_TIMEOUT_SEC`)은 실패 감지만 · 회차 시각 · 운영시간 끝은 시간표 자체

로컬 웹 호출(`control`)만 한다 · ROS 를 모른다 · 시험은 가짜 재생 관리자로.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable, Dict, Mapping, Optional

from motion_common.repeat_policy import GROUP_LOCKSTEP
from motion_common.run_state import GROUP_CYCLE_FINISHING_PHASE, GROUP_CYCLE_SKIPPED_PHASE, status_stamp
from motion_common.timing import initial_move_sec

from . import clock_grid
from .timetable import MANUAL_MODE, OFF_MODE, Choice

#: 시간표 실행 번호 머리 · `clock_grid.schedule_plan_id`
PLAN_PREFIX = 'tt-'
SCHEDULE_PREFIX = 'tt-s'
#: 회차 끝 장벽 단계 · 로컬 재생 관리자 · 연동 노드 `_BARRIER_PHASES`(신호 재생) + 재생 관리자가 쉰 회차(시간표만 ·
#: 그 회차를 끝낸 것처럼 서서 다음 회차 명령을 기다림 · 수정 목록 206)
BARRIER_PHASES = frozenset({'group_motion_completed', 'group_join_committed', GROUP_CYCLE_SKIPPED_PHASE})
#: 노드가 다시 떴을 때 이어받는 로컬 단계 · 회차 재생 중 · 회차 끝(장벽 전 틈 · 장벽) · 수정 목록 199 ·
#: 회차 명령(`timed_cycle`)을 쥔 재생 관리자는 어느 단계든(초기 이동 · 시작 대기) · 206
_ADOPT_STATES = frozenset({'running', 'verifying', 'start_scheduled'})
_ADOPT_PHASES = BARRIER_PHASES | {GROUP_CYCLE_FINISHING_PHASE}
#: 회차가 시작된(시작 시각을 기다리는 중 포함) 로컬 단계 · 따를 시간표가 바뀌어도 이 회차는 끝까지 · 그 전(준비 · 초기
#: 이동)이면 바로 놓는다 · 전에는 시작 예약을 보낸 뒤(`stage == 'scheduled'`)로 갈랐다 · 수정 목록 206
_CYCLE_BEGUN_STATES = frozenset({'running', 'verifying', 'start_scheduled'})
_CYCLE_BEGUN_PHASES = frozenset({'group_start_scheduled', GROUP_CYCLE_FINISHING_PHASE})
#: 끝난 로컬 실행 · 실행 번호가 남아 있어도 쥔 것으로 보지 않는다 · 수정 목록 188
#: 실제 재생 관리자는 정지 · 완료 뒤에도 `group_execution` 과 그 번호를 남긴다 · 전에는 그것을 「다른 재생 중」 으로 보고
#: 회차마다 쉬었다(실물 NY 2026-11-09 03:49 · 신호 재생 그룹을 즉시 정지하고 시간표 재생으로 바꾼 뒤 4대 모두 7회차 쉼)
_FINISHED_STATES = frozenset({'', 'idle', 'ready', 'stopped', 'completed'})


#: 그룹 실행이 아닌 로컬 재생이 「돌고 있는」 상태 · 연동 노드 `_SOLO_BUSY_STATES` + 준비 · 예약 · 정지 중 · 수정 목록 189
_SOLO_BUSY_STATES = frozenset({
    'preparing', 'initializing', 'running', 'verifying', 'waiting', 'recovering', 'stopping', 'armed', 'start_scheduled',
})


#: 시작 전에 멈춘 옛 그룹 실행(신호 재생) · 연동 노드에 그 실행이 없는데 로컬만 쥐고 있으면 끝내기(취소)를 놓친 것 ·
#: 시간표 준비 때 정리하고 들어간다 · 도는 재생(`running` · 회차 사이 `waiting`)은 손대지 않는다 · 수정 목록 193 ④
_STALE_GROUP_STATES = frozenset({'preparing', 'armed', 'initialized', 'start_scheduled'})


def _stale_group(held: str, state: str, status: Mapping[str, Any]) -> bool:
    """끝내기를 놓친 옛 그룹 실행인가 · 시간표 실행(`tt-`)이 아니고 시작 전 상태"""
    return bool(
        held and not held.startswith(PLAN_PREFIX) and status.get('group_execution')
        and state in _STALE_GROUP_STATES
    )


def _occupied(held: str, state: str, status: Mapping[str, Any]) -> bool:
    """이 PC 가 다른 실행을 하고 있는가 · 시간표 회차에 못 들어간다

    그룹 실행은 실행 번호(`held` · 끝난 것은 빈 값)로 · 단독 재생은 도는 상태로만 본다. 끝난 단독 초기화
    (`initialized`) 는 아무것도 돌지 않는다 · 운영 종료(schedule_end)가 기준점 이동 → 서보 OFF 를 한 뒤 4대 모두
    그 상태로 남아 다음 운영 1회차부터 매 회차 「다른 재생 중」 으로 쉬었다 · 서보 복구도 준비 길 안에만 있어
    서보 OFF 그대로(실물 NY 2026-11-09 08:31) · 수정 목록 189
    """
    if held:
        return True
    return not status.get('group_execution') and state in _SOLO_BUSY_STATES


_SERVO_OFF = re.compile(r'(\d+)번 모터 서보가 꺼져 있습니다')


def servo_off_reason(message: str) -> str:
    """로컬 준비 검사 실패가 서보 꺼짐뿐이면 짧은 이유 · 「서보가 꺼져 있습니다(0~4번 모터)」 · 아니면 '' · 수정 목록 197

    재생 관리자 글 · 「그룹 모션 실행 실패: Motion ID f2_neck_pitch: 0번 모터 서보가 꺼져 있습니다; …」 · 조인트마다
    `;` 로 이어진다 · 알람 · 감지 안 됨 같은 다른 이유가 하나라도 섞이면 오류 그대로 둔다.
    """
    parts = [part.strip() for part in str(message or '').split(';') if part.strip()]
    if not parts:
        return ''
    axes = set()
    for part in parts:
        found = _SERVO_OFF.findall(part)
        if not found:
            return ''
        axes.update(int(axis) for axis in found)
    return f'서보가 꺼져 있습니다({_axis_ranges(sorted(axes))}번 모터)'


def _axis_ranges(axes) -> str:
    """[0, 1, 2, 4] → 「0~2, 4」"""
    runs = []
    for axis in axes:
        if runs and axis == runs[-1][1] + 1:
            runs[-1][1] = axis
        else:
            runs.append([axis, axis])
    return ', '.join(str(a) if a == b else f'{a}~{b}' for a, b in runs)


class ClockDriver:
    """시간표 하나를 이 PC 에서 돌린다 · 연동 노드가 0.1 s 마다 `tick`"""

    #: 계획 짓기 여유 · 재생 목록 전부 · 들어가기 → 초기 이동 시작 · 쉬던 PC 가 다음 회차에 들어갈 수 있는지 가른다
    #: NY 실측 2026-11-16(test/root-fix) · 920 s × 20 조인트 첫 변환 최대 1.4 s(재샘플 1.0 s) · 변환본이 있으면 17~27 ms
    #: (208) · 45 → 10 s(사용자 2026-11-16) · 920 s 짜리 목록 7개까지 첫 변환이 들어감(복귀 길은 목록 전부를 짓고
    #: 「복귀 준비」) · 모자라도 회차를 쉬지 않고 늦게 시작(재생 관리자가 정함 · 206) · 너무 늦을 때만 쉼
    BUILD_SEC = 10.0
    #: 초기 이동 끝 → 재생 시작 사이 · 자동 주기에도 들어간다(`clock_grid.auto_period`) · 2 → 4 → 1 s · 수정 목록 188 · 206 ·
    #: 여기서는 들어갈 때 필요한 시간(`prep`)과 1회차 준비의 초기 이동 짐작에만 쓴다 · 실제 초기 이동 시각은 재생 관리자가 셈
    MARGIN_SEC = clock_grid.CYCLE_START_LEAD_SEC
    #: 실행을 잡는 시점 · 준비 시간 + 이만큼 전부터 · 그 전에는 로컬 실행을 잡지 않는다(사람 조작 가능)
    ENTER_WINDOW_SEC = 30.0
    #: 실패 감지만 · 보낸 명령 뒤의 로컬 상태(응답 표시 이상)가 이만큼 안 오면 재생 관리자 · 웹이 멈춘 것 · 회차를 놓는다 ·
    #: 재생 관리자는 상태를 0.5 s 마다 내고 웹은 응답의 상태를 바로 들고 있으므로 정상이면 다음 틱에 온다 · 수정 목록 199
    ECHO_TIMEOUT_SEC = 10.0
    #: 웹이 「서보 켜는 중」(`pending`)이라 답한 뒤 다시 묻는 간격 · 웹은 기다리지 않고 바로 답한다 · 수정 목록 217 ·
    #: 전에는 웹이 서보를 다 켤 때까지(최대 5 s) 이 노드가 HTTP 를 쥐고 기다려(한도 4 s) 실행기 전체가 2~4 s 섰다(NY 2026-11-16)
    PENDING_POLL_SEC = 0.5
    #: 즉시 정지한 시간표 · 정지가 풀릴 때까지 건너뜀 · 수정 목록 188
    _STOPPED_SKIP = 10 ** 9

    def __init__(
        self,
        control: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        *,
        info: Callable[[str], None],
        warn: Callable[[str], None],
        finish: Optional[Callable[[str, bool, str], None]] = None,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        self._control = control
        self._info = info
        self._warn = warn
        self._finish = finish
        self._wall = wall
        self._mono = mono
        self._run: Optional[Dict[str, Any]] = None
        #: 이 시간표의 이 회차까지는 다시 잡지 않는다(실패 · 쉼) · (plan_id, 회차)
        self._skip: tuple = ('', 0)
        #: 웹이 서보를 켜는 중 · 이 시각(단조) 전에는 준비 명령을 다시 보내지 않는다 · 수정 목록 217
        self._pending_until_m = 0.0
        #: 「켜는 중」 을 받은 회차 · (plan_id, 회차) · 들어갈 때를 넘기면 쉼으로 남긴다
        self._pending_slot: Optional[tuple] = None
        self._note = ''
        #: 회차를 쉬며 띄운 이유 · 다음 들어갈 때까지 화면에 남긴다 · 수정 목록 189
        self._skip_note = ''
        #: 마지막으로 경고 로그를 남긴 쉼 · (plan_id, 회차, 이유) · 같은 회차는 한 줄 · 수정 목록 189
        self._skip_logged: tuple = ('', 0, '')
        self._next_start_unix = 0.0
        #: 사람 그룹 정지로 선 스케줄 시간표 · 그 운영시간이 끝나면 주차 → 서보 OFF 한 번 · 수정 목록 193
        self._stopped_window = ''
        #: 그 운영시간 끝(유닉스 초) · 정지가 안 보여도(마스터 수동 · 끊김) 이 시각에 주차 · 0 = 모름 · 수정 목록 201
        self._stopped_until = 0.0
        #: 옛 그룹 실행을 정리한 번호 · 같은 실행은 한 번만 보낸다 · 수정 목록 193 ④
        self._stale_cancelled = ''
        #: 마지막으로 놓은(취소 · 정지) 명령 응답의 상태 표시 · 그보다 앞 상태로는 이어받거나 들어가지 않는다 · 수정 목록 199
        self._released_ack = 0.0
        #: 재생 관리자가 알린 회차 결과(늦게 시작) 를 기록한 회차 · (plan_id, 회차) · 회차마다 한 줄 · 수정 목록 206
        self._late_logged: tuple = ('', 0)
        #: 그 결과로 띄운 화면 글 · 다음 회차가 제때 시작하면 지운다
        self._result_note = ''

    # ------------------------------------------------------------------ #

    def report(self) -> Dict[str, Any]:
        """하트비트 · 화면용 · 지금 쥔 시간표 · 단계 · 회차 · 다음 시작 · 쉬는 이유"""
        run = dict(self._run or {})
        return {
            'plan_id': str(run.get('plan_id') or ''),
            'stage': str(run.get('stage') or 'idle'),
            'cycle': int(run.get('cycle') or 0),
            'next_start_unix': float(run.get('start_unix') or self._next_start_unix or 0.0),
            'note': self._note,
        }

    @property
    def holding(self) -> str:
        return str((self._run or {}).get('plan_id') or '')

    def belongs(self, status: Mapping[str, Any]) -> bool:
        """이 로컬 상태가 쥔 실행에 보낸 마지막 명령 뒤의 것인가 · 쥔 실행이 없으면 참 · 수정 목록 199"""
        run = self._run
        return run is None or self._belongs(run, status)

    @staticmethod
    def _belongs(run: Mapping[str, Any], status: Mapping[str, Any]) -> bool:
        """재생 관리자 상태 표시(바뀔 때마다 · 단조 시계) ≥ 명령 응답의 표시 · 응답에 표시가 없으면(옛 재생 관리자) 거르지 않는다

        로컬 상태는 50 ms 마다 웹을 거쳐 읽는다 · 웹은 응답의 상태를 바로 들지만 그 앞에 나간 상태 토픽이 뒤늦게 덮을 수
        있다 · 그래서 명령 바로 뒤 몇 틱은 그 앞 상태(다른 실행 · 앞 시도의 정지 · 오류)가 보인다 · 전에는 3 s 동안 봐주고
        그 뒤에는 그대로 믿었다 · 오류는 봐주지도 않아 앞 시도의 오류로 새 시도를 바로 접을 수 있었다.
        """
        ack = float(run.get('ack') or 0.0)
        return ack <= 0.0 or status_stamp(status) >= ack

    def _note_ack(self, run: Dict[str, Any], result: Mapping[str, Any], now_m: float) -> None:
        """명령이 받아졌다 · 그 응답의 상태 표시를 「이 뒤의 상태만 읽는다」 기준으로 · 응답 기다림 시작(실패 감지)"""
        stamp = status_stamp(result.get('status') if isinstance(result, Mapping) else None)
        run['ack'] = max(float(run.get('ack') or 0.0), stamp)
        run['sent_m'] = now_m

    def _note_release(self, result: Any) -> None:
        """쥔 실행을 놓는 명령(취소 · 정지)의 응답 표시 · 그 앞 상태에 남은 같은 실행을 다시 이어받지 않게 · 수정 목록 199"""
        stamp = status_stamp(result.get('status') if isinstance(result, Mapping) else None)
        self._released_ack = max(self._released_ack, stamp)

    def tick(self, choice: Choice, view: Mapping[str, Any]) -> None:
        """`view` · status(로컬 재생 상태) · init_sec(이 PC 조인트 매핑 초기 이동 · 로컬 상태 `initial_move_sec`) ·
        start_blocker · initial_move_time_sec(묶음에 정한 값 · 0 = PC 마다) · operation_mode(이 PC 운전 모드)"""
        status = view.get('status') if isinstance(view.get('status'), Mapping) else {}
        timeline = choice.timeline
        run = self._run
        now_w, now_m = self._wall(), self._mono()
        held = str(status.get('execution_id') or '') if status.get('group_execution') else ''
        phase = str(status.get('phase') or '')
        state = str(status.get('state') or '')
        # 끝난 실행의 번호는 이어받지도 · 「다른 재생 중」 으로 보지도 않는다 · 수정 목록 188
        live = held if state not in _FINISHED_STATES else ''
        skip_plan, skip_cycle = self._skip
        if skip_plan and skip_cycle >= self._STOPPED_SKIP and choice.stopped_plan_id != skip_plan:
            # 즉시 정지가 풀렸다(스케줄이 다시 시작) · 다음 경계부터 다시 들어간다 · 전에는 그 시간표를 그날 끝까지
            # 건너뛰어 정지한 PC 들만 서 있었다(실물 NY 2026-11-09 05:55 · 시험 4 뒤 floating1 · 3 · 4) · 수정 목록 188
            self._skip = ('', 0)
            if self._note == '정지됨':
                self._note = ''

        if run is None and status_stamp(status) < self._released_ack:
            # 방금 놓은(취소 · 정지) 실행의 그 앞 상태가 아직 보인다 · 그것으로 이어받거나 「다른 재생 중」 으로 보지 않는다 ·
            # 전에는 다음 틱에 그 실행을 「남아 있던 실행」 으로 다시 잡고 한 번 더 취소하며 쉰 이유를 덮었다 · 수정 목록 199
            return
        if run is None and live.startswith(PLAN_PREFIX):
            # 이 노드가 다시 떴다(워치독 · 업데이트) · 로컬 재생 관리자는 시간표 실행을 계속 돌고 있다 · 이어받는다
            run = self._adopt(live, phase, state, status, timeline, now_m)
            if run is None:
                return
        if run is not None:
            self._drive_run(run, choice, status, held, phase, state, now_w, now_m, view)
            return
        if self._park_stopped_window(choice, view, now_w):
            return
        self._maybe_enter(timeline, choice, view, status, live, state, now_w, now_m)

    def _drive_run(self, run, choice: Choice, status, held: str, phase: str, state: str, now_w: float, now_m: float, view) -> None:
        """쥔 실행 하나 · 사람 정지(로컬 상태와 상관없이 바로) → 내 명령 뒤의 로컬 상태로만 나머지 판단"""
        timeline = choice.timeline
        if (
            choice.halt_plan_id and choice.halt_plan_id == run['plan_id']
            and float(run.get('entered_unix') or 0.0) < float(choice.halt_at_unix or 0.0)
            and not (choice.stopped_plan_id and choice.stopped_plan_id == run['plan_id'])
        ):
            # 이 실행을 잡은 뒤 즉시 정지가 있었다 · 정지는 이미 지워졌다(스케줄이 다시 시작) · 끊겨서 못 받은 것 ·
            # 다른 PC 는 이미 섰다 · 바로 세우고 다음 경계에 같이 들어간다 · 수정 목록 188
            result = self._control({
                'command': 'stop_now',
                'execution_id': run['plan_id'],
                'network_operation_id': f'tt-halt-{uuid.uuid4().hex}',
            })
            self._note_release(result)
            self._info(f'시간표 재생 · 놓친 즉시 정지 · {run["plan_id"]} · {result.get("message") or ""}')
            self._skip = (run['plan_id'], int(run.get('cycle') or 0))
            self._run = None
            self._set_note('놓친 즉시 정지 · 다음 경계', warn=True)
            return
        if choice.stopped_plan_id and choice.stopped_plan_id == run['plan_id']:
            result = self._control({
                'command': 'stop_now',
                'execution_id': run['plan_id'],
                'network_operation_id': f'tt-stop-{uuid.uuid4().hex}',
            })
            self._note_release(result)
            self._info(f'시간표 재생 · 즉시 정지 · {run["plan_id"]} · {result.get("message") or ""}')
            self._skip = (run['plan_id'], self._STOPPED_SKIP)
            self._run = None
            self._note = '정지됨'
            return
        if not self._belongs(run, status):
            # 보낸 명령이 아직 로컬 상태에 안 보인다 · 그 앞 상태(다른 실행 · 앞 시도의 정지 · 오류)로는 아무것도 정하지
            # 않는다 · 전에는 3 s(`STATUS_GRACE_SEC` · 162) 동안만 봐주고 그 뒤에는 그 앞 상태로 「끝남」 을 정했다 · 수정 목록 199
            if now_m - float(run.get('sent_m') or 0.0) > self.ECHO_TIMEOUT_SEC:
                # 실패 감지만 · 재생 관리자 · 웹이 멈췄다(정상이면 다음 틱에 온다)
                self._cancel(
                    run,
                    f'{run["cycle"]}회차 쉼 · 로컬 상태가 명령 뒤로 바뀌지 않음'
                    f'({self.ECHO_TIMEOUT_SEC:.0f} s · 웹 · 재생 관리자 응답 없음)',
                )
            return
        if held != run['plan_id']:
            # 로컬 실행이 사라졌다(오류 · 누가 세움 · 재생 관리자 재시작) · 이 회차는 쉬고 다음 경계
            self._drop(f'{run["cycle"]}회차 로컬 실행이 끝남 · {status.get("message") or state or "상태 없음"}')
            return
        if state == 'error':
            servo_off = servo_off_reason(str(status.get('message') or ''))
            if servo_off:
                # 사람이 세우고 서보를 끈 PC · 들어가기는 받아졌다가 로컬 준비 검사에서 걸림 · 쉰 것이지 오류가 아니다 ·
                # 전에는 「N회차 오류 · 그룹 모션 실행 실패: Motion ID …」 로 축마다 긴 글이 남았다(NY 2026-11-12 00:32) ·
                # 수정 목록 197
                self._cancel(run, f'{run["cycle"]}회차 쉼 · {servo_off}')
            else:
                self._cancel(run, f'{run["cycle"]}회차 오류 · {status.get("message") or ""}')
            return
        if run.get('cycle_failed'):
            # 회차 명령이 거절됐고 로컬 상태도 오류가 아니다 · 이 회차를 놓고 다음 경계 · 수정 목록 206
            self._cancel(run, str(run['cycle_failed']))
            return
        if timeline is None or timeline.plan_id != run['plan_id']:
            self._leave_when_safe(run, phase, state, choice)
            return
        if state in _FINISHED_STATES and phase not in BARRIER_PHASES:
            # 로컬 실행이 같은 번호로 끝났다(사람이 이 PC 만 정지 · `stopped`) · 번호가 남아 위의 「사라짐」 에 안 걸리고
            # 회차 끝 장벽도 아니라 매 틱 그대로 쥐고 있었다 → 그 운영시간 끝까지 안 돌아옴(실물 NY 2026-11-11 00:02 ·
            # f2 A2) · 놓고 다음 경계 복귀 길 · 수정 목록 194
            # 정상 회차 끝은 여기 오지 않는다 · 회차 맞춤 회차의 끝은 장벽 전 틈부터 `motion_completed`(끝 아님) · 전에는
            # 그 틈이 `completed` 라 5 s 이어질 때만 놓았다(`ENDED_CONFIRM_SEC` · 195) · 이제 사람 정지는 바로 놓는다 · 199
            self._cancel(run, f'{run["cycle"]}회차 로컬 실행이 끝남 · {status.get("message") or state or "상태 없음"}')
            return
        self._advance(run, timeline, choice, phase, state, status, now_w, now_m, view)

    def release_stopped_window(self, why: str) -> None:
        """사람이 그룹을 맡았다(신호 재생 실행 · 시간표 재생 끔) · 그룹 정지 운영시간 끝 주차 기억을 버린다 · 수정 목록 201

        그 운영시간 끝에 주차하는 것은 사람이 손대지 않고 정지로 서 있던 PC 다 · 사람이 그룹 재생을 돌렸으면 그 끝도
        사람이 정한다 · 남겨 두면 그 재생이 끝난 직후(운영시간 끝 뒤) 갑자기 주차 → 서보 OFF 했다.
        """
        if self._stopped_window:
            self._info(f'시간표 재생 · {self._stopped_window} · 운영시간 끝 주차 기억 버림 · {why}')
        self._stopped_window = ''
        self._stopped_until = 0.0

    def _park_stopped_window(self, choice: Choice, view: Mapping[str, Any], now_w: float) -> bool:
        """사람 그룹 정지로 선 운영시간 · 끝나면 이 PC 도 주차 → 서보 OFF · 수정 목록 193 · 201

        정지가 운영시간 끝까지 유지된다(사용자 2026-11-11) · 회차를 쥔 PC 만 운영시간 끝에 주차하므로 정지로 선
        PC 는 서보를 켠 채 밤을 샜다 · 정지를 본 시간표(운영시간 이름)와 그 운영시간 끝 시각을 기억해 두고 그 시각이
        지나면(또는 다음 운영시간 시간표가 골라지거나 「운영시간 아님」) 한 번 주차한다.

        - 정지가 안 보여도(마스터 수동 · 끊김) 기억은 그 운영시간 끝까지 · 사용자 결정 「끊겨도 운영시간 끝에 스스로 선다」 ·
          전에는 정지를 2분 못 보면 기억을 버려(`STOPPED_FORGET_SEC`) 그 PC 가 서보를 켠 채 밤을 샜다 · 수정 목록 201
        - 같은 시간표가 다시 돌면(마스터 수동 → 스케줄) 기억을 지운다
        - 그 끝에 이 PC 가 수동 · 오프 모드면 주차하지 않는다(사람이 이 PC 를 만짐 · 운영 종료 규칙과 같음)
        - 사람이 그룹을 맡으면 연동 노드가 `release_stopped_window` 로 버린다
        """
        timeline = choice.timeline
        stopped = ''
        if choice.reason == '정지됨' and choice.stopped_plan_id.startswith(SCHEDULE_PREFIX):
            stopped = choice.stopped_plan_id
        elif choice.stop_after and timeline is not None and timeline.kind == 'schedule':
            stopped = timeline.plan_id
        if stopped:
            if stopped != self._stopped_window:
                self._stopped_until = 0.0
            self._stopped_window = stopped
            if float(choice.window_end_unix or 0.0) > 0.0:
                self._stopped_until = float(choice.window_end_unix)
            return False
        plan_id = self._stopped_window
        if not plan_id:
            return False
        if timeline is not None and timeline.plan_id == plan_id:
            self._stopped_window, self._stopped_until = '', 0.0   # 다시 돈다
            return False
        ended = (
            (self._stopped_until > 0.0 and now_w >= self._stopped_until)
            or (timeline is not None and timeline.kind == 'schedule')
            or (timeline is None and choice.reason == '운영시간 아님')
        )
        if not ended:
            return False
        self._stopped_window, self._stopped_until = '', 0.0
        mode = str(view.get('operation_mode') or '')
        if mode in {MANUAL_MODE, OFF_MODE}:
            self._info(f'시간표 재생 · {plan_id} · 운영시간 끝 · 이 PC 가 {mode} 모드 · 사람이 맡음 · 주차 안 함')
            return False
        if self._finish is not None:
            self._finish(plan_id, True, '운영시간 끝 · 그룹 정지로 서 있던 PC')
        self._info(f'시간표 재생 · {plan_id} · 운영시간 끝 · 그룹 정지로 서 있던 PC · 기준점 주차 → 서보 OFF')
        return True

    # ------------------------------------------------------------------ #

    def _adopt(self, held: str, phase: str, state: str, status, timeline, now_m: float) -> Optional[Dict[str, Any]]:
        """로컬에 남은 시간표 실행을 이어받는다 · 재생 중 · 회차 끝이면 그대로 · 그 밖(준비 · 초기 이동)은 놓고 다음 경계

        회차 끝 장벽 전 틈(`GROUP_CYCLE_FINISHING_PHASE`) · 최종 위치 확인(`verifying`)도 도는 회차다 · 전에는 그때
        다시 뜨면 「준비 단계」 로 보고 놓았다 · 수정 목록 199

        회차 명령을 쥔 재생 관리자(`timed_cycle`)는 초기 이동 · 시작을 스스로 한다 · 어느 단계든 이어받아 그 회차 끝(장벽)만
        기다린다 · 회차 번호는 쥔 명령의 것(장벽에서 다음 회차 명령을 이미 받았으면 그 회차) · 수정 목록 206
        """
        cycle = int(status.get('group_cycle_number') or status.get('current_cycle') or 0)
        timed = int(status.get('timed_cycle') or 0)
        cycle = max(cycle, timed)
        start = timeline.start_of(cycle) if timeline is not None and timeline.plan_id == held and cycle else 0.0
        self._run = {'plan_id': held, 'stage': 'scheduled', 'cycle': cycle, 'start_unix': start, 'sent_m': now_m,
                     'entered_unix': self._wall(), 'ack': status_stamp(status)}
        if (
            state in _ADOPT_STATES or phase in _ADOPT_PHASES
            or (timed and state not in _FINISHED_STATES and state != 'error')
        ):
            self._info(f'시간표 재생 · 남아 있던 실행 이어받음 · {held} · {cycle}회차')
            return self._run
        self._cancel(self._run, f'남아 있던 실행({held}) · 준비 단계라 놓고 다음 경계')
        return None

    def _init_sec(self, view: Mapping[str, Any], run: Optional[Mapping[str, Any]] = None) -> float:
        """이 PC 초기 이동 시간 · 묶음에 정한 값(마스터 · 0 = PC 마다) → 이 PC 조인트 매핑 값(로컬 상태 `initial_move_sec`) →
        아무도 안 알려 주면 선택지 중 가장 긴 값 · 수정 목록 205(전에는 따로 짐작한 10 s · 웹은 5 s)"""
        return initial_move_sec(
            (run or {}).get('initial_move_time_sec'), view.get('initial_move_time_sec'), view.get('init_sec'),
        )

    def _mono_of(self, wall_target: float) -> float:
        return self._mono() + (float(wall_target) - self._wall())

    def _maybe_enter(self, timeline, choice: Choice, view, status, held: str, state: str, now_w: float, now_m: float) -> None:
        if timeline is None:
            self._next_start_unix = 0.0
            self._set_note(choice.reason or '')
            return
        init = self._init_sec(view)
        prep = self.BUILD_SEC + init + self.MARGIN_SEC
        slot = clock_grid.next_slot(timeline, now_w, prep_sec=prep)
        if slot is None:
            self._next_start_unix = 0.0
            # 회차 후 정지로 남은 회차가 없음 · 그 운영시간 끝까지 유지(193) · 「시간표 끝」 은 틀린 말 · 수정 목록 194
            self._set_note('그룹 정지 유지 · 운영시간 끝까지' if choice.stop_after else '시간표 끝')
            return
        self._next_start_unix = slot.start_unix
        skip_plan, skip_cycle = self._skip
        if skip_plan == timeline.plan_id and slot.cycle <= skip_cycle:
            return
        pending = self._pending_slot
        if pending and pending != (timeline.plan_id, slot.cycle):
            # 서보 켜기(웹 「켜는 중」)를 기다리다 그 회차에 들어갈 때를 넘김 · 조용히 넘어가지 않게 쉼으로 남긴다 ·
            # 웹의 켜기는 축마다 명령 + 확인 한도(`SERVO_ON_WAIT_SEC`)라 들어가는 창(30 s 남짓)보다 짧다 · 수정 목록 217
            self._pending_slot = None
            self._pending_until_m = 0.0
            self._skip_cycle(pending[0], pending[1], '서보 켜기가 끝나지 않음', f'{pending[1]}회차 쉼 · 서보 켜기가 끝나지 않음')
        blocker = str(view.get('start_blocker') or '')
        early = slot.start_unix - now_w > prep + self.ENTER_WINDOW_SEC
        if blocker:
            # 모터 · 설정 문제 · 풀리면 다음 경계 · 화면에 늘 보인다 · 들어갈 때면 회차마다 경고 한 줄(189)
            if early:
                self._set_note(blocker)
            else:
                self._skip_cycle(timeline.plan_id, slot.cycle, blocker, blocker)
            return
        if early:
            # 앞 회차를 쉰 이유는 다음 들어갈 때까지 남긴다 · 전에는 바로 지워져 흔적이 없었다(189)
            if not self._skip_note or self._note != self._skip_note:
                self._set_note('')
            return
        if _stale_group(held, state, status) and held != self._stale_cancelled:
            # 끝내기를 놓친 옛 그룹 실행 · 정리하고 다음 틱에 들어간다 · 같은 회차 안 · 수정 목록 193 ④
            self._stale_cancelled = held
            result = self._control({
                'command': 'group_cancel', 'execution_id': held,
                'network_operation_id': f'tt-stale-{uuid.uuid4().hex}',
            })
            # 정리한 뒤의 상태를 보고 들어간다 · 그 앞 상태로 「다른 재생 중」 이라 이 회차를 쉬지 않게 · 수정 목록 199
            self._note_release(result)
            self._warn(f'시간표 재생 · 끝내기를 놓친 옛 그룹 실행({held} · {state}) 정리 · {result.get("message") or ""}')
            return
        if _occupied(held, state, status):
            detail = held or ' · '.join(
                part for part in (state, str(status.get('request_source') or '')) if part
            )
            self._skip_cycle(timeline.plan_id, slot.cycle, f'다른 재생 중({detail})', '다른 재생 중 · 이 회차 쉼')
            return
        if now_m < self._pending_until_m:
            return
        common = {
            'execution_id': timeline.plan_id,
            'network_operation_id': f'tt-enter-{uuid.uuid4().hex}',
            'repeat_mode': 'reinitialize',
            'dwell_sec': 0.0,
            'initialization_only': False,
            'run_mode': 'continuous',
            'sync_mode': GROUP_LOCKSTEP,
            'target_cycle_count': 0,
            'initial_move_time_sec': float(view.get('initial_move_time_sec') or 0.0),
        }
        if slot.cycle == 1:
            # 준비 명령은 초기 이동 예약 시각을 꼭 싣는다(신호 재생과 같은 명령) · 여기 값은 짐작(조인트 매핑 값) ·
            # 바로 뒤 회차 명령을 받으면 재생 관리자가 제 초기 이동 시간(첫 프레임 잇기 포함)으로 다시 센다 · 수정 목록 206
            initialize_at = slot.start_unix - init - self.MARGIN_SEC
            payload = {**common, 'command': 'group_prepare', 'initialize_monotonic': self._mono_of(initialize_at)}
            stage = 'preparing'
        else:
            payload = {**common, 'command': 'group_join', 'join_cycle_number': slot.cycle - 1}
            stage = 'joining'
        result = self._control(payload)
        if result.get('pending'):
            # 운영시간 첫 회차 · 웹이 꺼진 서보를 켜는 중 · 쉬지 않고 잠시 뒤 다시 묻는다 · 켜기 실패는 웹이 실패로 답해
            # 아래에서 그 회차를 쉰다 · 수정 목록 217
            self._pending_until_m = now_m + self.PENDING_POLL_SEC
            self._pending_slot = (timeline.plan_id, slot.cycle)
            self._set_note(f'{slot.cycle}회차 준비 · {result.get("message") or "서보 켜는 중"}')
            return
        self._pending_until_m = 0.0
        self._pending_slot = None
        if not result.get('success'):
            self._skip = (timeline.plan_id, slot.cycle)
            self._set_note(f'{slot.cycle}회차 쉼 · {result.get("message") or "응답 없음"}', warn=True)
            return
        self._run = {
            'plan_id': timeline.plan_id, 'stage': stage, 'cycle': slot.cycle, 'start_unix': slot.start_unix,
            'sent_m': now_m, 'initial_move_time_sec': float(view.get('initial_move_time_sec') or 0.0),
            'entered_unix': now_w,
        }
        # 이 응답 뒤의 로컬 상태만 이 실행의 것으로 읽는다(앞 시도의 정지 · 오류 · 다른 실행을 거름) · 수정 목록 199
        self._note_ack(self._run, result, now_m)
        self._skip_note = ''
        self._set_note('')
        self._info(
            f'시간표 재생 · {timeline.plan_id} · {slot.cycle}회차 준비 · 시작까지 {slot.start_unix - now_w:.0f} s'
            + (' · 복귀 길' if stage == 'joining' else '')
        )
        # 그 회차 명령을 같은 틱에 · 준비가 받아졌으면 세션이 서 있다 · 복귀 길은 이것이 합류 확정을 겸한다 · 수정 목록 206 ·
        # 전에는 「복귀 준비」 · 「초기 이동 끝」 을 로컬 상태로 본 뒤에 다음 명령을 보냈다
        self._send_cycle(self._run, timeline, slot.cycle, now_m)

    def _advance(self, run, timeline, choice: Choice, phase: str, state: str, status, now_w: float, now_m: float, view) -> None:
        """쥔 회차 · 그 사이는 결과만 본다(늦게 시작 · 쉼 기록) · 회차 끝(장벽)이면 다음 회차 명령 하나 · 수정 목록 206

        전에는 단계마다 로컬 상태를 보고 다음 명령(초기 이동 예약 → 시작 예약)을 보냈고 · 시각을 지났으면 「늦음 · 다음 경계」
        로 이 PC 회차를 버렸다(`now_w > start + 1` · `next_initialize <= now + 0.3`) · 이제 늦음 · 쉼은 재생 관리자가
        제 시계로 정한다 · 다음 회차 시각이 이미 지났어도 명령은 보낸다(그 회차를 늦게라도 돌지 · 쉴지 재생 관리자가 정함).
        """
        self._note_cycle_result(run, status, phase, state)
        if phase not in BARRIER_PHASES:
            return
        done = int(status.get('current_cycle') or status.get('group_cycle_number') or 0)
        if done != int(run['cycle']):
            return
        following = done + 1
        if not timeline.has_cycle(following):
            self._finish_run(run, park=timeline.kind == 'schedule' and not choice.stop_after,
                             why='운영시간 끝' if not choice.stop_after else '회차 후 정지')
            return
        self._send_cycle(run, timeline, following, now_m)

    def _send_cycle(self, run, timeline, cycle: int, now_m: float) -> bool:
        """회차 명령 하나 · 「k 회차를 T 에 시작 · 다음 회차 N」 · 초기 이동 → 시작은 재생 관리자가 제 시계로 · 수정 목록 206

        다음 회차 시각(N)은 재생 관리자가 「너무 늦어 쉼」 을 가르는 데만 쓴다(그 회차를 돌면 다음 회차 준비를 먹는가) ·
        운영시간 마지막 회차면 0(한도 없음).
        """
        start = timeline.start_of(cycle)
        following = int(cycle) + 1
        next_start = timeline.start_of(following) if timeline.has_cycle(following) else 0.0
        run.update(cycle=int(cycle), start_unix=start)
        result = self._control({
            'command': 'group_cycle_at', 'execution_id': run['plan_id'], 'cycle_number': int(cycle),
            'start_monotonic': self._mono_of(start),
            'next_start_monotonic': self._mono_of(next_start) if next_start else 0.0,
            'network_operation_id': f'tt-cycle-{uuid.uuid4().hex}',
        })
        if not result.get('success'):
            # 바로 놓지 않고 다음 틱의 로컬 상태로 가른다 · 들어간 직후 로컬 준비 검사가 실패해(서보 꺼짐 등) 세션이 이미
            # 닫혔으면 이 명령은 「세션이 일치하지 않음」 으로 거절된다 · 그때는 오류 상태의 이유(197)를 남긴다 · 수정 목록 206
            run['cycle_failed'] = f'{cycle}회차 시각 예약 실패 · {result.get("message") or "응답 없음"}'
            return False
        run['stage'] = 'scheduled'
        self._note_ack(run, result, now_m)
        return True

    def _note_cycle_result(self, run, status: Mapping[str, Any], phase: str, state: str) -> None:
        """재생 관리자가 알린 쥔 회차의 결과 · 회차마다 한 번 기록 + 화면 글 · 수정 목록 206

        - 쉼(`group_cycle_skipped`) · 「N회차 쉼 · 이유」(191 글 꼴) · 실행은 놓지 않는다(다음 회차 명령을 이어서)
        - 늦게 시작(`cycle_start_late_sec`) · 쉼이 아니다 · 다음 회차가 제때 시작하면 화면 글을 지운다
        """
        cycle = int(status.get('group_cycle_number') or status.get('current_cycle') or 0)
        if not cycle or cycle != int(run.get('cycle') or 0):
            return
        plan_id = str(run.get('plan_id') or '')
        if phase == GROUP_CYCLE_SKIPPED_PHASE:
            reason = str(status.get('cycle_skip_reason') or '') or '초기 이동이 너무 늦음'
            key = (plan_id, cycle, reason)
            if key != self._skip_logged:
                self._skip_logged = key
                self._warn(f'시간표 재생 · {cycle}회차 쉼 · {reason}')
            self._result_note = f'{cycle}회차 쉼 · {reason}'
            self._set_note(self._result_note)
            return
        if state not in {'running', 'verifying'}:
            return
        try:
            late = float(status.get('cycle_start_late_sec') or 0.0)
        except (TypeError, ValueError):
            late = 0.0
        if late > 0.0:
            if (plan_id, cycle) != self._late_logged:
                self._late_logged = (plan_id, cycle)
                self._warn(
                    f'시간표 재생 · {cycle}회차 {late:.1f} s 늦게 시작 · 초기 이동이 늦게 끝남 · 쉼 아님 · '
                    '다음 회차는 다시 시간표 시각'
                )
                self._result_note = f'{cycle}회차 {late:.1f} s 늦게 시작 · 다음 회차는 시간표대로'
                self._set_note(self._result_note)
        elif self._result_note and self._note == self._result_note:
            self._result_note = ''
            self._set_note('')

    def _leave_when_safe(self, run, phase: str, state: str, choice: Choice) -> None:
        """따를 시간표가 바뀌었다(운영시간 끝 · 신호 재생 · 다른 시간표) · 도는 회차는 끝까지 · 장벽에서 놓는다

        로컬 실행이 이미 끝났으면(정지 · 완료 · 같은 실행 번호) 장벽을 기다리지 않고 바로 놓는다 · 전에는 `stopped` 가
        장벽 단계가 아니라 영영 쥐고 있었다 · 마지막 창 끝에 마스터만 단독 회차 후 정지로 `stopped` 가 되자 그 실행을
        하트비트로 4대에 「도는 중」 으로 퍼뜨려 4대 주차가 교착(실물 NY 2026-11-09 23:27 · B) · 수정 목록 191
        """
        begun = state in _CYCLE_BEGUN_STATES or phase in _CYCLE_BEGUN_PHASES
        if begun and phase not in BARRIER_PHASES and state not in _FINISHED_STATES:
            return
        # 운영시간 끝 · 끝난 뒤에는 다음 운영시간(내일) 시간표가 골라지거나 없다 · 그때만 주차 → 서보 OFF ·
        # 마스터를 수동 모드로 바꾼 것 · 신호 재생으로 바꾼 것은 그 자리 정지(사람이 만지려는 것)
        next_window = (
            choice.timeline is not None and choice.timeline.kind == 'schedule'
            and choice.timeline.plan_id != run['plan_id']
        )
        window_end = run['plan_id'].startswith(SCHEDULE_PREFIX) and (
            next_window or (choice.timeline is None and choice.reason == '운영시간 아님')
        )
        self._finish_run(run, park=window_end,
                         why='운영시간 끝' if window_end else
                         f'따를 시간표 바뀜 · {choice.reason or (choice.timeline.plan_id if choice.timeline else "")}')

    def _finish_run(self, run, *, park: bool, why: str) -> None:
        if self._finish is not None:
            self._finish(run['plan_id'], park, why)
        else:
            self._control({
                'command': 'group_cancel', 'execution_id': run['plan_id'],
                'network_operation_id': f'tt-end-{uuid.uuid4().hex}',
            })
        self._info(f'시간표 재생 · {run["plan_id"]} · {why}' + (' · 기준점 주차 → 서보 OFF' if park else ''))
        self._skip = (run['plan_id'], int(run['cycle']))
        self._run = None

    def _cancel(self, run, why: str) -> None:
        result = self._control({
            'command': 'group_cancel', 'execution_id': run['plan_id'],
            'network_operation_id': f'tt-cancel-{uuid.uuid4().hex}',
        })
        self._note_release(result)
        self._drop(why)

    def _drop(self, why: str) -> None:
        """이 회차를 버린다 · 경고 로그는 「N회차 쉼」 글로 · 수정 목록 191

        전에는 「시간표 재생 · N회차 로컬 실행이 끝남」 처럼 이유만 남아 「회차 쉼」 으로 찾으면 안 걸렸다(실물 NY
        2026-11-09 · D) · 같은 이유는 같은 회차에 한 줄.
        """
        run = self._run or {}
        plan_id, cycle = str(run.get('plan_id') or ''), int(run.get('cycle') or 0)
        self._skip = (plan_id, cycle)
        self._run = None
        if why:
            # 쉰 이유는 다음 들어갈 때까지 화면에 남긴다(189 규칙) · 전에는 `_note` 만 바꿔 다음 틱에 지워졌다(실물
            # NY 2026-11-11 00:48 · f4 재시작 뒤 로그에만 있고 화면 note 는 빈 값) · 수정 목록 194
            self._skip_note = why
        if not why or why == self._note:
            return
        self._note = why
        prefix = f'{cycle}회차 '
        reason = why[len(prefix):] if why.startswith(prefix) else why
        reason = reason[len('쉼 · '):] if reason.startswith('쉼 · ') else reason
        key = (plan_id, cycle, reason)
        if key != self._skip_logged:
            self._skip_logged = key
            self._warn(f'시간표 재생 · {cycle}회차 쉼 · {reason}' if cycle else f'시간표 재생 · {reason}')

    def _skip_cycle(self, plan_id: str, cycle: int, why: str, note: str) -> None:
        """들어갈 때인데 못 들어감 · 화면 이유 + 회차마다 경고 로그 한 줄 · 수정 목록 189

        전에는 「다른 재생 중 · 이 회차 쉼」 이 로그 없이 화면에만 떴다가 다음 틱에 지워져 1회차부터 조용히
        안 돌았다(실물 NY 2026-11-09 08:31 · 로그 0줄).
        """
        self._skip_note = note
        self._set_note(note)
        key = (plan_id, int(cycle), why)
        if key != self._skip_logged:
            self._skip_logged = key
            self._warn(f'시간표 재생 · {cycle}회차 쉼 · {why}')

    def _set_note(self, text: str, *, warn: bool = False) -> None:
        if text == self._note:
            return
        self._note = text
        if text and warn:
            self._warn(f'시간표 재생 · {text}')
