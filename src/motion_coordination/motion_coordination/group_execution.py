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

from .participant_rules import STARTED_BY_SCHEDULE, normalize_started_by

#: PC 사이 메시지 약속 번호 · 메시지 칸을 바꿀 때마다 +1 · 수정 목록 30-7
#:
#: 1 · 칸 없음(옛 PC · 0 으로 읽힌다) · 2 · 2026-10-06 `GroupCommand.sync_mode` ·
#: `GroupHeartbeat.operation_mode`·`web_url`·`protocol_version` ·
#: 3 · 2026-10-06 `GroupCommand.stop_reason` (스케줄 끝 주차 · 수정 목록 36) ·
#: 4 · 2026-10-06 도는 그룹 복귀 · 명령 `join` · `update_participants` 가 참가자를 늘릴 수 있음 ·
#: 사건 `join_ready` (수정 목록 30-3) ·
#: 5 · 2026-10-07 `GroupCommand.motion_file_id`·`start_delay_sec` · PC 1대 재생도 `start_at` 알림
#: (스피커 연동 · 수정 목록 38) ·
#: 6 · 2026-10-12 `GroupCommand.initial_move_time_sec` (재생 화면 초기 이동 5/7/10 s) ·
#: 7 · 2026-10-13 칸은 같고 그룹 동작이 바뀜 · 누가 시작했나(`started_by` · 수동 PC 넣기 · 수정 목록 122) ·
#: 시작 전 미리 보기 · 뺀 PC 에만 보내는 풀기 명령 번호(123) · 도는 그룹 없이 구간 끝 주차(실행 ID 없는
#: `stop_after_cycle` · 수정 목록 36 후속) · 옛 PC 와 섞이면 그룹 동작이 갈린다 → 같은 버전끼리만 ·
#: 8 · 2026-10-14 `GroupHeartbeat.start_blocker`(실행 준비 안 됨 · 선택 때 미리 뺌) · 바쁜 마스터는 참가자에서
#: 빠진 채 진행만 한다(참가 PC 가 참가 목록 밖 진행 PC 를 받아들임) · 즉시 정지는 그 실행을 도는 PC 만
#: 세운다 · 진행 PC 는 제 `join` 을 처리하지 않는다 · 이미 놓은 실행의 풀기에는 「정지」 로 답한다(수정 목록 136)
#: 9 · 2026-10-14 칸은 같고 그룹 동작이 바뀜 · 웹 서비스가 정상 종료되면 `participant_left` 사건으로 그 PC 만
#: 빠진다 · 알림 없는 끊김도 2등급으로 잠그지 않는다(수정 목록 144 · 145) · 옛 진행 PC 는 새 사건을 몰라
#: 정지 + 2등급으로 갈린다 → 같은 버전끼리만 ·
#: 10 · 2026-10-16 `GroupCommand.segment_start_sec`·`segment_end_sec` (구간 재생 · 재생 목록 1번을 같은
#: 시각부터 · 스피커도 그 시각부터 음원) · 메시지 칸이 바뀜 → 로봇 PC · 스피커 모두 같은 버전 · 다시 빌드
GROUP_PROTOCOL_VERSION = 10

#: 진행 PC 가 **뺀 PC 하나에만** 보내는 풀기 명령의 번호 앞머리 · 수정 목록 123
#:
#: 약속상 참가 목록에 진행 PC 도 적혀야 해서(`_require_stop_command`) 진행 PC 자신도
#: 이 명령을 받는다 · 전에는 그것을 제 실행 취소로 처리해 제 쪽 `group_cancel` →
#: 「정지」 사건 → 제 실행을 `stopped` 로 두고 `execution_id` 는 남겼다 · 그래서 준비 중에
#: 다른 PC 가 거절하면 남은 마스터도 안 돌고 「이전 그룹 실행 정리 확인 중입니다」 에
#: 갇혔다(실물 S-11 · 2026-10-13 15:09 · 17 분) · 진행 PC 는 이 번호의 제 명령을 건너뛴다.
DROP_RELEASE_PREFIX = 'drop-release-'


