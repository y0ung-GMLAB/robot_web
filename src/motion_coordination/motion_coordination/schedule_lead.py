"""그룹 예약 명령의 여유(lead) · 잰 확인 시간으로 정한다 · 수정 목록 130

진행 PC 는 `initialize_at` · `cycle_initialize_at` · `start_at` 을 「지금 + 여유」 시각으로 보내고,
그 시각 0.1 s 전(`schedule_ack_margin_sec`)까지 **모든 참가 PC 의 확인** 을 받아야 한다 ·
진행 PC 자신도 같다 · 제 명령을 DDS 로 다시 받아 → HTTP 로컬 브리지 → ROS 로 motion_run_manager →
답 → 사건 발행 · 이 길이 여유 안에 끝나야 한다.

전에는 여유가 늘 0.5 s 였다 · 확인 마감은 0.4 s · 그런데 `initialize_at` 은 PC 마다 `group_prepare`
(실행 세션 · 작업 스레드 · 관문 검사 · 파일 읽기)라 가볍지 않고, 서 있을 때도 파이썬 노드들이 1 kHz
모터 상태에 바빴다 · 실물(floating4 · 2026-10-13 19:20~19:26)에서 마스터 자신이 0.4 s 를 넘겨
「그룹 예약 확인 제한시간 초과 · floating4」 로 다섯 번 실패하고 그룹 오류로 잠겼다.

이제 · PC 마다 최근 확인 시간을 재 두고 여유 = max(설정값, 종류별 바닥, 최악 × 2 + 마감 여백) ·
위 한도 3 s · 모든 PC 가 **같은 시각** 에 트리거하는 것은 그대로라 트리거 편차 판정(70 ms)은
바뀌지 않는다 · 늦어지는 것은 출발 시각뿐(초기 위치 이동 5~10 s 앞 1~2 s).

수정 목록 153 · 회차 맞춤 그룹 회차 사이 `cycle_initialize_at` 도 바닥(1.5 s) · 따로 잰다 · 실물
2026-10-16 14:35 floating3(마스터 · 38 s 애니) · 자기 확인 253~363 ms · 여유 0.83 s → 한 번 튀어
「자신의 예약 확인 늦음」 → 그룹 취소 → 매장 약 40 s 멈춤 · 이제 그 회차만 마스터가 여유를 늘려
제 초기화를 다시 예약한다(`may_retry_own_cycle_initialize`) · 다른 PC 는 받은 시각 그대로.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Iterable, Mapping, Tuple

#: 예약 명령 → 잴 종류 · `initialize_at` 만 무겁다(`group_prepare`) · 회차 초기화는 따로 잰다 ·
#: `initialize` 와 섞으면 `group_prepare` 의 큰 값이 회차 사이 여유를 부풀린다 · 수정 목록 153 ①
SCHEDULED_COMMANDS: Mapping[str, str] = {
    'initialize_at': 'initialize',
    'cycle_initialize_at': 'cycle_initialize',
    'start_at': 'schedule',
}
#: 초기 위치 이동 예약의 바닥 · 이 PC 들의 `group_prepare` 가 0.4 s 를 넘긴 실물 기록 · 이동이
#: 5~10 s 라 1.5 s 앞당겨 보내도 쇼에는 안 보인다
INITIALIZE_LEAD_MIN_SEC = 1.5
#: 회차 초기화 예약의 바닥 · 회차 끝 마스터는 제 재생 기록 쓰기와 겹쳐 확인이 튄다(실물 253~363 ms ·
#: 한 번은 679 ms 안에 못 함) · 뒤는 초기 위치 이동 5~10 s 라 안 보인다 · 수정 목록 153 ①
CYCLE_INITIALIZE_LEAD_MIN_SEC = 1.5
#: 종류 → 바닥 · 없으면 0(설정값 · 잰 값만)
LEAD_FLOOR_SEC: Mapping[str, float] = {
    'initialize': INITIALIZE_LEAD_MIN_SEC,
    'cycle_initialize': CYCLE_INITIALIZE_LEAD_MIN_SEC,
}
#: 회차 초기화 · 마스터 자신만 늦으면 그룹 취소 대신 제 초기화를 다시 예약하는 횟수 · 넘으면 옛 그대로 취소
CYCLE_INITIALIZE_SELF_RETRIES = 2
#: 그 사이 마감 검사가 기다리는 상한(보낸 때부터) · 로컬 호출 4 s × (처음 + 다시 2) + 여유 · DDS 로 제 명령이
#: 안 돌아와도 끝은 난다
SELF_LATE_WAIT_MAX_SEC = 15.0
#: 잰 값이 아무리 커도 이 이상은 기다리지 않는다 · 넘으면 그 PC 가 고장 난 것 · 마감이 잡는다
LEAD_MAX_SEC = 3.0
#: 최악 확인 시간에 곱하는 수 · 한 번 튄 값의 두 배까지는 버틴다
LATENCY_SAFETY_FACTOR = 2.0
#: PC · 종류마다 들고 있을 최근 확인 시간 수
LATENCY_WINDOW = 8


def command_kind(command: str) -> str:
    """예약 명령의 종류 · 예약 명령이 아니면 빈 문자열"""
    return SCHEDULED_COMMANDS.get(str(command or ''), '')


class ScheduleLeadPlanner:
    """PC · 종류마다 최근 예약 확인 시간 · 다음 예약 여유를 정한다 · 순수 · 락은 부르는 쪽"""

    def __init__(self, *, window: int = LATENCY_WINDOW) -> None:
        self._window = max(int(window), 1)
        self._samples: Dict[Tuple[str, str], Deque[float]] = {}
        self.last_lead: Dict[str, float] = {}

    def record(self, kind: str, pc_id: str, latency_sec: float) -> None:
        """확인 시간 하나 · 명령을 보낸 때부터 답을 받은 때까지(늦은 답도 잰다)"""
        if not kind or not pc_id:
            return
        try:
            value = float(latency_sec)
        except (TypeError, ValueError):
            return
        if value != value or value < 0.0:
            return
        key = (str(kind), str(pc_id))
        bucket = self._samples.get(key)
        if bucket is None:
            bucket = deque(maxlen=self._window)
            self._samples[key] = bucket
        bucket.append(value)

    def worst(self, kind: str, participants: Iterable[str]) -> float:
        """참가 PC 들의 최근 최악 확인 시간 · 잰 적 없으면 0"""
        values = [
            max(self._samples[(kind, str(pc_id))])
            for pc_id in participants
            if self._samples.get((kind, str(pc_id)))
        ]
        return max(values) if values else 0.0

    def lead_sec(
        self, kind: str, participants: Iterable[str], *,
        base_lead_sec: float, ack_margin_sec: float,
    ) -> float:
        base = max(float(base_lead_sec), float(ack_margin_sec))
        floor = float(LEAD_FLOOR_SEC.get(str(kind), 0.0))
        measured = self.worst(kind, participants) * LATENCY_SAFETY_FACTOR + float(ack_margin_sec)
        ceiling = max(LEAD_MAX_SEC, base)
        lead = min(max(base, floor, measured), ceiling)
        self.last_lead[str(kind)] = lead
        return lead

    def snapshot(self) -> Dict[str, object]:
        """화면 · 진단용 · 종류 → PC → 최근 확인 ms"""
        table: Dict[str, Dict[str, list]] = {}
        # 락 없이 화면이 읽는다 · 한 번에 베껴 두고 돈다
        for (kind, pc_id), bucket in list(self._samples.items()):
            table.setdefault(kind, {})[pc_id] = [round(value * 1000.0, 1) for value in list(bucket)]
        return {
            'recent_ack_ms': table,
            'last_lead_sec': dict(self.last_lead),
        }


#: 예약이 **시간 때문에** 거절된 글 · 진행 PC 자신의 로컬 길이 늦은 것 · 고장이 아니다
#: (`_local_schedule_ns` · `GroupSession` 의 「이미 지났습니다」 · 브리지 → motion_run_manager 대기 초과)
TIMING_REJECTION_MARKERS = (
    '준비 여유가 부족합니다',
    '트리거가 이미 지났습니다',
    'motion_run_manager response timeout',
)


def is_timing_rejection(text: str) -> bool:
    value = str(text or '')
    return any(marker in value for marker in TIMING_REJECTION_MARKERS)


def only_self_late(missing: Iterable[str], pc_id: str, pending_command: str) -> bool:
    """예약 확인 마감에서 **진행 PC 자신만** 늦었나 · 예약 명령일 때만

    다른 PC 는 다 답했고 늦은 것은 이 PC 의 로컬 길(HTTP · ROS · 바쁜 CPU)뿐이다 · 망 · 상대 PC
    고장이 아니다 · 그룹 오류(2등급)로 잠그지 않고 이번 시작만 취소한다 · 다음 시작은 잰 값으로
    여유가 늘어난다 · 수정 목록 124 (준비 확인) 와 같은 원칙.
    """
    return bool(command_kind(pending_command)) and set(missing) == {str(pc_id)}


#: 예약을 **확실히 받지 않은** 거절 · 조정 노드의 여유 검사(`_local_schedule_ns`) · `GroupSession` 의
#: 「이미 지났습니다」 · 다시 예약해도 두 번 잡히지 않는다 · 「response timeout」 은 늦게라도 받았을 수 있어 뺀다
NOT_ACCEPTED_MARKERS = (
    '준비 여유가 부족합니다',
    '트리거가 이미 지났습니다',
)


def is_not_accepted_rejection(text: str) -> bool:
    value = str(text or '')
    return any(marker in value for marker in NOT_ACCEPTED_MARKERS)


def may_retry_own_cycle_initialize(command: str, message: str, attempts: int) -> bool:
    """진행 PC 자신의 회차 초기화 예약을 다시 할까 · 수정 목록 153 ②

    회차 사이 · 다른 PC 는 받은 시각에 초기 위치로 간다 · 마스터만 여유를 늘려 제 초기화를 늦게
    예약해도 다음 회차 시작(`start_at`)은 모두 초기화를 마친 뒤라 맞는다 · 그룹 취소(약 40 s 멈춤)보다
    낫다 · 받았는지 모르는 거절(응답 시간 초과)은 두 번 잡힐 수 있어 다시 하지 않는다.
    """
    return (
        str(command or '') == 'cycle_initialize_at'
        and is_not_accepted_rejection(message)
        and int(attempts) < CYCLE_INITIALIZE_SELF_RETRIES
    )
