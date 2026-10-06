"""Transport-independent state machine for one DDS group execution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

from motion_common.repeat_policy import (
    GROUP_INDEPENDENT,
    GROUP_LOCKSTEP,
    normalize_group_sync_mode,
)

#: PC 사이 메시지 약속 번호 · 메시지 칸을 바꿀 때마다 +1 · 수정 목록 30-7
#:
#: 1 · 칸 없음(옛 PC · 0 으로 읽힌다) · 2 · 2026-10-06 `GroupCommand.sync_mode` ·
#: `GroupHeartbeat.operation_mode`·`web_url`·`protocol_version` ·
#: 3 · 2026-10-06 `GroupCommand.stop_reason` (스케줄 끝 주차 · 수정 목록 36) ·
#: 4 · 2026-10-06 도는 그룹 복귀 · 명령 `join` · `update_participants` 가 참가자를 늘릴 수 있음 ·
#: 사건 `join_ready` (수정 목록 30-3)
GROUP_PROTOCOL_VERSION = 4


@dataclass
class Member:
    pc_id: str
    boot_id: str
    joined: bool
    is_master: bool
    state: str
    trigger_sync_state: str
    trigger_sync_uncertainty_ms: float
    alarm_grade: int
    received_monotonic: float
    sequence: int = 0
    display_name: str = ''
    git_branch: str = ''
    git_hash: str = ''
    git_message: str = ''
    motion_phase: str = ''
    motion_elapsed_sec: float = 0.0
    motion_duration_sec: float = 0.0
    motion_progress_ratio: float = 0.0
    current_cycle: int = 0
    display_step: str = ''
    #: 그 PC 의 운전 모드(스케줄·수동·오프) · 웹 주소 · 약속 번호 · 수정 목록 30-6·30-7
    operation_mode: str = ''
    web_url: str = ''
    protocol_version: int = 0


class MemberRegistry:
    def __init__(self, *, warning_timeout_sec: float = 1.5, timeout_sec: float = 3.0):
        self.warning_timeout_sec = float(warning_timeout_sec)
        self.timeout_sec = float(timeout_sec)
        self._members: Dict[str, Member] = {}
        self._seen_boot_ids: Dict[str, set[str]] = {}

    def is_outdated_boot_id(self, pc_id: str, boot_id: str) -> bool:
        """Check if this boot_id is an old one that we have already seen and moved on from."""
        current = self._members.get(pc_id)
        if current and current.boot_id != boot_id:
            if boot_id in self._seen_boot_ids.get(pc_id, set()):
                return True
        return False

    def update(self, member: Member) -> None:
        previous = self._members.get(member.pc_id)
        if previous and previous.boot_id == member.boot_id:
            if member.sequence and member.sequence <= previous.sequence:
                return
            if member.received_monotonic < previous.received_monotonic:
                return
        if member.pc_id not in self._seen_boot_ids:
            self._seen_boot_ids[member.pc_id] = set()
        self._seen_boot_ids[member.pc_id].add(member.boot_id)
        self._members[member.pc_id] = member

    def status(self, pc_id: str, *, now: Optional[float] = None) -> str:
        member = self._members.get(pc_id)
        if member is None:
            return 'offline'
        age = (time.monotonic() if now is None else float(now)) - member.received_monotonic
        if age >= self.timeout_sec:
            return 'offline'
        if age >= self.warning_timeout_sec:
            return 'warning'
        return 'online'

    def live_joined(self, *, now: Optional[float] = None) -> tuple[str, ...]:
        return tuple(sorted(
            pc_id for pc_id, member in self._members.items()
            if member.joined and self.status(pc_id, now=now) == 'online'
        ))

    def joined(self) -> tuple[str, ...]:
        """Return every explicitly joined member, including delayed members."""
        return tuple(sorted(
            pc_id for pc_id, member in self._members.items() if member.joined
        ))

    def member(self, pc_id: str) -> Optional[Member]:
        return self._members.get(pc_id)


@dataclass
class ScheduledAction:
    command: str
    execution_id: str
    cycle_number: int
    scheduled_at: float
    command_id: str = field(default_factory=lambda: f'cmd-{uuid.uuid4().hex}')


class GroupExecution:
    """Coordinator-side barrier state; it never executes a local motion itself."""

    def __init__(self, *, start_lead_sec: float = 0.5, max_start_spread_ms: float = 70.0):
        self.start_lead_sec = float(start_lead_sec)
        self.max_start_spread_ms = float(max_start_spread_ms)
        self.reset()

    def reset(self) -> None:
        self.execution_id = ''
        self.coordinator_id = ''
        self.participants: tuple[str, ...] = ()
        self.state = 'idle'
        self.cycle_number = 0
        self.ready: set[str] = set()
        self.armed: set[str] = set()
        self.initialize_triggered: Dict[str, float] = {}
        self.cycle_ready: set[str] = set()
        self.motion_completed: set[str] = set()
        self.cycle_initialized: set[str] = set()
        self.scheduled: set[str] = set()
        self.triggered: Dict[str, float] = {}
        self.stop_after_cycle = False
        self.run_mode = 'continuous'
        self.repeat_mode = 'reinitialize'
        self.dwell_sec = 0.0
        self.target_cycle_count = 0
        self.initialization_only = False
        #: 회차 맞춤(lockstep) / 각자 재생(independent) · 수정 목록 35
        self.sync_mode = GROUP_LOCKSTEP
        #: 각자 재생에서 제 회차를 끝내고 멈췄다고 알린 PC
        self.independent_stopped: set[str] = set()
        #: 이번 실행에서 뺀 PC 와 이유 · 미접속·알람·오프 모드·명단 외 · 수정 목록 30
        self.excluded: Dict[str, str] = {}
        #: 진행 PC · 도는 중에 복귀하는 PC · {pc_id: {'state': preparing|ready, 'since': monotonic}} · 30-3
        self.joining: Dict[str, Dict[str, object]] = {}
        #: 진행 PC · 이번 회차 경계에서 넣은 PC · 확정이 거절되면 빼고 나머지로 간다
        self.admitted: set[str] = set()
        #: 복귀하는 쪽 PC · 합류 확정을 기다리는 회차(0 = 아님) · 기다리기 시작한 시각
        self.join_cycle = 0
        self.join_started = 0.0
        self.last_start_spread_ms: Optional[float] = None
        self.last_initialize_spread_ms: Optional[float] = None
        self.pending_command = ''
        self.pending_command_id = ''
        self.pending_acks: set[str] = set()
        self.pending_ack_deadline = 0.0
        self.pending_scheduled_at = 0.0
        self.motion_start_report_deadline = 0.0
        self.release_error = False

    def activate_claim(
        self, execution_id: str, coordinator_id: str,
        participants: Iterable[str],
    ) -> None:
        """Accept one peer-owned execution as this node's active lease."""
        self.reset()
        self.execution_id = str(execution_id)
        self.coordinator_id = str(coordinator_id)
        self.participants = tuple(participants)
        self.state = 'preparing'

    def clear_active(self) -> None:
        """Release the active lease while keeping its final display state."""
        self.execution_id = ''
        self.coordinator_id = ''
        self.participants = ()
        self.pending_command = ''
        self.pending_command_id = ''
        self.pending_acks.clear()
        self.pending_ack_deadline = 0.0
        self.pending_scheduled_at = 0.0
        self.motion_start_report_deadline = 0.0
        self.release_error = False
        self.joining.clear()
        self.admitted.clear()
        self.join_cycle = 0
        self.join_started = 0.0

    def admit(self, pc_ids: Iterable[str]) -> tuple[str, ...]:
        """도는 실행에 복귀 PC 를 넣는다 · 다음 회차 초기화부터 같이 · 넣은 PC 목록 · 30-3"""
        added = tuple(sorted(
            str(pc_id) for pc_id in pc_ids
            if str(pc_id) and str(pc_id) not in self.participants
        ))
        if not added:
            return ()
        self.participants = tuple(sorted({*self.participants, *added}))
        for pc_id in added:
            self.excluded.pop(pc_id, None)
            self.joining.pop(pc_id, None)
        # 막 끝난 회차를 같이 끝낸 것으로 친다 · 회차 초기화 장벽이 넣은 PC 까지 보고 넘어가게
        self.motion_completed.update(added)
        self.admitted = set(added)
        return added

    def begin(
        self,
        coordinator_id: str,
        participants: Iterable[str],
        *,
        run_mode: str = 'continuous',
        repeat_mode: str = 'reinitialize',
        dwell_sec: float = 0.0,
        target_cycle_count: int = 0,
        initialization_only: bool = False,
        sync_mode: str = GROUP_LOCKSTEP,
    ) -> str:
        selected = tuple(sorted(set(str(value) for value in participants if str(value))))
        if not 1 <= len(selected) <= 8:
            raise ValueError('그룹 실행 참가 PC는 1~8대여야 합니다')
        if coordinator_id not in selected:
            raise ValueError('임시 진행 PC가 참가 목록에 없습니다')
        if self.execution_id:
            raise ValueError('이전 그룹 실행 정리 확인 중입니다')
        if self.state not in {'idle', 'stopped', 'error'}:
            raise ValueError('다른 그룹 실행이 진행 중입니다')
        self.reset()
        self.execution_id = f'exec-{uuid.uuid4().hex}'
        self.coordinator_id = coordinator_id
        self.participants = selected
        self.run_mode = str(run_mode)
        self.repeat_mode = str(repeat_mode)
        self.dwell_sec = float(dwell_sec)
        self.target_cycle_count = int(target_cycle_count)
        self.initialization_only = bool(initialization_only)
        self.sync_mode = normalize_group_sync_mode(sync_mode)
        self.state = 'preparing'
        return self.execution_id

    def exclude(self, reasons: Dict[str, str]) -> tuple[str, ...]:
        """참가자에서 뺀다 · 진행 PC 는 빼지 않는다 · 뺀 PC 목록을 돌려준다.

        1대가 고장이어도 나머지는 돈다 · 수정 목록 30 · 빠진 PC 가 남긴 준비·
        완료 표시도 같이 지워야 장벽이 나머지만 보고 넘어간다.
        """
        drop = tuple(sorted(
            pc_id for pc_id in reasons
            if pc_id in self.participants and pc_id != self.coordinator_id
        ))
        if not drop:
            return ()
        self.participants = tuple(
            pc_id for pc_id in self.participants if pc_id not in drop
        )
        for pc_id in drop:
            self.excluded[pc_id] = str(reasons[pc_id])
            self.admitted.discard(pc_id)
        for bucket in (
            self.ready, self.armed, self.cycle_ready, self.motion_completed,
            self.cycle_initialized, self.scheduled, self.independent_stopped,
            self.pending_acks,
        ):
            bucket.difference_update(drop)
        for table in (self.initialize_triggered, self.triggered):
            for pc_id in drop:
                table.pop(pc_id, None)
        return drop

    def mark_ready(self, pc_id: str) -> None:
        self._participant(pc_id)
        if self.state != 'preparing':
            raise ValueError('준비 응답을 받을 수 있는 상태가 아닙니다')
        self.ready.add(pc_id)

    def initialize_action(self, *, now: float) -> ScheduledAction:
        if self.ready != set(self.participants):
            raise ValueError('전체 PC 실행 준비가 완료되지 않았습니다')
        self.state = 'initializing'
        self.scheduled.clear()
        return ScheduledAction(
            'initialize_at', self.execution_id, 0,
            float(now) + self.start_lead_sec,
        )

    def mark_armed(self, pc_id: str, triggered_at: float = 0.0) -> None:
        self._participant(pc_id)
        if self.state not in {'initializing', 'armed'}:
            raise ValueError('초기 위치 완료를 받을 수 있는 상태가 아닙니다')
        self.armed.add(pc_id)
        if triggered_at > 0.0:
            self.initialize_triggered[pc_id] = float(triggered_at)
        if self.armed == set(self.participants):
            if self.initialize_triggered.keys() >= set(self.participants):
                values = list(self.initialize_triggered.values())
                self.last_initialize_spread_ms = (max(values) - min(values)) * 1000.0
            self.state = 'armed'

    def start_action(self, *, now: float) -> ScheduledAction:
        if self.state == 'armed':
            next_cycle = 1
        elif (
            self.state == 'cycle_ready'
            and self.cycle_initialized == set(self.participants)
        ):
            next_cycle = self.cycle_number + 1
        else:
            raise ValueError('전체 PC가 다음 모션을 시작할 준비가 되지 않았습니다')
        self.state = 'start_scheduled'
        self.cycle_ready.clear()
        self.motion_completed.clear()
        self.scheduled.clear()
        self.triggered.clear()
        return ScheduledAction(
            'start_at', self.execution_id, next_cycle,
            float(now) + self.start_lead_sec,
        )

    def mark_scheduled(self, pc_id: str, cycle_number: int) -> None:
        self._participant(pc_id)
        if self.state != 'start_scheduled' or cycle_number != self.cycle_number + 1:
            raise ValueError('시작 예약 회차가 일치하지 않습니다')
        self.scheduled.add(pc_id)

    def mark_triggered(self, pc_id: str, cycle_number: int, triggered_at: float) -> None:
        self._participant(pc_id)
        if cycle_number != self.cycle_number + 1:
            raise ValueError('모션 시작 회차가 일치하지 않습니다')
        self.triggered[pc_id] = float(triggered_at)
        if self.triggered.keys() >= set(self.participants):
            values = list(self.triggered.values())
            self.last_start_spread_ms = (max(values) - min(values)) * 1000.0
            self.cycle_number = cycle_number
            # 각자 재생 · 1회차를 같이 시작한 뒤로는 회차 장벽이 없다 · 수정 목록 35
            self.state = (
                'running_independent'
                if self.sync_mode == GROUP_INDEPENDENT and self.run_mode == 'continuous'
                else 'running'
            )

    @property
    def independent(self) -> bool:
        return self.state == 'running_independent'

    def mark_independent_stopped(self, pc_id: str) -> bool:
        """각자 재생 · 모든 PC 가 제 회차를 끝내고 멈췄으면 참.

        한 PC 가 먼저 멈췄다고 나머지를 끊지 않는다 · 회차 후 정지는 PC 마다
        제 애니가 끝나는 시각이 다르다.
        """
        self._participant(pc_id)
        self.independent_stopped.add(pc_id)
        return self.independent_stopped >= set(self.participants)

    def mark_cycle_ready(self, pc_id: str, cycle_number: int) -> None:
        self._participant(pc_id)
        if cycle_number != self.cycle_number:
            raise ValueError('준비 완료 회차가 일치하지 않습니다')
        self.cycle_ready.add(pc_id)
        if self.cycle_ready == set(self.participants):
            self.state = 'cycle_ready'

    def mark_motion_completed(self, pc_id: str, cycle_number: int) -> None:
        """Hold every participant at the motion-completed barrier."""
        self._participant(pc_id)
        if self.state != 'running' or cycle_number != self.cycle_number:
            raise ValueError('모션 완료 회차가 일치하지 않습니다')
        self.motion_completed.add(pc_id)
        if self.motion_completed == set(self.participants):
            self.state = 'motion_completed'
            if self.target_cycle_count > 0 and self.cycle_number >= self.target_cycle_count:
                self.request_stop_after_cycle()

    def cycle_initialize_action(self, *, now: float) -> ScheduledAction:
        """Schedule the next cycle's initialization only after all motions finish."""
        if (
            self.state != 'motion_completed'
            or self.motion_completed != set(self.participants)
        ):
            raise ValueError('전체 PC 모션 완료 전에는 회차 초기화를 시작할 수 없습니다')
        self.state = 'cycle_initializing'
        self.cycle_initialized.clear()
        self.scheduled.clear()
        return ScheduledAction(
            'cycle_initialize_at', self.execution_id, self.cycle_number,
            float(now) + self.start_lead_sec,
        )

    def mark_cycle_initialized(self, pc_id: str, cycle_number: int) -> None:
        self._participant(pc_id)
        if self.state != 'cycle_initializing' or cycle_number != self.cycle_number:
            raise ValueError('회차 초기화 완료 회차가 일치하지 않습니다')
        self.cycle_initialized.add(pc_id)
        if self.cycle_initialized == set(self.participants):
            self.state = 'cycle_ready'

    def request_stop_after_cycle(self) -> None:
        self.stop_after_cycle = True
        if self.state in {'preparing', 'initializing', 'armed', 'cycle_ready', 'start_scheduled'}:
            self.state = 'stopped'

    def stop_now(self, *, error: bool = False) -> None:
        self.state = 'error' if error else 'stopped'

    def trigger_within_tolerance(self) -> Optional[bool]:
        if self.last_start_spread_ms is None:
            return None
        return self.last_start_spread_ms <= self.max_start_spread_ms

    def initialize_within_tolerance(self) -> Optional[bool]:
        if self.last_initialize_spread_ms is None:
            return None
        return self.last_initialize_spread_ms <= self.max_start_spread_ms

    def _participant(self, pc_id: str) -> None:
        if pc_id not in self.participants:
            raise ValueError('그룹 실행 참가 PC가 아닙니다')