def drop_release_command_id() -> str:
    return f'{DROP_RELEASE_PREFIX}{uuid.uuid4().hex}'


def is_own_drop_release(command: str, command_id: str, coordinator_id: str, pc_id: str) -> bool:
    """뺀 PC 에 보낸 풀기 명령이 진행 PC 자신에게 돌아왔나 · 그러면 처리하지 않는다"""
    return (
        str(command) == 'cancel_before_start'
        and str(command_id or '').startswith(DROP_RELEASE_PREFIX)
        and str(coordinator_id) == str(pc_id)
    )


def is_own_join(command: str, coordinator_id: str, pc_id: str) -> bool:
    """복귀 권유(`join`)가 진행 PC 자신에게 돌아왔나 · 그러면 처리하지 않는다 · 수정 목록 136

    약속상 참가 목록에 진행 PC 도 적혀 진행 PC 도 이 명령을 받는다 · 전에는 그것을 제 복귀로
    처리해 제 실행의 참가 목록을 {진행 PC, 복귀 PC} 로 덮어썼다 · 그래서 복귀 PC 의 거절이
    「참가 PC 의 명령 실패」 로 읽혀 도는 그룹이 통째로 섰다(실물 V-8 · 2026-10-14 09:31 · floating1).
    """
    return str(command) == 'join' and str(coordinator_id) == str(pc_id)


def late_refusal_reason(
    *, event: str, command_id: str, state: str,
    pending_command: str, pending_command_id: str, prepare_command_id: str,
) -> str:
    """진행 PC 가 받은 「거절」 이 늦게 온 것이라 무시할 것인가 · 그러면 이유 · 수정 목록 136 ③

    정리(`releasing`) 중에 온 거절은 그 PC 의 준비 · 예약 답이 늦게 온 것이다 · 그 PC 는 거절하면서
    실행을 이미 놓았거나 곧 올 풀기에 「정지」 로 답한다 · 전에는 이것을 「참가 PC 명령 실패」 로 읽어
    모든 참가 PC 에 즉시 정지를 보내고 그룹 오류로 잠갔다(실물 V-4 · floating2) · 풀기 명령 자체의
    거절(로컬 정리 실패일 수 있다)만 전처럼 본다 · 준비 단계를 지난 뒤 온 준비 거절도 무시한다.
    """
    if str(event) != 'rejected':
        return ''
    if str(state) == 'releasing' or str(pending_command) == 'cancel_before_start':
        if command_id and str(command_id) == str(pending_command_id):
            return ''
        return '정리 중 늦은 거절'
    if prepare_command_id and str(command_id) == str(prepare_command_id) and str(state) != 'preparing':
        return '준비 단계 뒤 늦은 준비 거절'
    return ''


#: 끝난 실행(`stopped` · `error`)을 들고 있을 수 있는 최대 시간 · 수정 목록 123
#:
#: 정상 길은 끝나면 바로 `execution_id` 를 지운다 · 이 시간을 넘겨 남아 있으면 어느
#: 길에서 정리를 빠뜨린 것이다 · 그대로 두면 새 시작이 영영 「이전 그룹 실행 정리 확인
#: 중입니다」 로 거부된다(실물 S-11 · 17 분 · 「프로그램 다시 시작」 으로만 풀림) ·
#: 회차 후 정지 요청이 출발 직전(`start_scheduled`)에 와서 잠깐 `stopped` 였다가 시작 보고로
#: 다시 `running` 이 되는 길이 있어 몇 초는 기다린다.
STALE_LEASE_LIMIT_SEC = 20.0


