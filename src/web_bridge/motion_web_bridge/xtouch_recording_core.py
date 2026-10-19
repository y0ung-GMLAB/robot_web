"""X-Touch 녹화 · 순수 계산 · 수정 목록 156 · 상태(`RecordingService`)는 `xtouch_recording`

    Take            새로 녹화 · supervisor 램프 값을 프레임에 놓는다(주기 번호로 잇고 끊기면 벽시계)
    animation_text  Blender 내보내기와 같은 JSON Lines
    rate_problem    재생과 같은 속도·가속도 검사
    save_unique     같은 이름이면 _2 · _3
    save_over       같은 이름에 덮어쓰기(전 파일은 휴지통에 사본)
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from motion_common import joint_mapping, rate_check, units

#: 프레임 간격 · 재생·Blender 내보내기와 같다
PERIOD_SEC = 0.02
#: 시작 버튼 뒤 기다리는 시간 · 사용자 결정 2026-10-17
COUNTDOWN_SEC = 3.0
#: 파일 이름 · 화면이 안 주면 이 앞머리 + 시각
DEFAULT_PREFIX = 'xtouch'
_NAME_UNSAFE = re.compile(r'[^0-9A-Za-z가-힣._-]+')


@dataclass
class TakeAxis:
    """녹화하는 모터 하나 · 그 모터를 모는 조인트 줄(보통 하나)"""

    axis: int
    rows: List[Dict[str, Any]]
    #: 녹화를 시작할 때 모터 위치 · rad · 첫 램프 값이 오기 전까지 이 값
    start_motor: float

    @property
    def motion_ids(self) -> List[str]:
        return [str(row.get('motion_id') or '').strip() for row in self.rows]


@dataclass
class Take:
    """녹화 한 번 · 값은 모두 모터 rad · 프레임 0 = 카운트다운이 끝난 순간"""

    t0: float
    axes: Dict[int, TakeAxis] = field(default_factory=dict)
    #: 축 → {프레임: 모터 rad}
    frames: Dict[int, Dict[int, float]] = field(default_factory=dict)
    #: 축 → 프레임 0 전 마지막 값 · 카운트다운 중에 움직인 것
    before: Dict[int, float] = field(default_factory=dict)
    #: 축 → (마지막 seq, 그 프레임)
    last: Dict[int, Tuple[int, int]] = field(default_factory=dict)

    def add_axis(self, axis: TakeAxis) -> None:
        if axis.axis not in self.axes:
            self.axes[axis.axis] = axis
            self.frames.setdefault(axis.axis, {})

    def add_samples(self, seq: int, wall: float, samples: List[Tuple[int, float]]) -> None:
        for axis, value in samples:
            if axis not in self.axes:
                continue
            previous = self.last.get(axis)
            if previous is not None and seq == previous[0] + 1:
                frame = previous[1] + 1
            else:
                frame = int(round((wall - self.t0) / PERIOD_SEC))
                if previous is not None:
                    frame = max(frame, previous[1] + 1)
            self.last[axis] = (seq, frame)
            if frame < 0:
                self.before[axis] = float(value)
            else:
                self.frames[axis][frame] = float(value)

    def frame_count(self, end_wall: float) -> int:
        return max(1, int(math.floor((end_wall - self.t0) / PERIOD_SEC + 1e-9)) + 1)

    def series(self, end_wall: float) -> Dict[int, List[float]]:
        """축 → 프레임마다 모터 rad · 빈 프레임은 앞 값 그대로"""
        return self.series_count(self.frame_count(end_wall))

    def series_count(self, count: int) -> Dict[int, List[float]]:
        """프레임 수를 정해서 · 바탕 위 녹화는 바탕 프레임 수로"""
        result: Dict[int, List[float]] = {}
        for axis, info in self.axes.items():
            value = self.before.get(axis, info.start_motor)
            placed = self.frames.get(axis, {})
            values = []
            for frame in range(count):
                if frame in placed:
                    value = placed[frame]
                values.append(value)
            result[axis] = values
        return result

    def joint_series(self, end_wall: float) -> List[Tuple[str, Dict[str, Any], List[float]]]:
        """(조인트 이름, 매핑 줄, 프레임마다 조인트 rad) · 줄 순서 = 모터 번호 순"""
        return self.joint_series_count(self.frame_count(end_wall))

    def joint_series_count(self, count: int) -> List[Tuple[str, Dict[str, Any], List[float]]]:
        out = []
        motor = self.series_count(count)
        for axis in sorted(self.axes):
            for row in self.axes[axis].rows:
                values = []
                for value in motor[axis]:
                    joint = joint_mapping.joint_from_motor(row, value, units.RAD)
                    values.append(0.0 if joint is None else joint)
                out.append((str(row.get('motion_id') or '').strip(), row, values))
        return out


def animation_text(
    title: str, joints: List[Tuple[str, Any, List[float]]], start: float = PERIOD_SEC, base: str = '',
) -> str:
    """Blender 내보내기(`scripts/blender/animation_export.py`)와 같은 모양 · 프레임 1 = `start`(보통 0.02 s)"""
    header = {
        'title': title, 'type': 'motion_header', 'rotation_mode': 'relative',
        'rotation_unit': 'rad', 'fields': ['frame', 'time_sec', 'id', 'value'],
        'file_title': title, 'source': 'xtouch',
    }
    if base:
        header['base_file'] = base
    lines = [json.dumps(header, ensure_ascii=False)]
    count = len(joints[0][2]) if joints else 0
    for index in range(count):
        row: List[Any] = [index + 1, round(start + index * PERIOD_SEC, 9)]
        for motion_id, _, values in joints:
            row.extend((motion_id, round(values[index], 9) + 0.0))
        lines.append(json.dumps(row, ensure_ascii=False, separators=(',', ':')))
    return '\n'.join(lines) + '\n'


def rate_problem(joints: List[Tuple[str, Any, List[float]]]) -> str:
    """재생과 같은 속도·가속도 검사 · 넘으면 이유 · 빈 글자면 통과 · 매핑 줄이 없는 조인트(다른 로봇 것)는 안 본다"""
    joints = [joint for joint in joints if joint[1]]
    if not joints:
        return ''
    count = len(joints[0][2])
    samples = [
        {
            'time_sec': (index + 1) * PERIOD_SEC,
            # 파일에 쓰는 값 그대로(소수 9자리) 잰다 · 재생이 읽는 값과 같게 · 2026-10-19
            'motion_values': {motion_id: round(values[index], 9) for motion_id, _, values in joints},
        }
        for index in range(count)
    ]
    axes = [{'motion_id': motion_id, 'row': row} for motion_id, row, _ in joints]
    return rate_check.rate_limit_error(axes, samples, PERIOD_SEC)


def clean_name(value: Any, now: Optional[datetime] = None) -> str:
    """파일 이름 앞부분 · 확장자 없이 · 비면 `xtouch_YYYYMMDD_HHMMSS`"""
    text = _NAME_UNSAFE.sub('_', str(value or '').strip())
    text = re.sub(r'\.json$', '', text, flags=re.IGNORECASE).strip('._-')[:80]
    if text:
        return text
    stamp = (now or datetime.now()).strftime('%Y%m%d_%H%M%S')
    return f'{DEFAULT_PREFIX}_{stamp}'


#: 저장소가 같은 이름을 거절할 때 쓰는 글 · `ProjectRepository.import_text`
SAME_NAME_TEXT = '같은 이름의 파일이 이미 있습니다'


def save_over(repository: Any, project_id: str, base: str, joints: Any, *, start: float, base_file: str = '') -> Tuple[str, str]:
    """같은 이름에 덮어쓰기 · 있으면 휴지통에 사본(되살릴 수 있음) 뒤 그 자리에 · 없으면 새로 · (쓴 이름, 사본 경로 | '')

    사용자 2026-10-19 「이미 있는거에 저장」 · 화면에서 덮어쓰기를 골랐을 때만
    """
    name = f'{base}.json'
    text = animation_text(base, joints, start=start, base=base_file)
    try:
        backup = repository.copy_to_trash(project_id, 'motions', name)
    except ValueError:              # 그 이름이 없음 · 새로
        repository.import_text(project_id, 'motions', name, text)
        return name, ''
    repository.save_file(project_id, 'motions', name, text)
    return name, str(backup)


def save_unique(write: Callable[[str], Any], base: str, limit: int = 1000) -> str:
    """같은 이름이 있으면 `_2` · `_3` … 로 다시 · 기존 파일은 안 바뀐다 · 쓴 이름을 돌려준다

    있는지 먼저 보고 쓰면 그 사이 다른 저장과 겹칠 수 있다 · 저장소가 같은 이름을 거절하는 것을 쓴다.
    """
    for number in range(1, limit + 1):
        name = f'{base}.json' if number == 1 else f'{base}_{number}.json'
        try:
            write(name)
        except ValueError as exc:
            if SAME_NAME_TEXT in str(exc):
                continue
            raise
        return name
    raise ValueError(f'{base} 이름이 너무 많습니다')


