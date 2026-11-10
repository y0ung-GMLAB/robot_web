"""시간표 재생 · 이 PC 혼자 시간표대로 재생 · 수정 목록 186 (2026-11-09)

사용자 결정(설계 2-3 · 7장) · 마스터 신호 없이 각 PC 가 시간표의 회차 시각에 스스로 초기 이동 → 재생.

- 회차 하나 · 시작 T 를 정한다 → T − 초기 이동 − 2 s 에 초기 이동 → T 에 재생 · 로컬 재생 관리자의 그룹 실행
  (`group_prepare` · `group_initialize_at` · `group_start_at`)을 그대로 쓴다 · 실행 번호 = 시간표 이름(모든 PC 같음)
- 1회차는 처음 준비(`group_prepare`) · 2회차부터 들어가는 PC(재부팅 · 늦게 켬 · 쉬었다 옴)는 복귀 길
  (`group_join` → `group_join_commit`)로 「앞 회차를 끝낸 것처럼」 서서 그 회차 초기 위치로 간다 · 그래서 로컬
  회차 번호 · 재생 목록 순서가 시간표와 같다
- 회차 중간 합류 없음 · 준비가 늦으면 그 회차는 쉬고 다음 경계 · **이 PC 만**(다른 PC 는 그대로)
- 회차 끝 · 다음 회차가 시간표에 있으면 그 초기 이동을 예약 · 없으면(운영시간 끝 · 회차 후 정지) 놓는다 ·
  운영시간 끝이면 기준점 주차 → 서보 OFF(평소 운영 종료와 같음)
- 사람의 즉시 정지 · 이 PC 가 그 시간표를 쥐고 있으면 바로 정지

로컬 웹 호출(`control`)만 한다 · ROS 를 모른다 · 시험은 가짜 재생 관리자로.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, Mapping, Optional

from motion_common.repeat_policy import GROUP_LOCKSTEP

from . import clock_grid
from .timetable import Choice

#: 시간표 실행 번호 머리 · `clock_grid.schedule_plan_id`
PLAN_PREFIX = 'tt-'
SCHEDULE_PREFIX = 'tt-s'
#: 회차 끝 장벽 단계 · 로컬 재생 관리자 · 연동 노드 `_BARRIER_PHASES` 와 같다
BARRIER_PHASES = frozenset({'group_motion_completed', 'group_join_committed'})
#: 끝난 로컬 실행 · 실행 번호가 남아 있어도 쥔 것으로 보지 않는다 · 수정 목록 188
#: 실제 재생 관리자는 정지 · 완료 뒤에도 `group_execution` 과 그 번호를 남긴다 · 전에는 그것을 「다른 재생 중」 으로 보고
#: 회차마다 쉬었다(실물 NY 2026-11-09 03:49 · 신호 재생 그룹을 즉시 정지하고 시간표 재생으로 바꾼 뒤 4대 모두 7회차 쉼)
_FINISHED_STATES = frozenset({'', 'idle', 'ready', 'stopped', 'completed'})


#: 그룹 실행이 아닌 로컬 재생이 「돌고 있는」 상태 · 연동 노드 `_SOLO_BUSY_STATES` + 준비 · 예약 · 정지 중 · 수정 목록 189
_SOLO_BUSY_STATES = frozenset({
    'preparing', 'initializing', 'running', 'verifying', 'waiting', 'recovering', 'stopping', 'armed', 'start_scheduled',
})


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


class ClockDriver:
    """시간표 하나를 이 PC 에서 돌린다 · 연동 노드가 0.1 s 마다 `tick`"""

    #: 계획 짓기 여유 · 재생 목록 전부(920 s × 20 조인트 파일 하나 3 s 남짓 · 목록 여럿이면 더)
    BUILD_SEC = 45.0
    #: 초기 이동 끝 → 재생 시작 사이 · 자동 주기에도 들어간다(`clock_grid.auto_period`) · 2 s → 4 s · 수정 목록 188
    MARGIN_SEC = clock_grid.CYCLE_START_LEAD_SEC
    #: 실행을 잡는 시점 · 준비 시간 + 이만큼 전부터 · 그 전에는 로컬 실행을 잡지 않는다(사람 조작 가능)
    ENTER_WINDOW_SEC = 30.0
    #: 명령을 보낸 뒤 로컬 상태가 따라올 때까지 기다리는 시간 · 그 안에 사라져 보여도 끝난 것으로 보지 않는다
    STATUS_GRACE_SEC = 3.0
    #: 초기 이동을 모를 때 · 신호 재생 스스로 잇기(끊김 시험 A)와 같은 10 s
    INIT_FALLBACK_SEC = 10.0
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
        self._note = ''
        #: 회차를 쉬며 띄운 이유 · 다음 들어갈 때까지 화면에 남긴다 · 수정 목록 189
        self._skip_note = ''
        #: 마지막으로 경고 로그를 남긴 쉼 · (plan_id, 회차, 이유) · 같은 회차는 한 줄 · 수정 목록 189
        self._skip_logged: tuple = ('', 0, '')
        self._next_start_unix = 0.0

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

    def tick(self, choice: Choice, view: Mapping[str, Any]) -> None:
        """`view` · status(로컬 재생 상태) · init_sec(이 PC 초기 이동) · start_blocker · initial_move_time_sec"""
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

        if run is None and live.startswith(PLAN_PREFIX):
            # 이 노드가 다시 떴다(워치독 · 업데이트) · 로컬 재생 관리자는 시간표 실행을 계속 돌고 있다 · 이어받는다
            run = self._adopt(live, phase, state, status, timeline, now_m)
            if run is None:
                return
        if run is not None and held != run['plan_id']:
            if now_m - float(run.get('sent_m') or 0.0) > self.STATUS_GRACE_SEC:
                # 로컬 실행이 사라졌다(오류 · 누가 세움 · 웹 서비스 재시작) · 이 회차는 쉬고 다음 경계
                self._drop(f'{run["cycle"]}회차 로컬 실행이 끝남 · {status.get("message") or state or "상태 없음"}')
            return
        if run is not None and state == 'error':
            self._cancel(run, f'{run["cycle"]}회차 오류 · {status.get("message") or ""}')
            return
        if (
            run is not None and choice.halt_plan_id and choice.halt_plan_id == run['plan_id']
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
            self._info(f'시간표 재생 · 놓친 즉시 정지 · {run["plan_id"]} · {result.get("message") or ""}')
            self._skip = (run['plan_id'], int(run.get('cycle') or 0))
            self._run = None
            self._set_note('놓친 즉시 정지 · 다음 경계', warn=True)
            return
        if run is not None and choice.stopped_plan_id and choice.stopped_plan_id == run['plan_id']:
            result = self._control({
                'command': 'stop_now',
                'execution_id': run['plan_id'],
                'network_operation_id': f'tt-stop-{uuid.uuid4().hex}',
            })
            self._info(f'시간표 재생 · 즉시 정지 · {run["plan_id"]} · {result.get("message") or ""}')
            self._skip = (run['plan_id'], self._STOPPED_SKIP)
            self._run = None
            self._note = '정지됨'
            return
        if run is not None and (timeline is None or timeline.plan_id != run['plan_id']):
            self._leave_when_safe(run, phase, state, choice)
            return
        if run is not None:
            self._advance(run, timeline, choice, phase, state, status, now_w, now_m, view)
            return
        self._maybe_enter(timeline, choice, view, status, live, state, now_w, now_m)

    # ------------------------------------------------------------------ #

    def _adopt(self, held: str, phase: str, state: str, status, timeline, now_m: float) -> Optional[Dict[str, Any]]:
        """로컬에 남은 시간표 실행을 이어받는다 · 재생 중 · 회차 끝이면 그대로 · 그 밖(준비 · 초기 이동)은 놓고 다음 경계"""
        cycle = int(status.get('group_cycle_number') or status.get('current_cycle') or 0)
        start = timeline.start_of(cycle) if timeline is not None and timeline.plan_id == held and cycle else 0.0
        self._run = {'plan_id': held, 'stage': 'scheduled', 'cycle': cycle, 'start_unix': start, 'sent_m': now_m,
                     'entered_unix': self._wall()}
        if state in {'running', 'start_scheduled'} or phase in BARRIER_PHASES:
            self._info(f'시간표 재생 · 남아 있던 실행 이어받음 · {held} · {cycle}회차')
            return self._run
        self._cancel(self._run, f'남아 있던 실행({held}) · 준비 단계라 놓고 다음 경계')
        return None

    def _init_sec(self, view: Mapping[str, Any], run: Optional[Mapping[str, Any]] = None) -> float:
        planned = float((run or {}).get('initial_move_time_sec') or view.get('initial_move_time_sec') or 0.0)
        if planned > 0.0:
            return planned
        local = float(view.get('init_sec') or 0.0)
        return local if local > 0.0 else self.INIT_FALLBACK_SEC

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
            self._set_note('시간표 끝')
            return
        self._next_start_unix = slot.start_unix
        skip_plan, skip_cycle = self._skip
        if skip_plan == timeline.plan_id and slot.cycle <= skip_cycle:
            return
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
        if _occupied(held, state, status):
            detail = held or ' · '.join(
                part for part in (state, str(status.get('request_source') or '')) if part
            )
            self._skip_cycle(timeline.plan_id, slot.cycle, f'다른 재생 중({detail})', '다른 재생 중 · 이 회차 쉼')
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
            initialize_at = slot.start_unix - init - self.MARGIN_SEC
            payload = {**common, 'command': 'group_prepare', 'initialize_monotonic': self._mono_of(initialize_at)}
            stage = 'preparing'
        else:
            payload = {**common, 'command': 'group_join', 'join_cycle_number': slot.cycle - 1}
            stage = 'joining'
        result = self._control(payload)
        if not result.get('success'):
            self._skip = (timeline.plan_id, slot.cycle)
            self._set_note(f'{slot.cycle}회차 쉼 · {result.get("message") or "응답 없음"}', warn=True)
            return
        self._run = {
            'plan_id': timeline.plan_id, 'stage': stage, 'cycle': slot.cycle, 'start_unix': slot.start_unix,
            'sent_m': now_m, 'initial_move_time_sec': float(view.get('initial_move_time_sec') or 0.0),
            'entered_unix': now_w,
        }
        self._skip_note = ''
        self._set_note('')
        self._info(
            f'시간표 재생 · {timeline.plan_id} · {slot.cycle}회차 준비 · 시작까지 {slot.start_unix - now_w:.0f} s'
            + (' · 복귀 길' if stage == 'joining' else '')
        )

    def _advance(self, run, timeline, choice: Choice, phase: str, state: str, status, now_w: float, now_m: float, view) -> None:
        stage = run['stage']
        init = self._init_sec(view, run)
        start = float(run['start_unix'])
        initialize_at = start - init - self.MARGIN_SEC
        if stage == 'joining':
            if phase == 'group_join_ready':
                if initialize_at <= now_w + 0.3:
                    self._cancel(run, f'{run["cycle"]}회차 준비가 늦음 · 다음 경계')
                    return
                commit = self._control({
                    'command': 'group_join_commit', 'execution_id': run['plan_id'],
                    'cycle_number': int(run['cycle']) - 1,
                    'network_operation_id': f'tt-commit-{uuid.uuid4().hex}',
                })
                if not commit.get('success'):
                    self._cancel(run, f'{run["cycle"]}회차 복귀 확정 실패 · {commit.get("message") or ""}')
                    return
                self._schedule_initialize(run, int(run['cycle']) - 1, initialize_at, now_m)
            elif now_w > initialize_at - 0.3:
                self._cancel(run, f'{run["cycle"]}회차 계획 짓기가 늦음 · 다음 경계')
            return
        if stage == 'preparing':
            if state == 'armed' or phase == 'group_armed':
                self._schedule_start(run, now_m)
            elif now_w > start + 1.0:
                self._cancel(run, f'{run["cycle"]}회차 초기 이동이 늦음 · 다음 경계')
            return
        if stage == 'initializing':
            if phase == 'group_cycle_initialized':
                self._schedule_start(run, now_m)
            elif now_w > start + 1.0:
                self._cancel(run, f'{run["cycle"]}회차 초기 이동이 늦음 · 다음 경계')
            return
        if stage == 'scheduled' and phase in BARRIER_PHASES:
            done = int(status.get('current_cycle') or status.get('group_cycle_number') or 0)
            if done != int(run['cycle']):
                return
            following = done + 1
            if not timeline.has_cycle(following):
                self._finish_run(run, park=timeline.kind == 'schedule' and not choice.stop_after,
                                 why='운영시간 끝' if not choice.stop_after else '회차 후 정지')
                return
            next_start = timeline.start_of(following)
            next_initialize = next_start - init - self.MARGIN_SEC
            if next_initialize <= now_w + 0.3:
                # 클립이 길었거나(주기보다) 늦었다 · 이 PC 만 쉬고 다음 경계에 다시 들어온다
                self._cancel(run, f'{following}회차 초기 이동 시각을 놓침 · 다음 경계')
                return
            run.update(cycle=following, start_unix=next_start)
            self._schedule_initialize(run, done, next_initialize, now_m)

    def _schedule_initialize(self, run, cycle_done: int, initialize_at_wall: float, now_m: float) -> None:
        result = self._control({
            'command': 'group_initialize_at', 'execution_id': run['plan_id'], 'cycle_number': int(cycle_done),
            'initialize_monotonic': self._mono_of(initialize_at_wall),
            'network_operation_id': f'tt-init-{uuid.uuid4().hex}',
        })
        if not result.get('success'):
            self._cancel(run, f'{run["cycle"]}회차 초기 이동 예약 실패 · {result.get("message") or ""}')
            return
        run.update(stage='initializing', sent_m=now_m)

    def _schedule_start(self, run, now_m: float) -> None:
        start = float(run['start_unix'])
        if start <= self._wall() + 0.1:
            self._cancel(run, f'{run["cycle"]}회차 시작 시각을 놓침 · 다음 경계')
            return
        result = self._control({
            'command': 'group_start_at', 'execution_id': run['plan_id'], 'cycle_number': int(run['cycle']),
            'start_monotonic': self._mono_of(start),
            'network_operation_id': f'tt-start-{uuid.uuid4().hex}',
        })
        if not result.get('success'):
            self._cancel(run, f'{run["cycle"]}회차 시작 예약 실패 · {result.get("message") or ""}')
            return
        run.update(stage='scheduled', sent_m=now_m)

    def _leave_when_safe(self, run, phase: str, state: str, choice: Choice) -> None:
        """따를 시간표가 바뀌었다(운영시간 끝 · 신호 재생 · 다른 시간표) · 도는 회차는 끝까지 · 장벽에서 놓는다

        로컬 실행이 이미 끝났으면(정지 · 완료 · 같은 실행 번호) 장벽을 기다리지 않고 바로 놓는다 · 전에는 `stopped` 가
        장벽 단계가 아니라 영영 쥐고 있었다 · 마지막 창 끝에 마스터만 단독 회차 후 정지로 `stopped` 가 되자 그 실행을
        하트비트로 4대에 「도는 중」 으로 퍼뜨려 4대 주차가 교착(실물 NY 2026-11-09 23:27 · B) · 수정 목록 191
        """
        if run['stage'] == 'scheduled' and phase not in BARRIER_PHASES and state not in _FINISHED_STATES:
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
        self._control({
            'command': 'group_cancel', 'execution_id': run['plan_id'],
            'network_operation_id': f'tt-cancel-{uuid.uuid4().hex}',
        })
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
        if not why or why == self._note:
            return
        self._note = why
        prefix = f'{cycle}회차 '
        reason = why[len(prefix):] if why.startswith(prefix) else why
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