class StaleLeaseWatch:
    """끝난 실행이 얼마나 오래 남아 있나 · 진행 PC 만 · 한도를 넘기면 참"""

    TERMINAL_STATES = frozenset({'stopped', 'error'})

    def __init__(self, limit_sec: float = STALE_LEASE_LIMIT_SEC) -> None:
        self.limit_sec = float(limit_sec)
        self._key: tuple = ()
        self._since = 0.0

    def observe(
        self, *, execution_id: str, state: str, coordinator: bool,
        releasing: bool, now: float,
    ) -> bool:
        if not execution_id or not coordinator or releasing or state not in self.TERMINAL_STATES:
            self._key = ()
            self._since = 0.0
            return False
        key = (execution_id, state)
        if key != self._key:
            self._key = key
            self._since = float(now)
            return False
        return float(now) - self._since >= self.limit_sec


#: 웹 서비스가 내려가기 전에 참가 PC 가 진행 PC 에 보내는 사건 · 「이 PC 빠짐」 · 수정 목록 145 ①
#:
#: 메시지 칸은 그대로다(`GroupEvent.event` 글자 값 하나 추가) · 약속 번호를 올리지 않는다 ·
#: 이 값을 모르는 옛 진행 PC 는 무시하고 전처럼(갑자기 끊김) 처리한다 · 동작이 갈리지 않고 옛 길로 돌아간다.
PARTICIPANT_LEFT_EVENT = 'participant_left'

#: 이 PC 의 웹 서비스가 갑자기 끊겨 그룹을 세웠다 · 잠그지 않는 기록 · 웹이 다시 뜨면 지운다 · 수정 목록 145 ②
BRIDGE_LOST_CODE = 'GROUP_LOCAL_BRIDGE_LOST'

#: 기동 뒤 이 시간 안에 로컬 Web Bridge 상태가 끊기는 것은 고장으로 잠그지 않는다 · 수정 목록 123·124
#:
#: 「프로그램 다시 시작」 은 웹 서비스와 연동 서비스를 같이 다시 띄운다 · 연동이 먼저 뜨고
#: 스케줄이 첫 점검에서 그룹 시작을 보내면, 아직 덜 뜬 브리지 상태가 끊겨
#: GROUP_PARTICIPANT_FAILURE 2등급으로 잠겼다(실물 S-11 다시 · 15:26) · 사람이 한 재시작이다.
BOOT_GRACE_SEC = 90.0
#: 「프로그램 다시 시작」 을 누른 뒤 브리지가 사라져도 잠그지 않는 시간
PLANNED_RESTART_GRACE_SEC = 120.0
#: 아직 아무것도 움직이지 않은 단계 · 여기서 브리지가 끊기면 취소만 한다(잠그지 않는다)
PRE_MOTION_STATES = frozenset({'idle', 'ready', 'preparing', 'stopped', 'error'})


