"""구간 재생 · 애니메이션을 mm:ss 부터 (끝 시각까지) · 이 낱말의 주인 (2026-10-16)

구간 = {시작 초 ≥ 0 · 끝 초(0 = 끝까지 · 아니면 시작보다 뒤)} · **재생 목록 1번에만** 쓴다.
시각은 파일 시각 · 애니메이션 첫 줄을 0 으로 잰다(재생 화면 진행 시각과 같은 자).

화면(재생) → 브리지(검사 · 칸 이름 맞춤) → 런타임(계획 자르기) · 그룹이면 연동(`GroupCommand`
`segment_start_sec` · `segment_end_sec`) → PC 마다 제 재생 목록 1번을 같은 시각으로 자른다 · 스피커는
같은 시각부터 음원을 튼다. 저장하지 않는다 · 시작 요청 한 번의 값 · 스케줄은 늘 통째로.

이 모듈은 ROS 를 모른다 · 브리지 · 연동 · 런타임이 같이 쓴다.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

#: 칸 이름 · 런타임 요청 · 상태 · 그룹 명령이 같은 이름을 쓴다
START_KEY = 'segment_start_sec'
END_KEY = 'segment_end_sec'

#: 시각 비교 여유 · 1 ms 보다 훨씬 작게 · 파일 시각은 20 ms 칸
_EPS = 1e-6

#: 이보다 길면 잘못 친 값으로 본다 · 24 시간
MAX_SEGMENT_SEC = 86400.0


def format_time(seconds: Any) -> str:
    """`80` → `1:20` · `80.5` → `1:20.5` · 0.1 초 단위 · 화면 글과 같은 모양"""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return '-'
    if not math.isfinite(value):
        return '-'
    tenths = int(round(max(value, 0.0) * 10.0))
    minutes, rest = divmod(tenths, 600)
    whole, tenth = divmod(rest, 10)
    return f'{minutes}:{whole:02d}' + (f'.{tenth}' if tenth else '')


def _number(value: Any, label: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    if isinstance(value, bool):
        raise ValueError(f'{label} 시각이 숫자가 아닙니다')
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} 시각이 숫자가 아닙니다') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label} 시각이 숫자가 아닙니다')
    if number < 0.0:
        raise ValueError(f'{label}은 0초 이상이어야 합니다')
    if number > MAX_SEGMENT_SEC:
        raise ValueError(f'{label} {format_time(number)} 이 너무 깁니다')
    return number


def parse(payload: Optional[Mapping[str, Any]]) -> Tuple[float, float]:
    """요청에서 (시작 초, 끝 초) · 끝 0 = 끝까지 · 틀리면 ValueError(사람이 읽는 이유)

    두 모양을 받는다 · 화면 `segment: {start_sec, end_sec}` · 안쪽 `segment_start_sec` · `segment_end_sec`.
    """
    if not isinstance(payload, Mapping):
        return 0.0, 0.0
    nested = payload.get('segment')
    if isinstance(nested, Mapping):
        raw_start, raw_end = nested.get('start_sec'), nested.get('end_sec')
    elif nested not in (None, '', {}):
        raise ValueError('구간 값은 {start_sec, end_sec} 이어야 합니다')
    else:
        raw_start, raw_end = payload.get(START_KEY), payload.get(END_KEY)
    start = _number(raw_start, '구간 시작')
    end = _number(raw_end, '구간 끝')
    if end > 0.0 and end <= start + _EPS:
        raise ValueError(
            f'구간 끝 {format_time(end)} 이 구간 시작 {format_time(start)} 보다 뒤여야 합니다'
        )
    return start, end


def is_active(start: Any, end: Any = 0.0) -> bool:
    """구간이 걸렸나 · 0/0(또는 빈 값) = 통째로"""
    try:
        return float(start or 0.0) > _EPS or float(end or 0.0) > _EPS
    except (TypeError, ValueError):
        return False


def fields(start: float, end: float) -> Dict[str, float]:
    return {START_KEY: float(start), END_KEY: float(end)}


def apply_to_payload(payload: Mapping[str, Any], *, allowed: bool = True) -> Dict[str, Any]:
    """요청 사본 · `segment` 를 안쪽 칸 두 개로 바꾼다 · `allowed=False`(스케줄) 면 통째로(0/0)

    틀린 값이면 ValueError · 받기 전에 거절하려고 브리지가 부른다.
    """
    result = dict(payload or {})
    start, end = parse(result) if allowed else (0.0, 0.0)
    result.pop('segment', None)
    result.update(fields(start, end))
    return result


def label(start: Any, end: Any = 0.0) -> str:
    """`구간 1:20~1:45` · 끝이 0 이면 `구간 1:20~끝` · 구간이 없으면 빈 글자"""
    if not is_active(start, end):
        return ''
    end_value = float(end or 0.0)
    return f'구간 {format_time(start)}~{format_time(end_value) if end_value > _EPS else "끝"}'


def _interpolate(records: List[Mapping[str, Any]], at: float) -> float:
    """선형 · 재생 계획의 보간(`motion_run_rules._interpolated_value`)과 같은 규칙 · 범위 밖은 끝값"""
    if at <= float(records[0]['time_sec']):
        return float(records[0]['value'])
    if at >= float(records[-1]['time_sec']):
        return float(records[-1]['value'])
    for before, after in zip(records, records[1:]):
        t0 = float(before['time_sec'])
        t1 = float(after['time_sec'])
        if t0 <= at <= t1:
            span = max(t1 - t0, 1e-9)
            ratio = (at - t0) / span
            return float(before['value']) + (float(after['value']) - float(before['value'])) * ratio
    return float(records[-1]['value'])


def slice_records(
    records: List[Mapping[str, Any]], start_sec: float, end_sec: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """모션 줄을 [시작, 끝] 으로 자르고 0 부터 다시 센다 · (잘린 줄, 정보)

    조인트마다 시작·끝 시각의 값을 보간해 첫 줄·끝 줄로 넣고 그 사이 줄은 그대로 둔다 · 선형 보간
    위의 점을 더한 것이라 20 ms 재샘플 결과는 원래 파일을 시작 시각부터 20 ms 마다 읽은 값과 같다.

    시작이 애니메이션 길이 이상이면 ValueError · 끝이 길이보다 길면 끝까지(정보 `end_clamped`).
    정보 · `source_duration_sec`(파일 길이) · `segment_start_sec` · `segment_end_sec`(실제 끝 · 파일 시각) ·
    `end_clamped`.
    """
    rows = [record for record in records if isinstance(record, Mapping)]
    if not rows:
        return [], {'source_duration_sec': 0.0, **fields(start_sec, end_sec), 'end_clamped': False}
    first_time = min(float(record['time_sec']) for record in rows)
    last_time = max(float(record['time_sec']) for record in rows)
    length = max(last_time - first_time, 0.0)
    start = max(float(start_sec or 0.0), 0.0)
    requested_end = max(float(end_sec or 0.0), 0.0)
    if start >= length - _EPS:
        raise ValueError(
            f'구간 시작 {format_time(start)} 이 애니메이션 길이 {format_time(length)} 보다 깁니다'
        )
    if requested_end > _EPS and requested_end <= start + _EPS:
        raise ValueError(
            f'구간 끝 {format_time(requested_end)} 이 구간 시작 {format_time(start)} 보다 뒤여야 합니다'
        )
    end_clamped = requested_end > length + _EPS
    end = length if requested_end <= _EPS or requested_end >= length else requested_end
    cut_from = first_time + start
    cut_to = first_time + end

    groups: Dict[str, List[Mapping[str, Any]]] = {}
    for record in rows:
        groups.setdefault(str(record['motion_id']), []).append(record)
    sliced: List[Dict[str, Any]] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: float(item['time_sec']))
        template = dict(ordered[0])
        sliced.append({**template, 'time_sec': 0.0, 'value': _interpolate(ordered, cut_from)})
        for record in ordered:
            at = float(record['time_sec'])
            if cut_from + _EPS < at < cut_to - _EPS:
                sliced.append({**dict(record), 'time_sec': at - cut_from})
        sliced.append({
            **dict(ordered[-1]), 'time_sec': cut_to - cut_from, 'value': _interpolate(ordered, cut_to),
        })
    return sliced, {
        'source_duration_sec': length,
        START_KEY: start,
        END_KEY: end,
        'end_clamped': end_clamped,
    }
