"""X-Touch 녹화 · 기존 애니메이션 위에 · 수정 목록 156 ⑨ 추가 녹화 · ⑨-2 구간 덮어쓰기 (사용자 결정 2026-10-17)

기존 애니메이션(바탕)을 재생 노드가 재생하는 동안 녹화한다 · 결과는 **새 파일**(바탕은 안 바뀐다).

    바탕 조인트   원본 그대로 · 사람이 잡은 구간만 재생 노드가 보낸 값(`motion_common.punch` · 잡기 · 놓으면 원본으로 잇기)
    새 조인트     바탕에 없는 축을 X-Touch 로 얹음(추가 녹화) · supervisor 램프가 보낸 값을 재생 프레임에 맞춤
    그 밖         바탕 파일의 다른 조인트(다른 로봇 것 포함)도 그대로 옮긴다
    길이          끝까지 재생되면 바탕 길이 · 중간에 멈추면 거기까지

프레임 시각 · 재생 노드가 프레임마다 번호와 보낸 벽시계를 알린다(`MOTION_RUN_TAKE_FRAMES`) ·
프레임 0 의 벽시계 = 그 알림들의 (시각 − 번호 × 주기) 중 가장 이른 값(전달 지연이 가장 짧은 것).

순수 계산만 · 상태는 `xtouch_recording.RecordingService` 가 든다.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from motion_common import joint_mapping, motion_table

from .xtouch_recording_core import PERIOD_SEC, Take, TakeAxis


@dataclass
class BaseAnimation:
    """바탕 애니메이션 · 재생 계획과 같은 20 ms 격자 · 값은 rad"""

    file_id: str
    ids: List[str]
    start: float
    values: Dict[str, List[float]]

    @property
    def count(self) -> int:
        return len(next(iter(self.values.values()))) if self.values else 0


def load_base(file_id: str, content: str, dt: float = PERIOD_SEC) -> BaseAnimation:
    """재생과 같은 파서 · 같은 격자(시작 = 가장 이른 시각 · 주기마다 · 끝은 마지막 시각) · 사이 값은 직선"""
    rows, headers, _source, _warning = motion_table.extract_rows_from_content(content)
    records = motion_table.parse_rows(rows, headers)
    motion_table.scale_record_values(records, motion_table.rotation_unit_from_content(content))
    if not records:
        raise ValueError(f'{file_id} · 재생할 수 있는 행이 없습니다')
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for record in sorted(records, key=lambda item: (item['time_sec'], item.get('row_index', 0))):
        groups.setdefault(str(record['motion_id']), []).append(record)
    ids = []
    for record in records:
        motion_id = str(record['motion_id'])
        if motion_id not in ids:
            ids.append(motion_id)
    start = min(record['time_sec'] for record in records)
    end = max(record['time_sec'] for record in records)
    count = max(1, int(math.floor((end - start) / dt)) + 1)
    if end - (start + (count - 1) * dt) > 0.001:
        count += 1
    values: Dict[str, List[float]] = {}
    for motion_id, group in groups.items():
        times = [float(item['time_sec']) for item in group]
        values[motion_id] = [
            _interpolated(group, times, min(start + index * dt, end)) for index in range(count)
        ]
    return BaseAnimation(file_id=file_id, ids=ids, start=float(start), values=values)


def _interpolated(group: List[Dict[str, Any]], times: List[float], time_sec: float) -> float:
    """재생(`motion_run_rules._interpolated_value`)과 같은 식"""
    if time_sec <= group[0]['time_sec']:
        return float(group[0]['value'])
    if time_sec >= group[-1]['time_sec']:
        return float(group[-1]['value'])
    after_index = bisect_left(times, time_sec)
    before = group[after_index - 1]
    after = group[after_index]
    span = max(float(after['time_sec'] - before['time_sec']), 1e-9)
    ratio = (time_sec - before['time_sec']) / span
    return float(before['value']) + (float(after['value']) - float(before['value'])) * ratio


@dataclass
class BaseTake:
    """녹화 한 번 · 바탕 위에"""

    take_id: str
    base: BaseAnimation
    #: 사람이 잡을 수 있는 바탕 조인트 · 조인트 → 매핑 줄
    punch_rows: Dict[str, Dict[str, Any]]
    #: 바탕에 없는 축(추가 녹화) · 모터 번호 → 줄
    overdub: Dict[int, TakeAxis] = field(default_factory=dict)
    #: 재생 노드가 덮어쓴 값 · 조인트 → {프레임: rad}
    punched: Dict[str, Dict[int, float]] = field(default_factory=dict)
    #: supervisor X-Touch 램프 값 · (seq, 벽시계, 모터, rad)
    samples: List[Tuple[int, float, int, float]] = field(default_factory=list)
    t0: Optional[float] = None
    last_frame: int = -1
    ended: bool = False
    overrun: set = field(default_factory=set)
    #: 재생 노드가 알린 실패 이유(시작도 못 함 · 오류로 끝남) · 2026-10-19
    error: str = ''

    def on_frame(self, payload: Dict[str, Any], dt: float = PERIOD_SEC) -> None:
        if payload.get('end'):
            self.ended = True
            self.error = str(payload.get('error') or '')
            return
        try:
            frame = int(payload.get('frame'))
            wall = float(payload.get('t'))
        except (TypeError, ValueError):
            return
        start = wall - frame * dt
        self.t0 = start if self.t0 is None else min(self.t0, start)
        self.last_frame = max(self.last_frame, frame)
        for motion_id, value in (payload.get('values') or {}).items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                self.punched.setdefault(str(motion_id), {})[frame] = number
        for motion_id in payload.get('blend_overrun') or []:
            self.overrun.add(str(motion_id))

    def frame_count(self) -> int:
        """끝까지 재생됐으면 바탕 길이 · 중간에 멈췄으면 받은 마지막 프레임까지"""
        if self.last_frame < 0:
            return 0
        return min(self.base.count, self.last_frame + 1)

    def compose(self) -> Tuple[List[Tuple[str, Optional[Dict[str, Any]], List[float]]], int]:
        """(조인트, 매핑 줄 | None, 프레임마다 rad) 목록 · 바탕 순서 다음에 새 조인트"""
        count = self.frame_count()
        out: List[Tuple[str, Optional[Dict[str, Any]], List[float]]] = []
        for motion_id in self.base.ids:
            values = list(self.base.values[motion_id][:count])
            for frame, value in self.punched.get(motion_id, {}).items():
                if 0 <= frame < count:
                    values[frame] = value
            out.append((motion_id, self.punch_rows.get(motion_id), values))
        if self.overdub and count:
            take = Take(t0=float(self.t0 if self.t0 is not None else 0.0))
            for item in self.overdub.values():
                take.add_axis(item)
            for seq, wall, axis, value in self.samples:
                take.add_samples(seq, wall, [(axis, value)])
            known = set(self.base.ids)
            for motion_id, row, values in take.joint_series_count(count):
                if motion_id not in known:
                    out.append((motion_id, row, values))
        return out, count


def mapped_rows(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """「사용」 줄 · 조인트 이름 → 줄"""
    return {
        str(row.get('motion_id') or '').strip(): row for row in rows
        if row.get('enabled') is not False and str(row.get('motion_id') or '').strip()
    }


def punchable(base: BaseAnimation, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """바탕 조인트 중 이 PC 매핑에 있고 속도·가속도 상한이 있는 것 · 그것만 사람이 잡을 수 있다"""
    by_id = mapped_rows(rows)
    return {
        motion_id: by_id[motion_id] for motion_id in base.ids
        if motion_id in by_id and joint_mapping.rate_limits_set(by_id[motion_id])
    }
