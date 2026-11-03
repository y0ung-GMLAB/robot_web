"""DDS 그룹 실행 세션 · 여러 PC가 같은 시각에 같은 동작을 하도록 맞춘다.

`MotionRunManager`에서 떼어냈다 · §5 분해 목표안의 `GroupSession` · §6-29

이 객체가 갖는 것 · 세션 상태와 그 조건변수.
**조건변수는 실행 락(`_run_lock`) 위에 만든다** · 그룹 세션과 단일 실행이 같은
자원을 두고 다투므로 락을 나눠 가지면 안 된다. 노드가 락을 소유하고 넘겨준다 ·
`ScanOrchestrator`·`MotorConfigService`가 `lifecycle_lock`을 나눠 갖는 것과 같다.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from motion_common import repeat_policy
from motion_common.values import finite_float

from . import motion_run_rules
from .deferred_playlist import DeferredPlaylist

#: 스케줄 구간 끝이 보낸 회차 후 정지의 이유 · 브리지·연동 노드가 같은 글자를 쓴다
SCHEDULE_END_REASON = 'schedule_end'
#: 구간 끝 정상 정지 · 전에는 마스터의 세션 정리가 「그룹 실행 취소」 로 덮어 실패처럼 읽혔다 · 수정 목록 141
SCHEDULE_END_STOP_MESSAGE = '구간 끝 · 회차 후 정지'
#: 사람이 누른 「현재 회차 후 정지」
GROUP_AFTER_CYCLE_STOP_MESSAGE = '현재 그룹 모션 회차 완료 후 정지'
#: 재생 목록 2번부터 짓기 시작 · 1회차 시작 시각 + 이만큼 · 수정 목록 171
#:
#: 그룹 시작은 「준비 → 초기 위치 이동 예약 확인 → 이동 → 모션 시작 대기 → `start_at` 확인 → 시작 →
#: 시작 보고(진행 PC 가 1 s 안에 받아야 함 · `trigger_report_timeout_sec`)」 가 모두 마감이 있다 ·
#: 짓기가 이 사이에 돌면 GIL 을 두고 다퉈 확인이 늦었다(NY 실물 2026-11-03 · 진행 PC 제 `start_at`
#: 확인 0.4 s 넘김 · 그룹 취소) · 그래서 시작 보고까지 지나고 짓는다 · 2번은 1회차가 끝나야 쓴다.
#: 1회차가 이보다 짧으면 쓸 때(회차 끝) 바로 짓는다.
DEFERRED_BUILD_DELAY_SEC = 1.5


class GroupSession:
    def __init__(self, manager: Any, *, run_lock: threading.RLock) -> None:
        self.manager = manager
        #: 단일 실행과 같은 락 위에서 기다린다
        self.condition = threading.Condition(run_lock)
        self.session: Dict[str, Any] = {}

    # -- 정지 경로가 부르는 것 ------------------------------------------- #

    def mark_stopping(self) -> None:
        """즉시 정지 · 세션을 비활성으로 표시하고 대기 중인 쪽을 깨운다."""
        with self.condition:
            if self.session:
                # 즉시 정지가 회차 후 정지보다 이긴다 · 끝 문구도 「회차 후 정지」 로 쓰지 않는다 · 수정 목록 141
                self.session.update({'active': False, 'state': 'stopping', 'stopped_now': True})
            self.condition.notify_all()

    def after_cycle_stop_message(self, default: str = GROUP_AFTER_CYCLE_STOP_MESSAGE) -> str:
        """회차 후 정지로 끝난 세션의 끝 문구 · 아니면 빈 글자 · 수정 목록 141

        스케줄 구간 끝이면 「구간 끝 · 회차 후 정지」 · 사람이 누른 회차 후 정지면 `default` ·
        회차 후 정지를 안 받았거나 그 뒤 즉시 정지가 왔으면 빈 글자(부르는 쪽 옛 문구 그대로).
        """
        with self.condition:
            if not self.session.get('stop_after_cycle') or self.session.get('stopped_now'):
                return ''
            if str(self.session.get('stop_reason') or '') == SCHEDULE_END_REASON:
                return SCHEDULE_END_STOP_MESSAGE
            return default

    def request_stop_after_cycle(
        self, current: Dict[str, Any], reason: str = '', group_wide: bool = False,
    ) -> bool:
        """이번 주기까지만 · 활성 세션이 없으면 거짓.

        정지 지시가 실제로 서려면 세션 표시만으로는 부족하다 · 재생 루프가 보는
        `_graceful_stop_event`도 함께 세운다. 아직 움직이는 중이 아니면
        `_stop_event`까지 세워 즉시 끝낸다.

        `reason` · 스케줄 구간 끝이면 `schedule_end` · 끝 문구를 가른다 · 수정 목록 141

        `group_wide` · 진행 PC 가 아는 그룹 전체 회차 후 정지(연동 노드가 DDS 로 받거나 보낸 것) ·
        회차 맞춤이면 제 회차를 끝내고 **장벽에 머문다** · 진행 PC 가 모든 PC 회차 끝을 보고 푼다 ·
        전에는 짧은 PC 가 바로 멈춰(`stopped`) 긴 PC 의 마지막 회차가 잘렸다 · 수정 목록 154 ·
        아니면(이 PC 만 · 1등급 알람 · 단독 길) 옛 그대로 회차 끝에 멈춘다 · 진행 PC 가 「먼저 정지」 로 푼다
        """
        with self.condition:
            if not self.session.get('active'):
                return False
            self.session['stop_after_cycle'] = True
            if group_wide:
                self.session['stop_after_cycle_group'] = True
            if reason or not self.session.get('stop_reason'):
                self.session['stop_reason'] = str(reason or '')
            self.manager._graceful_stop_event.set()
            # `completed` · 회차 애니가 막 끝나 장벽 표시 직전 · 여기서 끊으면 회차 끝이 「정지」 로 나간다 · 154
            finishing = {'running', 'verifying', 'completed', 'motion_completed'}
            if self.session.get('independent'):
                # 각자 재생 · 회차 사이(초기 위치 이동·대기)도 재생 루프 안이다 ·
                # 루프가 회차 후 정지를 보고 멈춘다 · 움직이는 도중 끊지 않는다
                finishing |= {'initializing', 'initialized', 'waiting'}
            if current.get('state') not in finishing:
                self.manager._stop_event.set()
            # 이미 장벽에서 다른 PC 를 기다리는 중 · 화면에 「회차 후 정지 대기」 · 155
            at_barrier = (
                group_wide
                and not self.session.get('independent')
                and self.session.get('state') == 'motion_completed'
            )
            barrier_cycle = int(self.session.get('cycle_number') or 0)
            self.condition.notify_all()
        if at_barrier:
            self._mark_stop_wait(barrier_cycle)
        return True

    def _mark_stop_wait(self, cycle_number: int) -> None:
        """회차 맞춤 · 제 회차를 끝냈고 회차 후 정지 대기 · 상태 · 단계는 그대로(장벽 보고가 그것으로 나간다) · 155"""
        self.manager._update_status({
            'message': f'그룹 모션 {cycle_number}회차 완료 · 회차 후 정지 대기 · 다른 PC 회차 끝 기다림',
            'group_stop_after_cycle': True,
        })

    def prepare(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare one persistent group session without enabling local repeat.

        `join_cycle_number` (수정 목록 30-3) · 도는 그룹에 **복귀**하는 PC · 계획만
        만들고 움직이지 않는다 · 진행 PC 가 합류를 확정하면(`commit_join`) 다른 PC 와
        같이 다음 회차 초기 위치로 가서 다음 회차부터 같이 돈다.
        """
        execution_id = str(payload.get('execution_id') or '').strip()
        initialize_monotonic = finite_float(
            payload.get('initialize_monotonic')
        )
        try:
            join_cycle = int(payload.get('join_cycle_number') or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError('복귀 회차 번호가 올바르지 않습니다') from exc
        if not execution_id:
            raise ValueError('그룹 execution_id가 필요합니다')
        if join_cycle < 0:
            raise ValueError('복귀 회차 번호가 올바르지 않습니다')
        if not join_cycle and (
            initialize_monotonic is None or initialize_monotonic <= time.monotonic()
        ):
            raise ValueError('그룹 초기 위치 이동 예약 트리거가 이미 지났습니다')
        with self.manager._run_lock:
            # 같은 execution_id의 재요청은 슬롯 경쟁이 아니라 중복 전달이다 ·
            # 그룹 명령은 여러 PC가 같은 트리거를 받으므로 재전송이 정상이다.
            if (
                self.manager._run_thread is not None
                and self.manager._run_thread.is_alive()
                and self.session.get('execution_id') == execution_id
            ):
                return {
                    'success': True,
                    'duplicate': True,
                    'message': '이미 준비 중인 그룹 실행 세션',
                    'status': self.manager.status(),
                }
            try:
                motors_snapshot = self.manager._claim_run_slot()
            except motion_run_rules.RunSlotUnavailable as exc:
                return {
                    'success': False,
                    'message': str(exc),
                    'status': self.manager.status(),
                }
            self.session = {
                'active': True,
                'execution_id': execution_id,
                'state': 'join_preparing' if join_cycle else 'preparing',
                'cycle_number': join_cycle,
                'join_cycle_number': join_cycle,
                'join_committed_cycle': 0,
                'next_start_at': 0.0,
                'next_cycle_number': 0,
                'next_initialize_at': 0.0,
                'next_initialize_cycle_number': 0,
                'stop_after_cycle': False,
            }
            status = motion_run_rules._empty_status()
            status.update({
                'state': 'preparing',
                'phase': 'group_preparing',
                'message': '그룹 실행 계획 생성 중',
                'group_execution': True,
                'execution_id': execution_id,
                'project_id': str(payload.get('project_id') or ''),
                'motion_file_id': str(payload.get('motion_file_id') or ''),
                'mapping_file_id': str(payload.get('mapping_file_id') or ''),
                'request_source': 'group_control',
                'phase_started_at': time.time(),
            })
            self.manager._set_status(status)
            self.manager._run_thread = threading.Thread(
                target=self._run,
                args=(dict(payload), list(motors_snapshot)),
                name=f'group-motion-{execution_id[:24]}',
                daemon=True,
            )
            self.manager._run_thread.start()
        return {
            'success': True,
            'message': '그룹 실행 준비 시작',
            'execution_id': execution_id,
            'status': self.manager.status(),
        }

    def commit_join(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """복귀 확정 · 진행 PC 가 이 PC 를 참가 목록에 넣었다 · 수정 목록 30-3

        `cycle_number` = 그룹이 방금 끝낸 회차 · 이 PC 도 그 회차를 끝낸 것처럼
        서서 다음 회차 초기화(`schedule_initialization`)를 같이 받는다.
        """
        execution_id = str(payload.get('execution_id') or '').strip()
        try:
            cycle_number = int(payload.get('cycle_number'))
        except (TypeError, ValueError) as exc:
            raise ValueError('그룹 회차 번호가 필요합니다') from exc
        if cycle_number < 1:
            raise ValueError('복귀 회차 번호가 올바르지 않습니다')
        with self.condition:
            session = self.session
            if not session.get('active') or session.get('execution_id') != execution_id:
                raise ValueError('활성 그룹 실행 세션이 일치하지 않습니다')
            if int(session.get('join_committed_cycle') or 0) == cycle_number:
                return {
                    'success': True, 'duplicate': True,
                    'message': '이미 확정된 복귀', 'status': self.manager.status(),
                }
            if session.get('state') != 'join_ready':
                raise ValueError('복귀 준비가 끝나지 않아 합류를 확정할 수 없습니다')
            # 상태도 여기서 바꾼다 · 바로 뒤따르는 회차 초기화 명령이 작업
            # 스레드가 깨기 전에 와도 받아지게
            session.update({
                'join_committed_cycle': cycle_number,
                'cycle_number': cycle_number,
                'state': 'motion_completed',
            })
            self.condition.notify_all()
        return {
            'success': True,
            'message': f'복귀 · {cycle_number + 1}회차부터 합류',
            'execution_id': execution_id,
            'cycle_number': cycle_number,
            'status': self.manager.status(),
        }

    def schedule_initialization(
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        execution_id = str(payload.get('execution_id') or '').strip()
        initialize_monotonic = finite_float(payload.get('initialize_monotonic'))
        try:
            cycle_number = int(payload.get('cycle_number'))
        except (TypeError, ValueError) as exc:
            raise ValueError('그룹 회차 번호가 필요합니다') from exc
        if initialize_monotonic is None or initialize_monotonic <= time.monotonic():
            raise ValueError('그룹 회차 초기화 트리거가 이미 지났습니다')
        with self.condition:
            session = self.session
            if not session.get('active') or session.get('execution_id') != execution_id:
                raise ValueError('활성 그룹 실행 세션이 일치하지 않습니다')
            if session.get('state') not in {
                'motion_completed', 'cycle_initialize_scheduled',
            }:
                raise ValueError('그룹 회차 초기화를 예약할 수 있는 상태가 아닙니다')
            if cycle_number != int(session.get('cycle_number') or 0):
                raise ValueError('그룹 회차 초기화 번호가 일치하지 않습니다')
            existing_cycle = int(
                session.get('next_initialize_cycle_number') or 0
            )
            existing_at = float(session.get('next_initialize_at') or 0.0)
            if existing_cycle:
                if (
                    existing_cycle == cycle_number
                    and existing_at == float(initialize_monotonic)
                ):
                    return {
                        'success': True,
                        'duplicate': True,
                        'message': '이미 예약된 그룹 회차 초기화 명령',
                        'status': self.manager.status(),
                    }
                raise ValueError('다른 그룹 회차 초기화 명령이 이미 예약되었습니다')
            session.update({
                'next_initialize_cycle_number': cycle_number,
                'next_initialize_at': float(initialize_monotonic),
                'state': 'cycle_initialize_scheduled',
            })
            self.condition.notify_all()
        return {
            'success': True,
            'message': f'그룹 모션 {cycle_number}회차 후 초기화 예약',
            'execution_id': execution_id,
            'cycle_number': cycle_number,
            'initialize_monotonic': float(initialize_monotonic),
            'status': self.manager.status(),
        }

    def schedule_cycle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        execution_id = str(payload.get('execution_id') or '').strip()
        start_monotonic = finite_float(payload.get('start_monotonic'))
        try:
            cycle_number = int(payload.get('cycle_number'))
        except (TypeError, ValueError) as exc:
            raise ValueError('그룹 회차 번호가 필요합니다') from exc
        if start_monotonic is None or start_monotonic <= time.monotonic():
            raise ValueError('그룹 모션 시작 트리거가 이미 지났습니다')
        with self.condition:
            session = self.session
            if not session.get('active') or session.get('execution_id') != execution_id:
                raise ValueError('활성 그룹 실행 세션이 일치하지 않습니다')
            if session.get('state') not in {'armed', 'cycle_ready', 'start_scheduled'}:
                raise ValueError('그룹 모션 시작을 예약할 수 있는 상태가 아닙니다')
            expected = int(session.get('cycle_number') or 0) + 1
            if cycle_number != expected:
                raise ValueError(f'그룹 모션 회차가 일치하지 않습니다: 예상 {expected}')
            existing_cycle = int(session.get('next_cycle_number') or 0)
            existing_start = float(session.get('next_start_at') or 0.0)
            if existing_cycle:
                if existing_cycle == cycle_number and existing_start == float(start_monotonic):
                    return {
                        'success': True,
                        'duplicate': True,
                        'message': '이미 예약된 그룹 모션 시작 명령',
                        'status': self.manager.status(),
                    }
                raise ValueError('다른 그룹 모션 시작 명령이 이미 예약되었습니다')
            session.update({
                'next_cycle_number': cycle_number,
                'next_start_at': float(start_monotonic),
                'state': 'start_scheduled',
            })
            self.condition.notify_all()
        return {
            'success': True,
            'message': f'그룹 모션 {cycle_number}회차 시작 예약',
            'execution_id': execution_id,
            'cycle_number': cycle_number,
            'start_monotonic': float(start_monotonic),
            'status': self.manager.status(),
        }

    def cancel(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        execution_id = str(payload.get('execution_id') or '').strip()
        # 끝까지 돈 1회 · 회차 후 정지도 마스터가 이 길로 세션을 정리한다 · 그때 「완료」 를 「취소」 로 덮어
        # 끝까지 돈 재생이 실패처럼 보였다(2026-10-12 H-52) · 끝난 뒤 정리면 완료로 둔다 · 수정 목록 112 마
        finished = str(self.manager.status().get('state') or '') in ('completed', 'motion_completed')
        with self.condition:
            if execution_id and self.session.get('execution_id') != execution_id:
                raise ValueError('취소하려는 그룹 실행 세션이 일치하지 않습니다')
            # 회차 후 정지(스케줄 구간 끝 · 사람이 누른 회차 후 정지) 뒤의 정리도 이 길이다 · 그것을
            # 「그룹 실행 취소」 로 덮어 구간 끝 정상 정지가 실패처럼 읽혔다(실물 S-11 · 2026-10-14) · 수정 목록 141
            after_cycle_text = self.after_cycle_stop_message()
            self.manager._stop_event.set()
            self.session.update({'active': False, 'state': 'stopped'})
            self.condition.notify_all()
            worker = getattr(self.manager, '_run_thread', None)
        # Do not report the group session as released until its worker has
        # observed cancellation. Starting another group session earlier races
        # the shared stop event and causes "previous motion run task" errors.
        if (
            worker is not None and worker.is_alive()
            and worker is not threading.current_thread()
        ):
            worker.join(timeout=5.0)
        if worker is not None and worker.is_alive():
            return {
                'success': False,
                'message': '이전 그룹 실행 정리 중입니다. 잠시 후 다시 시도하세요',
                'status': self.manager.status(),
            }
        # 회차 후 정지가 먼저 · 회차 맞춤은 장벽(`motion_completed`)에서 이 풀기를 기다린다 · 끝 문구는 회차 후 정지 · 154
        if after_cycle_text:
            self.manager._update_status({
                'state': 'stopped',
                'phase': 'stopped',
                'message': after_cycle_text,
                'phase_finished_at': time.time(),
            })
            return {'success': True, 'message': f'{after_cycle_text} · 세션 정리', 'status': self.manager.status()}
        if finished:
            self.manager._update_status({
                'state': 'completed',
                'phase': 'completed',
                'message': '그룹 실행 완료',
            })
            return {'success': True, 'message': '그룹 실행 완료 · 세션 정리', 'status': self.manager.status()}
        self.manager._update_status({
            'state': 'stopped',
            'phase': 'stopped',
            'message': '그룹 실행 취소',
            'phase_finished_at': time.time(),
        })
        return {'success': True, 'message': '그룹 실행 취소', 'status': self.manager.status()}

    def _prepare_plans(
        self, payload: Dict[str, Any], motors_snapshot: List[Dict[str, Any]],
    ) -> tuple:
        """초기 위치 이동 예약 시각 **전에** 하는 일 · (연속, 각자, 1회차 계획, 초기 위치 계획, 재생 목록)

        예약 시각은 그룹 준비를 받은 때 + 1.5~3 s 다 · 이 안에 끝나야 한다 · 수정 목록 164

        - 1회차 재생 계획 하나 · 초기 위치 계획 하나만 짓는다 · 둘 다 준비 검사(`check`)가 지어 둔
          재료(읽은 파일 · 20 ms 재샘플)를 다시 쓴다(`PlanBuilder` 캐시)
        - 「검증 계획」 을 따로 짓지 않는다 · 옛 길은 같은 요청으로 세 번 지었다 · 검증 계획이 따로
          보던 이음매 값 차이는 막지 않기로 했다(§6-142 · 검사 함수가 빈 사유만 돌려준다) ·
          그 검사는 재생 계획으로 한다
        - 재생 목록 2번부터는 뒤에서 짓는다(`DeferredPlaylist`) · 처음 쓰일 때 기다린다 ·
          짓기 시작은 1회차가 시작되고 나서다(`DEFERRED_BUILD_DELAY_SEC`) · 여기서는 만들기만 · 171
        """
        # 회차 맞춤 / 각자 재생 · 수정 목록 35
        continuous = (
            not payload.get('initialization_only')
            and str(payload.get('run_mode') or 'once') == 'continuous'
        )
        independent = continuous and (
            repeat_policy.normalize_group_sync_mode(payload.get('sync_mode'))
            == repeat_policy.GROUP_INDEPENDENT
        )
        motion_payload = {
            **payload,
            # 각자 재생은 1회차 시작 뒤 이 PC 가 혼자 잇는다 · 로컬 연속 재생과 같은 길
            'run_mode': 'continuous' if independent else 'once',
            'automation_run': False,
            'group_execution': True,
            'request_source': 'group_control',
            'scheduled_start_at': 0.0,
            'synchronized_cycle_sec': 0.0,
            'synchronized_repeat_count': 0,
        }
        builder = self.manager._plan_builder
        plan = builder.build(motion_payload, motors_snapshot=motors_snapshot)
        guard_error = motion_run_rules._motion_auto_start_guard_error(plan)
        if guard_error:
            raise ValueError(guard_error)
        initialization_plan = builder.build(
            motion_payload,
            initialization_only=True,
            motors_snapshot=motors_snapshot,
        )
        playlist: Any = []
        if continuous:
            player = self.manager._player
            names = player._playlist_names(plan, require_continuous=False)
            if names:
                first = (
                    {**plan, **player._playlist_marks(0, names)},
                    {**initialization_plan, **player._playlist_marks(0, names)},
                )
                stop_event = self.manager._stop_event
                playlist = DeferredPlaylist(
                    first,
                    len(names),
                    lambda: player._build_playlist_entries(
                        motion_payload, plan, initialization_plan, motors_snapshot,
                        require_continuous=False, should_stop=stop_event.is_set,
                    ),
                    stop_event=stop_event,
                    name=f'group-playlist-{str(payload.get("execution_id") or "")[:20]}',
                )
                plan, initialization_plan = playlist[0]
        return continuous, independent, plan, initialization_plan, playlist

    def _run(
        self, payload: Dict[str, Any], motors_snapshot: List[Dict[str, Any]]
    ) -> None:
        execution_id = str(payload.get('execution_id') or '')
        try:
            continuous, independent, plan, initialization_plan, playlist = self._prepare_plans(
                payload, motors_snapshot,
            )
            if self.manager._stop_event.is_set():
                return
            join_cycle = int(payload.get('join_cycle_number') or 0)
            cycle_number = 0
            if join_cycle:
                # 복귀 · 계획만 만들고 서 있는다 · 모터는 아직 움직이지 않는다 · 30-3 ·
                # 재생 목록도 다 짓고 나서 「복귀 준비」 를 알린다 · 예약 시각에 쫓기지 않는 자리 · 164
                if isinstance(playlist, DeferredPlaylist):
                    playlist.wait()
                committed = self._wait_join_commit(execution_id, join_cycle)
                if committed is None:
                    return
                cycle_number = committed
            else:
                self.manager._wait_group_deadline(
                    float(payload['initialize_monotonic']),
                    phase='group_initialize_scheduled',
                    message='그룹 초기 위치 이동 시작 대기',
                    execution_id=execution_id,
                )
                initialize_triggered_at = time.time()
                initialize_triggered_monotonic = time.monotonic()
                # 재생이 뒤따르면 첫 프레임까지 잇는다 · 그룹 「초기 위치 이동」 만이면 초기 위치에 선다 · 13-1
                self.manager._player._run_initialization({
                    **initialization_plan,
                    'blend_to_first_frame': not payload.get('initialization_only'),
                })
                if self.manager._stop_event.is_set() or self.manager.status().get('state') != 'initialized':
                    return
                # 재생 목록 2번부터는 아직 안 짓는다 · 1회차가 시작된 뒤에 · 깨진 파일은 1회차 도중에
                # 알게 되고 그 파일을 쓰기 전(회차 끝)에 멈춘다 · 171
                with self.condition:
                    self.session.update({
                        'state': 'armed',
                        'initialize_triggered_at': initialize_triggered_at,
                        'initialize_triggered_monotonic': (
                            initialize_triggered_monotonic
                        ),
                    })
                self.manager._update_status({
                    'state': 'armed',
                    'phase': 'group_armed',
                    'message': '그룹 초기 위치 이동 완료 · 모션 시작 대기',
                    'group_execution': True,
                    'execution_id': execution_id,
                    'initialize_triggered_at': initialize_triggered_at,
                    'initialize_triggered_monotonic': (
                        initialize_triggered_monotonic
                    ),
                })
            # 복귀한 PC 는 그룹이 막 끝낸 회차에서 들어온다 · 첫 바퀴는 재생 없이
            # 바로 다음 회차 초기화를 기다린다
            if join_cycle and not self._initialize_next_cycle(
                execution_id, cycle_number, playlist, initialization_plan,
            ):
                return
            while not self.manager._stop_event.is_set():
                scheduled = self._wait_cycle(execution_id)
                if scheduled is None:
                    break
                cycle_number, start_at = scheduled
                self.manager._wait_group_deadline(
                    start_at,
                    phase='group_start_scheduled',
                    message=f'그룹 모션 {cycle_number}회차 시작 대기',
                    execution_id=execution_id,
                    cycle_number=cycle_number,
                )
                if self.manager._stop_event.is_set():
                    break
                if isinstance(playlist, DeferredPlaylist):
                    # 1회차 시작 · 시작 보고가 나간 뒤에 2번부터 짓는다 · 두 번째부터는 아무 일 없음 · 171
                    playlist.start(DEFERRED_BUILD_DELAY_SEC)
                group_context = {
                    'scheduled_start_at': 0.0,
                    'group_execution': True,
                    'execution_id': execution_id,
                    'group_cycle_number': cycle_number,
                }
                if independent:
                    self._run_independent(
                        plan, initialization_plan, playlist, group_context,
                    )
                    return
                if playlist:
                    plan = playlist[(cycle_number - 1) % len(playlist)][0]
                plan = {**plan, **group_context}
                self.manager._player._run_motion(plan)
                result = self.manager.status()
                if result.get('state') == 'error' or self.manager._stop_event.is_set():
                    break
                # 다음 회차 애니 계획 · 뒤에서 짓던 것이 아직이면 **회차 끝을 알리기 전에** 기다린다 · 164
                #
                # 회차 사이 초기화 예약(`cycle_initialize_at`)은 지금 + 1.5 s 다 · 그 안에서 기다리면 예약
                # 시각을 놓친다. 여기서 기다리면 다른 PC 가 장벽에서 조금 더 기다릴 뿐이다.
                # 1회차가 짓기보다 짧으면 이 기다림이 길어진다(짓기는 1회차 시작 뒤에 시작 · 171) · 장벽에는
                # 제한시간이 없고 모두 마지막 프레임에 서 있다 · 다 지은 뒤에야 회차 끝을 알리므로
                # `cycle_initialize_at` 확인은 짓기와 겹치지 않는다.
                if isinstance(playlist, DeferredPlaylist):
                    playlist.wait()
                triggered_at = float(
                    (result.get('lifecycle') or {}).get('motion_started_at') or 0.0
                )
                self.manager._update_status({
                    'state': 'motion_completed',
                    'phase': 'group_motion_completed',
                    'message': f'그룹 모션 {cycle_number}회차 완료',
                    'group_execution': True,
                    'execution_id': execution_id,
                    'cycle_count': cycle_number,
                    'current_cycle': cycle_number,
                    'group_cycle_number': cycle_number,
                    'cycle_triggered_at': triggered_at,
                })
                with self.condition:
                    self.session.update({
                        'state': 'motion_completed',
                        'cycle_number': cycle_number,
                    })
                    stop_after_cycle = bool(self.session.get('stop_after_cycle'))
                    stop_wait = stop_after_cycle and bool(self.session.get('stop_after_cycle_group'))
                if stop_after_cycle and not stop_wait:
                    # 이 PC 만의 회차 후 정지 · 진행 PC 는 모른다 · 멈춰서 「먼저 정지」 로 알린다
                    self._finish(self.after_cycle_stop_message() or GROUP_AFTER_CYCLE_STOP_MESSAGE)
                    return
                if stop_wait:
                    # 그룹 전체 회차 후 정지 · 장벽(`motion_completed`)에 머문다 · 진행 PC 가 모든 PC 회차 끝을
                    # 보고 풀기(`cancel`)를 보낸다 · 그때 끝 문구 · 1회 재생과 같은 길 · 수정 목록 154
                    self._mark_stop_wait(cycle_number)
                if not self._initialize_next_cycle(
                    execution_id, cycle_number, playlist, initialization_plan,
                ):
                    break
        except InterruptedError:
            pass
        except Exception as exc:
            if not self.manager._stop_event.is_set():
                self.manager.get_logger().error(
                    f'group motion execution failed\n{traceback.format_exc()}'
                )
                self.manager._update_status({
                    'state': 'error',
                    'phase': 'error',
                    'message': f'그룹 모션 실행 실패: {exc}',
                    'group_execution': True,
                    'execution_id': execution_id,
                    'phase_finished_at': time.time(),
                })
        finally:
            # 회차 사이(초기 위치 · 시작 대기)에 받은 회차 후 정지도 여기서 끝난다 · 같은 끝 문구 · 수정 목록 141
            after_cycle_text = self.after_cycle_stop_message()
            with self.condition:
                if self.session.get('execution_id') == execution_id:
                    self.session['active'] = False
                    if self.session.get('state') not in {'error', 'stopped'}:
                        self.session['state'] = str(self.manager.status().get('state') or 'stopped')
                self.condition.notify_all()
            if (
                self.manager._stop_event.is_set()
                and self.manager.status().get('state') not in {'stopped', 'error'}
            ):
                self.manager._update_status({
                    'state': 'stopped',
                    'phase': 'stopped',
                    'message': after_cycle_text or '그룹 실행 정지',
                    'phase_finished_at': time.time(),
                })

    def _initialize_next_cycle(
        self,
        execution_id: str,
        cycle_number: int,
        playlist: List[tuple],
        initialization_plan: Dict[str, Any],
    ) -> bool:
        """회차가 끝난 뒤 · 다음 회차 초기화 명령을 기다렸다가 초기 위치로 · 실패·정지면 거짓

        끝난 회차의 PC 와 복귀한 PC(수정 목록 30-3)가 같은 길을 탄다.
        """
        scheduled_initialize = self._wait_initialization(
            execution_id,
        )
        if scheduled_initialize is None:
            return False
        initialized_cycle, initialize_at = scheduled_initialize
        if playlist:
            # 다음 회차 애니의 첫 프레임으로 · 회차 N 다음은 목록의 N 번째
            initialization_plan = playlist[
                initialized_cycle % len(playlist)
            ][1]
        initialization_plan = {
            **initialization_plan,
            'group_execution': True,
            'execution_id': execution_id,
            'group_cycle_number': initialized_cycle,
        }
        self.manager._wait_group_deadline(
            initialize_at,
            phase='group_cycle_initialize_scheduled',
            message=f'그룹 모션 {initialized_cycle}회차 후 초기화 대기',
            execution_id=execution_id,
            cycle_number=initialized_cycle,
        )
        if self.manager._stop_event.is_set():
            return False
        self.manager._player._run_initialization({
            **initialization_plan, 'blend_to_first_frame': True,
        })
        if self.manager._stop_event.is_set() or self.manager.status().get('state') != 'initialized':
            return False
        with self.condition:
            self.session.update({
                'state': 'cycle_ready',
                'cycle_number': cycle_number,
                'next_start_at': 0.0,
                'next_cycle_number': 0,
            })
        self.manager._update_status({
            'state': 'cycle_ready',
            'phase': 'group_cycle_initialized',
            'message': f'그룹 모션 {cycle_number}회차 후 초기화 완료',
            'group_execution': True,
            'execution_id': execution_id,
            'cycle_count': cycle_number,
            'current_cycle': cycle_number,
            'group_cycle_number': cycle_number,
        })
        return True

    def _run_independent(
        self,
        plan: Dict[str, Any],
        initialization_plan: Dict[str, Any],
        playlist: List[tuple],
        group_context: Dict[str, Any],
    ) -> None:
        """각자 재생 · 1회차 시작 시각만 그룹이 정했다 · 그 뒤는 이 PC 혼자 · 수정 목록 35

        로컬 연속 재생과 같은 길(`_run_motion`)을 탄다 · 회차 사이 동작·재생
        목록·목표 회차도 같다. 회차 후 정지는 `_graceful_stop_event` 로 오고
        이 PC 의 현재 애니가 끝나면 멈춘다 · 끝나면 「정지」를 알려 조정 PC 가
        모두 멈춘 것을 보고 그룹을 푼다.
        """
        with self.condition:
            self.session['independent'] = True
        marks = {**group_context, 'independent_group': True}
        # 뒤에서 짓는 목록이면 다 기다리지 않고 쓸 때 본다 · 1번은 바로 있다 · 164
        entries = (
            playlist.map(lambda entry: ({**entry[0], **marks}, {**entry[1], **marks}))
            if isinstance(playlist, DeferredPlaylist)
            else [
                ({**item_plan, **marks}, {**item_init, **marks})
                for item_plan, item_init in playlist
            ]
        )
        run_plan = entries[0][0] if entries else {**plan, **marks}
        run_init = entries[0][1] if entries else {**initialization_plan, **marks}
        if not entries and run_plan.get('repeat_mode') not in {
            'reinitialize', 'dwell_reinitialize',
        }:
            run_init = None
        self.manager._player._run_motion(run_plan, run_init, entries or None)
        result = self.manager.status()
        if result.get('state') == 'error' or self.manager._stop_event.is_set():
            return
        default = (
            str(result.get('message') or '')
            if result.get('state') == 'stopped'
            else '각자 재생 · 현재 회차 완료 후 정지'
        )
        # 스케줄 구간 끝이면 그 문구 · 수정 목록 141
        self._finish(
            SCHEDULE_END_STOP_MESSAGE
            if self.after_cycle_stop_message(default) == SCHEDULE_END_STOP_MESSAGE
            else default
        )

    def _wait_join_commit(self, execution_id: str, join_cycle: int) -> Optional[int]:
        """복귀 · 계획을 다 만들었다고 알리고 진행 PC 의 합류 확정을 기다린다 · 30-3"""
        with self.condition:
            if self.session.get('execution_id') != execution_id:
                return None
            self.session['state'] = 'join_ready'
        self.manager._update_status({
            'state': 'join_ready',
            'phase': 'group_join_ready',
            'message': '그룹 복귀 · 다음 회차부터 합류 대기',
            'group_execution': True,
            'execution_id': execution_id,
            'group_cycle_number': join_cycle,
        })
        with self.condition:
            while not self.manager._stop_event.is_set():
                if self.session.get('execution_id') != execution_id or not self.session.get('active'):
                    return None
                committed = int(self.session.get('join_committed_cycle') or 0)
                if committed > 0:
                    self.session['state'] = 'motion_completed'
                    break
                self.condition.wait(timeout=0.2)
            else:
                return None
        self.manager._update_status({
            'state': 'motion_completed',
            'phase': 'group_join_committed',
            'message': f'그룹 복귀 · {committed + 1}회차부터 합류',
            'group_execution': True,
            'execution_id': execution_id,
            'cycle_count': committed,
            'current_cycle': committed,
            'group_cycle_number': committed,
        })
        return committed

    def _wait_initialization(
        self, execution_id: str,
    ) -> Optional[tuple[int, float]]:
        with self.condition:
            while not self.manager._stop_event.is_set():
                if self.session.get('execution_id') != execution_id:
                    return None
                cycle = int(
                    self.session.get('next_initialize_cycle_number') or 0
                )
                initialize_at = float(
                    self.session.get('next_initialize_at') or 0.0
                )
                if cycle > 0 and initialize_at > 0.0:
                    self.session['state'] = 'cycle_initialize_scheduled'
                    self.session['next_initialize_cycle_number'] = 0
                    self.session['next_initialize_at'] = 0.0
                    return cycle, initialize_at
                self.condition.wait(timeout=0.2)
        return None

    def _wait_cycle(self, execution_id: str) -> Optional[tuple[int, float]]:
        with self.condition:
            while not self.manager._stop_event.is_set():
                if self.session.get('execution_id') != execution_id:
                    return None
                cycle = int(self.session.get('next_cycle_number') or 0)
                start_at = float(self.session.get('next_start_at') or 0.0)
                if cycle > 0 and start_at > 0.0:
                    self.session['state'] = 'start_scheduled'
                    return cycle, start_at
                self.condition.wait(timeout=0.2)
        return None

    def _finish(self, message: str) -> None:
        with self.condition:
            self.manager._stop_event.set()
            self.session.update({'active': False, 'state': 'stopped'})
            self.condition.notify_all()
            worker = getattr(self.manager, '_run_thread', None)
        if (
            worker is not None and worker.is_alive()
            and worker is not threading.current_thread()
        ):
            worker.join(timeout=5.0)
        self.manager._update_status({
            'state': 'stopped',
            'phase': 'stopped',
            'message': message,
            'phase_finished_at': time.time(),
        })
