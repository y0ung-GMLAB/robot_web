"""모션 파일 줄을 조인트마다 배열로 · 줄마다 사전을 만들지 않는다 · 수정 목록 170

NY 실물 2026-11-03 · 920 s × 20 조인트 파일(25 MB · 레코드 92만 개)을 줄마다 사전(`dict`)으로
들고 있었다 · 레코드 하나 약 380 B 라 이 PC 의 5 조인트만 남겨도 파일 하나 약 88 MB · 재생 목록
4개를 미리 읽으면 370 MB · 메모리 4.7 GB PC 에서 Firefox 3D 화면까지 켜자 스왑으로 넘어가
실행기가 멈췄다.

여기서는 조인트마다 `array('d')` 넷(프레임 · 시각 · 값 · 줄 번호) · 레코드 하나 32 B.

    JointTrack     한 조인트 · 시각 순(같은 시각은 파일 순) · 값은 파일에서 읽은 그대로의 double
    MotionTracks   파일 하나 · 조인트 순서는 옛 길(시각 · 이름 · 줄 번호로 정렬한 레코드에서 처음 나온 순)

옛 길과 **같은 값**이다 · 정렬 규칙도 같다(시각 → 조인트 이름 → 줄 번호 · 조인트 안에서는 시각 →
줄 번호). `MotionTracks` 를 돌면 옛 레코드 사전이 같은 순서로 나온다(시험 · 옛 함수 호환용 ·
그때 그 자리에서 만든다).

**담은 배열은 고치지 않는다** · 캐시가 여러 계획에 같이 준다.
"""

from __future__ import annotations

from array import array
from bisect import bisect_left
from collections.abc import Sequence
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from . import motion_segment

#: 배열 종류 · 프레임 · 줄 번호는 정수(8 B) · 시각 · 값은 double(8 B)
_INT = 'q'
_REAL = 'd'


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


class JointTrack:
    """한 조인트의 줄들 · 시각 오름차순 · 같은 시각은 파일 순(줄 번호 순)"""

    __slots__ = ('motion_id', 'frames', 'times', 'values', 'rows')

    def __init__(self, motion_id: str) -> None:
        self.motion_id = str(motion_id)
        self.frames = array(_INT)
        self.times = array(_REAL)
        self.values = array(_REAL)
        self.rows = array(_INT)

    @classmethod
    def single(cls, motion_id: str, time_sec: float, value: float, *, frame: int = 0, row: int = 0) -> 'JointTrack':
        """한 점짜리 · 초기 위치 대체값(애니에 이 조인트가 없을 때)"""
        track = cls(motion_id)
        track.append(frame, time_sec, value, row)
        return track

    def append(self, frame: int, time_sec: float, value: float, row: int) -> None:
        self.frames.append(frame)
        self.times.append(time_sec)
        self.values.append(value)
        self.rows.append(row)

    def __len__(self) -> int:
        return len(self.times)

    def __getitem__(self, index: int) -> Dict[str, Any]:
        """옛 레코드 사전 하나(`track[0]['value']` 꼴 호환) · 많이 부를 곳은 배열을 직접 본다"""
        if not -len(self) <= index < len(self):
            raise IndexError(index)
        return self.record(index)

    @property
    def nbytes(self) -> int:
        return sum(column.itemsize * len(column) for column in (self.frames, self.times, self.values, self.rows))

    def sort_by_time(self) -> None:
        """시각 오름차순 · 안정 정렬이라 같은 시각은 넣은 순(파일 순) · 이미 순서면 손대지 않는다"""
        times = self.times
        if all(times[index - 1] <= times[index] for index in range(1, len(times))):
            return
        order = sorted(range(len(times)), key=times.__getitem__)
        self.frames = array(_INT, (self.frames[index] for index in order))
        self.times = array(_REAL, (times[index] for index in order))
        self.values = array(_REAL, (self.values[index] for index in order))
        self.rows = array(_INT, (self.rows[index] for index in order))

    def scale_values(self, scale: float) -> None:
        """`motion_table.scale_record_values` 와 같은 식 · `float(값) * 배율`"""
        if scale != 1.0:
            self.values = array(_REAL, (float(value) * scale for value in self.values))

    def record(self, index: int) -> Dict[str, Any]:
        """옛 레코드 사전 하나 · 칸 순서도 `motion_table.parse_row` + `row_index` 와 같다"""
        return {
            'frame': self.frames[index],
            'time_sec': self.times[index],
            'motion_id': self.motion_id,
            'value': self.values[index],
            'row_index': self.rows[index],
        }

    def sort_key(self) -> tuple:
        """조인트 순서 · 옛 길의 전체 정렬(시각 · 이름 · 줄 번호)에서 이 조인트가 처음 나오는 자리"""
        return (self.times[0], self.motion_id, self.rows[0]) if len(self) else (float('inf'), self.motion_id, 0)


def interpolated(times: Sequence, values: Sequence, time_sec: float) -> float:
    """`motion_run_rules._interpolated_value` 와 비트까지 같은 식 · 레코드 사전 대신 배열"""
    if not len(times):
        return 0.0
    if time_sec <= times[0]:
        return float(values[0])
    if time_sec >= times[-1]:
        return float(values[-1])
    after_index = bisect_left(times, time_sec)
    before_time = times[after_index - 1]
    span = max(float(times[after_index] - before_time), 1e-9)
    ratio = (time_sec - before_time) / span
    before_value = float(values[after_index - 1])
    return before_value + ((float(values[after_index]) - before_value) * ratio)