def bridge_loss_while_moving(
    *, state: str, now: float, boot_monotonic: float, planned_restart_until: float,
) -> bool:
    """로컬 Web Bridge 상태가 끊겼을 때 「움직이던 중 끊김」 으로 볼 것인가

    참이면 모두 세우고 「웹 서비스 끊김으로 그룹 정지」 를 남긴다 · 거짓이면 조용히 정리만 한다 ·
    **어느 쪽도 그룹 오류(2등급)로 잠그지 않는다** · 수정 목록 145 ② · 전에는 참이면 잠갔다
    (`systemctl --user restart motion-control` 한 번에 「그룹 오류 해제」 를 눌러야 했다 · 실물 V-28 ④) ·
    사람이 누른 다시 시작 · 기동 직후 · 움직이기 전 단계는 정리만 한다 · 스케줄이 다음 점검에 다시 시작한다.
    """
    if planned_restart_until and now < planned_restart_until:
        return False
    if boot_monotonic and now - boot_monotonic < BOOT_GRACE_SEC:
        return False
    return str(state or '') not in PRE_MOTION_STATES


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
    #: 그 PC 가 지금 그룹을 시작할 수 없는 이유(설정 없음 · 모터 끊김 · 사람 조작 중) · 수정 목록 136
    start_blocker: str = ''


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
        #: 초기 위치 이동 시간 · 0 = PC마다 조인트 매핑 값 · 2026-10-12
        self.initial_move_time_sec = 0.0
        #: 구간 재생 · 파일 시각 · 0/0 = 통째로 · PC 마다 제 재생 목록 1번을 같은 시각으로 · 2026-10-16
        self.segment_start_sec = 0.0
        self.segment_end_sec = 0.0
        self.target_cycle_count = 0
        self.initialization_only = False
        #: 회차 맞춤(lockstep) / 각자 재생(independent) · 수정 목록 35
        self.sync_mode = GROUP_LOCKSTEP
        #: 각자 재생에서 제 회차를 끝내고 멈췄다고 알린 PC
        self.independent_stopped: set[str] = set()
        #: 이번 실행에서 뺀 PC 와 이유 · 미접속·알람·끔 모드·명단 외 · 수정 목록 30
        self.excluded: Dict[str, str] = {}
        #: 누가 시작했나 · 사람(human) · 스케줄(schedule) · 참가 · 복귀 규칙이 다르다 · 수정 목록 122
        self.started_by = STARTED_BY_SCHEDULE
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
        #: 예약 명령을 보낸 때 · 확인 시간 재기 · 수정 목록 130
        self.pending_published_at = 0.0
        self.motion_start_report_deadline = 0.0
        self.release_error = False
        #: 진행 PC · 이번 실행의 준비(`prepare`) 명령 번호 · 늦은 준비 거절을 가린다 · 수정 목록 136
        self.prepare_command_id = ''

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
        self.pending_published_at = 0.0
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
        initial_move_time_sec: float = 0.0,
        started_by: str = STARTED_BY_SCHEDULE,
        coordinator_participates: bool = True,
        segment_start_sec: float = 0.0,
        segment_end_sec: float = 0.0,
    ) -> str:
        """`coordinator_participates=False` · 진행 PC 가 바빠(단독 재생 · 사람 조작 · 준비 안 됨) 빠지고
        진행만 한다 · 참가 목록에 진행 PC 가 없다 · 수정 목록 136"""
        selected = tuple(sorted(set(str(value) for value in participants if str(value))))
        if not 1 <= len(selected) <= 8:
            raise ValueError('그룹 실행 참가 PC는 1~8대여야 합니다')
        if coordinator_participates and coordinator_id not in selected:
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
        self.initial_move_time_sec = max(float(initial_move_time_sec or 0.0), 0.0)
        self.segment_start_sec = max(float(segment_start_sec or 0.0), 0.0)
        self.segment_end_sec = max(float(segment_end_sec or 0.0), 0.0)
        self.started_by = normalize_started_by(started_by)
        self.state = 'preparing'
        return self.execution_id

    def exclude(self, reasons: Dict[str, str], *, allow_coordinator: bool = False) -> tuple[str, ...]:
        """참가자에서 뺀다 · 진행 PC 는 빼지 않는다 · 뺀 PC 목록을 돌려준다.

        1대가 고장이어도 나머지는 돈다 · 수정 목록 30 · 빠진 PC 가 남긴 준비·
        완료 표시도 같이 지워야 장벽이 나머지만 보고 넘어간다.

        `allow_coordinator` · 진행 PC 자신이 준비를 거절했을 때 · 진행만 하고 빠진다 · 수정 목록 136
        """
        drop = tuple(sorted(
            pc_id for pc_id in reasons
            if pc_id in self.participants and (allow_coordinator or pc_id != self.coordinator_id)
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

    def settle_after_exclude(self) -> str:
        """뺀 PC 만 기다리던 장벽을 넘긴다 · 넘긴 단계 이름(없으면 빈 값) · 수정 목록 145 ①

        도는 중에 PC 하나가 빠지면(웹 다시 시작) 남은 PC 는 그 단계 보고를 이미 끝냈을 수 있다 ·
        그러면 다음 사건이 오지 않아 장벽이 영영 안 넘어가고 제한시간 초과로 그룹이 선다 ·
        사건이 오면 넘기던 자리(`mark_*`)와 같은 규칙으로 여기서 넘긴다 · 그 뒤 할 일은 부르는 쪽.

        - `released` · 풀기 확인이 남은 PC 모두에게서 왔다 · 실행을 놓는다
        - `armed` · 초기 위치 완료 · 첫 회차 시작(또는 초기 위치만이면 끝)
        - `running` · 모션 시작 보고가 다 왔다 · 회차 번호를 올린다
        - `motion_completed` · 회차 완료 · 다음 회차 또는 정지
        - `cycle_ready` · 회차 초기화 완료 · 다음 회차 시작
        - `independent_stopped` · 각자 재생 · 남은 PC 가 다 멈췄다 · 그룹을 푼다
        """
        remaining = set(self.participants)
        if not remaining or not self.execution_id:
            return ''
        if self.pending_command_id and self.pending_acks >= remaining:
            if self.pending_command == 'cancel_before_start':
                return 'released'
            self.pending_command = ''
            self.pending_command_id = ''
            self.pending_ack_deadline = 0.0
            self.pending_scheduled_at = 0.0
            self.pending_published_at = 0.0
        if self.state == 'initializing' and self.armed >= remaining:
            if self.initialize_triggered.keys() >= remaining:
                values = [self.initialize_triggered[pc_id] for pc_id in remaining]
                self.last_initialize_spread_ms = (max(values) - min(values)) * 1000.0
            self.state = 'armed'
            return 'armed'
        if self.state == 'start_scheduled' and self.triggered.keys() >= remaining:
            values = [self.triggered[pc_id] for pc_id in remaining]
            self.last_start_spread_ms = (max(values) - min(values)) * 1000.0
            self.cycle_number += 1
            self.state = (
                'running_independent'
                if self.sync_mode == GROUP_INDEPENDENT and self.run_mode == 'continuous'
                else 'running'
            )
            return 'running'
        if self.state == 'running' and self.motion_completed >= remaining:
            self.state = 'motion_completed'
            if self.target_cycle_count > 0 and self.cycle_number >= self.target_cycle_count:
                self.request_stop_after_cycle()
            return 'motion_completed'
        if self.state == 'cycle_initializing' and self.cycle_initialized >= remaining:
            self.state = 'cycle_ready'
            return 'cycle_ready'
        if self.state == 'running_independent' and self.independent_stopped >= remaining:
            return 'independent_stopped'
        return ''

    def mark_ready(self, pc_id: str) -> None:
        self._participant(pc_id)
        if self.state != 'preparing':
            raise ValueError('준비 응답을 받을 수 있는 상태가 아닙니다')
        self.ready.add(pc_id)

    def initialize_action(self, *, now: float, lead_sec: Optional[float] = None) -> ScheduledAction:
        if self.ready != set(self.participants):
            raise ValueError('전체 PC 실행 준비가 완료되지 않았습니다')
        self.state = 'initializing'
        self.scheduled.clear()
        return ScheduledAction(
            'initialize_at', self.execution_id, 0,
            float(now) + self._lead(lead_sec),
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

    def start_action(self, *, now: float, lead_sec: Optional[float] = None) -> ScheduledAction:
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
            float(now) + self._lead(lead_sec),
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

    def cycle_initialize_action(self, *, now: float, lead_sec: Optional[float] = None) -> ScheduledAction:
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
            float(now) + self._lead(lead_sec),
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

    def _lead(self, lead_sec: Optional[float]) -> float:
        """예약 여유 · 진행 PC 가 잰 확인 시간으로 정해 넘긴다 · 없으면 설정값 · 수정 목록 130"""
        if lead_sec is None:
            return self.start_lead_sec
        return max(float(lead_sec), self.start_lead_sec)

    def _participant(self, pc_id: str) -> None:
        if pc_id not in self.participants:
            raise ValueError('그룹 실행 참가 PC가 아닙니다')
