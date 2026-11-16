"""그룹 예약 명령의 여유(lead) · 잰 확인 시간으로 정한다 · 수정 목록 130 · 207

진행 PC 는 `initialize_at` · `cycle_initialize_at` · `start_at` 을 「지금 + 여유」 시각으로 보내고,
그 시각 0.1 s 전(`schedule_ack_margin_sec`)까지 **모든 참가 PC 의 확인** 을 받아야 한다 · 모든 PC 가
**같은 시각** 에 트리거하는 것은 그대로라 트리거 편차 판정(70 ms)은 여유와 상관없다.

여유 = max(설정값(0.5 s), 종류별 바닥, 참가 PC 최근 최악 확인 시간 × 2 + 마감 여백) · 위 한도 `LEAD_MAX_SEC`.
잰 값은 PC 의 망 왕복 + 그 PC 연동 노드 → 재생 관리자 왕복이다 · 실제 망 지연이라 재는 것이 맞다.

**207 전** 에는 진행 PC 자신의 확인이 가장 느렸다 · 제 명령을 DDS 로 다시 받아 → HTTP 로컬 웹(매번 프로젝트 ·
매핑 YAML 읽기) → ROS → 재생 관리자 · 웹이 바쁘면 0.4~0.7 s 를 넘겨 「자신의 예약 확인 늦음」 으로 빠지거나
그룹이 취소됐다(130 · 153 · 171 · 179) · 그래서 바닥을 덧댔다(초기 위치 3 s · 1회차 시작 3 s · 회차 초기화
1.5 s) · 회차 초기화는 마스터만 여유를 늘려 다시 예약했다(153 ② · 2번 · 기다림 15 s).
**이제** 진행 PC 자신의 예약은 이 프로세스 안에서 재생 관리자에 바로 간다(DDS · HTTP 없음 · 수정 목록 207 ·
`coordination_node._reserve_own_now`) · 회차 초기화 바닥과 다시 예약은 뺐다 · 재시작 뒤 그 종류를 잰 값이 없을
때는 같은 PC 의 다른 예약 종류에서 방금 잰 값을 쓴다(`SAMPLE_FALLBACK` · 같은 길이다).

남긴 바닥 둘 · 둘 다 진행 PC 의 길 때문이 아니다(사용자 결정 179 「그룹 시작 · 스케줄 시작 때 시간 여유를 확 늘리자」)
- 초기 위치(`initialize_at` · 3 s) · 모든 PC 가 확인(`group_prepare` 받음)한 **뒤에** 그 시각까지 재생 계획을 짓는다
  (`GroupSession._prepare_plans` · 수정 목록 164) · 확인 시간으로는 그 짓기 시간이 안 잡힌다 · NY 실측 2026-11-16 ·
  920 s 애니 첫 변환 최대 1.4 s · 변환본(208)이 있으면 수십 ms · 예약 확인 최대 17.5 ms · 사용자 결정 179 바닥이라
  그대로 둔다
- 1회차 시작(`first_start` · 3 s) · 잰 값이 없을 때의 기본값 · 재시작 뒤 첫 시작에는 다른 PC 들의 Wi-Fi 왕복을 잰 값이
  없다(`FIRST_START_LEAD_MIN_SEC`)
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Iterable, Mapping, Tuple

#: 예약 명령 → 잴 종류 · 회차 초기화는 따로 잰다(153 ①) · 1회차 시작은 `first_start`(바닥 3 s · 잰 값은 `schedule`)
SCHEDULED_COMMANDS: Mapping[str, str] = {
    'initialize_at': 'initialize',
    'cycle_initialize_at': 'cycle_initialize',
    'start_at': 'schedule',
}
#: 초기 위치 이동 예약의 바닥 · 모든 PC 가 확인한 뒤 예약 시각까지 재생 계획을 짓는다(164) · 이동이 5~10 s 라
#: 앞당겨 보내도 쇼에는 안 보인다 · 1.5 → 3 s(수정 목록 179) · 207 뒤에도 남긴다(위 모듈 설명)
INITIALIZE_LEAD_MIN_SEC = 3.0
#: 실행 1회차 `start_at` 의 바닥 · **잰 값이 없을 때의 기본값 · 사용자 결정 179**(2026-11-07 「그룹 시작 · 스케줄 시작
#: 때 시간 여유를 확 늘리자」)
#:
#: 잰 확인 시간은 메모리에만 있다 · 서비스 재시작 · 업데이트 · 재부팅 뒤 첫 그룹 시작에는 다른 PC 들의 Wi-Fi 왕복을
#: 잰 값이 없다(같은 PC 의 다른 종류 `SAMPLE_FALLBACK` 도 그 실행의 `initialize_at` 한 번뿐) · 그래서 실행마다 1회차
#: 시작은 이 값 아래로 내리지 않는다 · 진행 PC 자신의 예약이 프로세스 안에서 바로 가는 것(207)과 상관없는 값이다 ·
#: 대가는 초기 위치에서 몇 초 더 서 있는 것(쇼에는 안 보임) · 2회차부터(`schedule`)는 잰 값만
FIRST_START_LEAD_MIN_SEC = 3.0
#: 종류 → 바닥 · 없으면 0(설정값 · 잰 값만)
LEAD_FLOOR_SEC: Mapping[str, float] = {
    'initialize': INITIALIZE_LEAD_MIN_SEC,
    'first_start': FIRST_START_LEAD_MIN_SEC,
}
#: 바닥 · 이름만 따로이고 잰 값은 다른 종류와 같이 쓰는 종류 · 1회차 `start_at` 도 같은 `start_at` 확인이다
SAMPLE_KIND: Mapping[str, str] = {
    'first_start': 'schedule',
}
#: 그 종류를 아직 안 잰 PC 는 같은 PC 의 이 종류들에서 잰 값을 쓴다 · 세 예약 모두 같은 길(DDS → 연동 노드 → 재생
#: 관리자)이다 · 재시작 뒤 첫 `start_at` 은 몇 초 앞 `initialize_at` 확인으로 잰다 · 전에는 바닥 3 s 로 덮었다(179) · 207
SAMPLE_FALLBACK: Tuple[str, ...] = ('initialize', 'cycle_initialize', 'schedule')
#: 잰 값이 아무리 커도 이 이상은 기다리지 않는다 · 넘으면 그 PC 가 고장 난 것 · 마감이 잡는다 ·
#: 3 → 6 s · 초기 위치 바닥(3 s)보다 커야 잰 값 × 2 가 먹는다 · 수정 목록 179
LEAD_MAX_SEC = 6.0
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

    def _pc_worst(self, kind: str, pc_id: str) -> float:
        """한 PC 의 그 종류 최악 · 안 잰 종류면 같은 PC 의 다른 예약 종류 최악(`SAMPLE_FALLBACK`) · 아무것도 없으면 0"""
        bucket = self._samples.get((kind, pc_id))
        if bucket:
            return max(bucket)
        values = [
            max(self._samples[(other, pc_id)])
            for other in SAMPLE_FALLBACK
            if other != kind and self._samples.get((other, pc_id))
        ]
        return max(values) if values else 0.0

    def worst(self, kind: str, participants: Iterable[str]) -> float:
        """참가 PC 들의 최근 최악 확인 시간 · 잰 적 없으면 0"""
        values = [self._pc_worst(str(kind), str(pc_id)) for pc_id in participants]
        return max(values) if values else 0.0

    def lead_sec(
        self, kind: str, participants: Iterable[str], *,
        base_lead_sec: float, ack_margin_sec: float,
    ) -> float:
        base = max(float(base_lead_sec), float(ack_margin_sec))
        floor = float(LEAD_FLOOR_SEC.get(str(kind), 0.0))
        sample_kind = SAMPLE_KIND.get(str(kind), str(kind))
        measured = self.worst(sample_kind, participants) * LATENCY_SAFETY_FACTOR + float(ack_margin_sec)
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


#: 예약을 **확실히 받지 않은** 거절 · 조정 노드의 여유 검사(`_local_schedule_ns`) · `GroupSession` 의
#: 「이미 지났습니다」 · 다시 예약해도 두 번 잡히지 않는다 · 「response timeout」 은 늦게라도 받았을 수 있어 뺀다 ·
#: 스스로 잇기(178 · 끊김 시험 A)가 다음 눈금으로 한 번 더 잡을지 정할 때 쓴다
NOT_ACCEPTED_MARKERS = (
    '준비 여유가 부족합니다',
    '트리거가 이미 지났습니다',
)


def is_not_accepted_rejection(text: str) -> bool:
    value = str(text or '')
    return any(marker in value for marker in NOT_ACCEPTED_MARKERS)