def _segment_value(track: JointTrack, at: float) -> float:
    """`motion_segment._interpolate` 와 같은 식 · 그쪽은 앞에서부터 처음 맞는 칸 · 시각이 오름차순이라
    `bisect_left` 로 찾은 칸이 바로 그 칸이다"""
    times = track.times
    values = track.values
    if at <= float(times[0]):
        return float(values[0])
    if at >= float(times[-1]):
        return float(values[-1])
    index = bisect_left(times, at)
    t0 = float(times[index - 1])
    t1 = float(times[index])
    span = max(t1 - t0, 1e-9)
    ratio = (at - t0) / span
    return float(values[index - 1]) + (float(values[index]) - float(values[index - 1])) * ratio


class MotionTracks(Sequence):
    """파일 하나의 조인트별 줄 · 돌면 옛 레코드 사전(전체 정렬 순서) · 시험 · 옛 함수 호환용"""

    def __init__(self, tracks: Optional[Mapping[str, JointTrack]] = None) -> None:
        self.tracks: Dict[str, JointTrack] = dict(tracks or {})

    # ------------------------------------------------------------------ 만들기

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> 'MotionTracks':
        """레코드 사전 목록에서 · `motion_run_rules._motion_groups` 와 같은 묶음
        (조인트는 목록에서 처음 나온 순 · 조인트 안은 시각으로 안정 정렬)"""
        tracks: Dict[str, JointTrack] = {}
        for index, record in enumerate(records):
            motion_id = str(record['motion_id'])
            track = tracks.get(motion_id)
            if track is None:
                track = tracks[motion_id] = JointTrack(motion_id)
            track.append(
                _as_int(record.get('frame'), 0),
                record['time_sec'],
                record['value'],
                _as_int(record.get('row_index'), index),
            )
        for track in tracks.values():
            track.sort_by_time()
        return cls(tracks)

    @classmethod
    def from_builder(cls, tracks: Mapping[str, JointTrack]) -> 'MotionTracks':
        """파일 순서로 쌓은 조인트들 · 조인트마다 시각으로 안정 정렬 · 조인트 순서는 옛 전체 정렬 순"""
        for track in tracks.values():
            track.sort_by_time()
        ordered = sorted(tracks.values(), key=JointTrack.sort_key)
        return cls({track.motion_id: track for track in ordered})

    # ------------------------------------------------------------------ 읽기

    def __len__(self) -> int:
        return sum(len(track) for track in self.tracks.values())

    def __bool__(self) -> bool:
        return any(len(track) for track in self.tracks.values())

    def records(self) -> List[Dict[str, Any]]:
        """옛 레코드 사전 목록 · 정렬은 옛 길 그대로(시각 · 조인트 이름 · 줄 번호) · 부를 때마다 새것"""
        records = [track.record(index) for track in self.tracks.values() for index in range(len(track))]
        records.sort(key=lambda item: (item['time_sec'], str(item['motion_id']), item['row_index']))
        return records

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self.records())

    def __getitem__(self, index):
        return self.records()[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MotionTracks):
            return self.records() == other.records()
        if isinstance(other, (list, tuple)):
            return self.records() == list(other)
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'MotionTracks({len(self.tracks)} joints, {len(self)} records)'

    @property
    def nbytes(self) -> int:
        """대략 · 배열 크기만 · 캐시 예산에 쓴다"""
        return sum(track.nbytes for track in self.tracks.values())

    def start_time(self) -> float:
        return min(track.times[0] for track in self.tracks.values() if len(track))

    def end_time(self) -> float:
        return max(track.times[-1] for track in self.tracks.values() if len(track))

    # ------------------------------------------------------------------ 구간

    def sliced(self, start_sec: Any, end_sec: Any) -> Tuple['MotionTracks', Dict[str, Any]]:
        """`motion_segment.slice_records` + `_motion_groups` 와 같은 결과 · (잘린 것, 정보)

        조인트마다 첫 줄(시각 0 · 시작 시각 보간값) · 안쪽 줄(시각 − 시작) · 끝 줄(끝 시각 보간값) ·
        첫·끝 줄의 프레임 · 줄 번호는 옛 길처럼 그 조인트의 첫 · 끝 줄 것.
        """
        live = [track for track in self.tracks.values() if len(track)]
        if not live:
            return MotionTracks(), {
                'source_duration_sec': 0.0, **motion_segment.fields(start_sec, end_sec), 'end_clamped': False,
            }
        first_time = min(float(track.times[0]) for track in live)
        last_time = max(float(track.times[-1]) for track in live)
        cut_from, cut_to, info = motion_segment.cut_bounds(first_time, last_time, start_sec, end_sec)
        result: Dict[str, JointTrack] = {}
        for track in live:
            cut = JointTrack(track.motion_id)
            cut.append(track.frames[0], 0.0, _segment_value(track, cut_from), track.rows[0])
            for index in range(len(track)):
                at = float(track.times[index])
                if motion_segment.inside_cut(at, cut_from, cut_to):
                    cut.append(track.frames[index], at - cut_from, track.values[index], track.rows[index])
            cut.append(track.frames[-1], cut_to - cut_from, _segment_value(track, cut_to), track.rows[-1])
            result[track.motion_id] = cut
        return MotionTracks(result), info
