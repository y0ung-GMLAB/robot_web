"""20 ms 재샘플 결과를 배열로 · 꺼낼 때 옛 사전 모양으로 · 수정 목록 170

계획의 `samples` 는 원래 샘플마다 사전 셋(샘플 · 모터 위치 · 조인트 값)이었다 · 920 s 면 46000 개 ·
5 조인트에서 약 54 MB · 캐시 둘 + 재생 목록 계획까지 들고 있었다.

여기서는 칸마다 `array('d')` 하나 · 샘플 하나 (2 + 축 수 × 2) × 8 B · 5 축이면 96 B.

    samples[i]   → {'time_sec', 'absolute_time_sec', 'positions': {모터축: rad}, 'motion_values': {조인트: rad}}
                   (옛 사전과 같은 칸 · 같은 순서 · 같은 double · 꺼낼 때마다 새 사전이라 고쳐도 계획은 그대로)
    len · 음수 번호 · 자르기 · 돌기 · 같음 비교(목록과도)
    time_column() · motion_column(조인트) · 검사(속도·가속)가 사전을 만들지 않고 배열을 바로 본다

**배열은 고치지 않는다** · 캐시가 여러 계획에 같이 준다.
"""

from __future__ import annotations

from array import array
from collections.abc import Sequence
from typing import Any, Dict, List

_REAL = 'd'


class PackedSamples(Sequence):
    __slots__ = ('_times', '_absolute', '_motor_axes', '_motion_ids', '_positions', '_values')

    def __init__(self, motor_axes: List[int], motion_ids: List[str]) -> None:
        if len(motor_axes) != len(motion_ids):
            raise ValueError('축 수와 조인트 수가 다릅니다')
        self._times = array(_REAL)
        self._absolute = array(_REAL)
        self._motor_axes = tuple(motor_axes)
        self._motion_ids = tuple(str(item) for item in motion_ids)
        self._positions = tuple(array(_REAL) for _ in motor_axes)
        self._values = tuple(array(_REAL) for _ in motion_ids)

    # ------------------------------------------------------------------ 쌓기 (계획 만들 때만)

    def append(self, time_sec: float, absolute_time_sec: float, positions: List[float], values: List[float]) -> None:
        """축 순서대로 · 위치 · 조인트 값"""
        self._times.append(time_sec)
        self._absolute.append(absolute_time_sec)
        for column, value in zip(self._positions, positions):
            column.append(value)
        for column, value in zip(self._values, values):
            column.append(value)

    # ------------------------------------------------------------------ 읽기

    def __len__(self) -> int:
        return len(self._times)

    def _sample(self, index: int) -> Dict[str, Any]:
        positions: Dict[int, float] = {}
        for axis, column in zip(self._motor_axes, self._positions):
            positions[axis] = column[index]
        motion_values: Dict[str, float] = {}
        for motion_id, column in zip(self._motion_ids, self._values):
            motion_values[motion_id] = column[index]
        return {
            'time_sec': self._times[index],
            'absolute_time_sec': self._absolute[index],
            'positions': positions,
            'motion_values': motion_values,
        }

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self._sample(item) for item in range(*index.indices(len(self)))]
        count = len(self)
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError('sample index out of range')
        return self._sample(index)

    def __iter__(self):
        for index in range(len(self)):
            yield self._sample(index)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PackedSamples):
            return (
                self._motor_axes == other._motor_axes and self._motion_ids == other._motion_ids
                and self._times == other._times and self._absolute == other._absolute
                and self._positions == other._positions and self._values == other._values
            )
        if isinstance(other, (list, tuple)):
            return len(self) == len(other) and all(mine == theirs for mine, theirs in zip(self, other))
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'PackedSamples({len(self)} samples × {len(self._motor_axes)} axes)'

    def time_column(self) -> array:
        """샘플 시각(계획 시작 0) · 고치지 말 것"""
        return self._times

    def motion_column(self, motion_id: str) -> array:
        """그 조인트 값 · 사전처럼 같은 조인트가 둘이면 뒤의 것 · 없으면 KeyError · 고치지 말 것"""
        key = str(motion_id)
        for index in range(len(self._motion_ids) - 1, -1, -1):
            if self._motion_ids[index] == key:
                return self._values[index]
        raise KeyError(motion_id)

    @property
    def nbytes(self) -> int:
        columns = (self._times, self._absolute, *self._positions, *self._values)
        return sum(column.itemsize * len(column) for column in columns)
