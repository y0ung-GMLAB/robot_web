"""X-Touch 녹화 · 수정 목록 156 (사용자 결정 2026-10-17)

X-Touch 페이더로 움직인 축을 애니메이션 파일로 남긴다 · 로봇 쪽(브리지)에서 기록한다 ·
화면(브라우저)은 시작·정지만 보낸다 · 화면이 끊겨도 여기서 끊긴 순간까지 저장한다.

    기록 값   **명령값 · 램프 뒤** · supervisor 램프가 주기마다 모터로 보낸 값(`MANUAL_STREAM_SAMPLES`) ·
              모터 rad 를 조인트 매핑 식으로 되돌려 조인트 rad 로
    주기      20 ms · 램프 주기 번호(`seq`)가 이어지면 다음 프레임 · 끊겼다 다시 오면 받은 벽시계로 자리를 정한다 ·
              램프가 없는 동안(놓고 도착함)은 마지막 값 그대로(축이 서 있다)
    축        녹화 시작 때 고른 축(+ 녹화 중 더한 축) · 그 밖의 축은 파일에 안 넣는다 ·
              속도·가속도 상한이 빈 축은 시작 거절
    시작      카운트다운 3초 뒤부터 · 그 전 값은 첫 프레임 값으로만
    저장      Blender 내보내기와 같은 JSON Lines(첫 줄 `motion_header` · rad) · 프로젝트 애니메이션 목록 ·
              같은 이름이면 `_2` · `_3` · 저장 전에 재생과 같은 속도·가속도 검사(`rate_check`) · 넘으면 저장 안 함
    끊김      소켓이 닫히거나 수신이 끊기면 마지막으로 받은 순간까지 자동 저장(자동 번호)

순수 계산(`Take` · `animation_text`)과 상태(`RecordingService`)를 나눴다 · 시험은 앞쪽을 본다.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
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
        count = self.frame_count(end_wall)
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
        out = []
        motor = self.series(end_wall)
        for axis in sorted(self.axes):
            for row in self.axes[axis].rows:
                values = []
                for value in motor[axis]:
                    joint = joint_mapping.joint_from_motor(row, value, units.RAD)
                    values.append(0.0 if joint is None else joint)
                out.append((str(row.get('motion_id') or '').strip(), row, values))
        return out


def animation_text(title: str, joints: List[Tuple[str, Dict[str, Any], List[float]]]) -> str:
    """Blender 내보내기(`scripts/blender/animation_export.py`)와 같은 모양 · 프레임 1 = 0.02 s"""
    header = {
        'title': title, 'type': 'motion_header', 'rotation_mode': 'relative',
        'rotation_unit': 'rad', 'fields': ['frame', 'time_sec', 'id', 'value'],
        'file_title': title, 'source': 'xtouch',
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    count = len(joints[0][2]) if joints else 0
    for index in range(count):
        row: List[Any] = [index + 1, round((index + 1) * PERIOD_SEC, 9)]
        for motion_id, _, values in joints:
            row.extend((motion_id, round(values[index], 9) + 0.0))
        lines.append(json.dumps(row, ensure_ascii=False, separators=(',', ':')))
    return '\n'.join(lines) + '\n'


def rate_problem(joints: List[Tuple[str, Dict[str, Any], List[float]]]) -> str:
    """재생과 같은 속도·가속도 검사 · 넘으면 이유 · 빈 글자면 통과"""
    if not joints:
        return ''
    count = len(joints[0][2])
    samples = [
        {
            'time_sec': (index + 1) * PERIOD_SEC,
            'motion_values': {motion_id: values[index] for motion_id, _, values in joints},
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


class RecordingService:
    """브리지에 하나 · 한 번에 녹화 하나(X-Touch 를 쥔 화면 하나) · 잠금 안에서만 바꾼다

    브리지 속은 안 만진다 · 필요한 것은 만들 때 받는다(§6-170) ·
        mapping   () → (저장된 매핑 「사용」 줄들, 모터 상태들) · 막는 이유를 먼저 본 뒤 부른다
        record_event(event_type, content, details) · 모터 기록(운영 로그)
    """

    def __init__(
        self,
        bridge: Any,
        *,
        mapping: Callable[[], Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]],
        record_event: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.bridge = bridge
        self._mapping = mapping
        self._event = record_event
        self._clock = clock
        self._lock = threading.Lock()
        self._take: Optional[Take] = None
        self.last_event_error = ''
        self._owner: Any = None
        self._name = ''

    # ------------------------------------------------------------------ #
    # supervisor 램프 값
    # ------------------------------------------------------------------ #

    def samples_callback(self, msg: Any) -> None:
        try:
            payload = json.loads(msg.data)
        except (AttributeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        try:
            seq = int(payload.get('seq'))
            wall = float(payload.get('t'))
        except (TypeError, ValueError):
            return
        samples = []
        for item in payload.get('samples') or []:
            try:
                axis, value = int(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if math.isfinite(value):
                samples.append((axis, value))
        with self._lock:
            if self._take is not None and samples:
                self._take.add_samples(seq, wall, samples)

    # ------------------------------------------------------------------ #
    # 화면 요청
    # ------------------------------------------------------------------ #

    def active_for(self, owner: Any) -> bool:
        with self._lock:
            return self._take is not None and self._owner is owner

    def status(self) -> Dict[str, Any]:
        with self._lock:
            take = self._take
            if take is None:
                return {'state': 'idle'}
            now = self._clock()
            return {
                'state': 'countdown' if now < take.t0 else 'recording',
                'name': self._name,
                'axes': sorted(take.axes),
                'starts_in_sec': max(0.0, take.t0 - now),
                'elapsed_sec': max(0.0, now - take.t0),
            }

    def start(self, owner: Any, axes: Any, name: Any = '') -> Dict[str, Any]:
        with self._lock:
            if self._take is not None:
                return {'success': False, 'message': '이미 녹화 중입니다 · 정지한 뒤 다시 시작하세요'}
        block = self._block_reason()
        if block:
            return {'success': False, 'message': block}
        resolved, error = self._resolve_axes(axes)
        if error:
            return {'success': False, 'message': error}
        if not resolved:
            return {'success': False, 'message': '녹화할 축이 없습니다 · X-Touch 에서 SELECT 로 축을 고르세요'}
        now = self._clock()
        take = Take(t0=now + COUNTDOWN_SEC)
        for item in resolved:
            take.add_axis(item)
        with self._lock:
            if self._take is not None:
                return {'success': False, 'message': '이미 녹화 중입니다 · 정지한 뒤 다시 시작하세요'}
            self._take = take
            self._owner = owner
            self._name = clean_name(name)
        return {'success': True, 'message': f'{COUNTDOWN_SEC:g}초 뒤 녹화 시작', **self.status()}

    def add_axes(self, owner: Any, axes: Any) -> Dict[str, Any]:
        """녹화 중 SELECT 로 더한 축 · 그 전 프레임은 지금 위치 그대로(그동안 안 움직였다)"""
        with self._lock:
            if self._take is None or self._owner is not owner:
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            known = set(self._take.axes)
        wanted = [axis for axis in _axis_list(axes) if axis not in known]
        if not wanted:
            return {'success': True, 'message': '', **self.status()}
        resolved, error = self._resolve_axes(wanted)
        if error:
            return {'success': False, 'message': error}
        with self._lock:
            if self._take is None or self._owner is not owner:
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            for item in resolved:
                self._take.add_axis(item)
        return {'success': True, 'message': '', **self.status()}

    def cancel(self, owner: Any) -> Dict[str, Any]:
        with self._lock:
            if self._take is None or self._owner is not owner:
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            self._take = None
            self._owner = None
        return {'success': True, 'state': 'idle', 'message': '녹화를 취소했습니다 · 저장하지 않았습니다'}

    def stop(self, owner: Any, end_wall: Optional[float] = None, *, reason: str = '') -> Dict[str, Any]:
        """정지 · 저장 · 카운트다운 중이면 저장할 것 없이 취소"""
        with self._lock:
            if self._take is None or self._owner is not owner:
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            take = self._take
            name = self._name
            self._take = None
            self._owner = None
        end = self._clock() if end_wall is None else float(end_wall)
        if end < take.t0 + PERIOD_SEC:
            return {'success': False, 'state': 'idle', 'message': '카운트다운 중에 멈췄습니다 · 저장할 녹화가 없습니다'}
        return self._save(take, name, end, reason)

    # ------------------------------------------------------------------ #

    def _block_reason(self) -> str:
        blocker = getattr(self.bridge, 'manual_range_blocker', None)
        return str(blocker() or '') if callable(blocker) else ''

    def _resolve_axes(self, axes: Any) -> Tuple[List[TakeAxis], str]:
        from .manual_range_gate import axis_rows   # 순환 import 피함

        rows, motors = self._mapping()
        positions = {}
        for motor in motors:
            index = motor.get('controller_index')
            value = motor.get('position_rad')
            try:
                positions[int(index)] = float(value)
            except (TypeError, ValueError):
                continue
        result = []
        for axis in _axis_list(axes):
            found = axis_rows(rows, motors, axis)
            if not found:
                return [], f'{axis}번 모터는 조인트 매핑의 「사용」 줄에 없습니다'
            for row in found:
                if not joint_mapping.rate_limits_set(row):
                    return [], (
                        f'축 {axis} ({row.get("motion_id")}) 속도·가속도 상한을 먼저 채우세요 · '
                        '조인트 매핑의 최대 속도·가속도'
                    )
            if axis not in positions or not math.isfinite(positions[axis]):
                return [], f'{axis}번 모터의 현재 위치를 읽을 수 없습니다'
            result.append(TakeAxis(axis=axis, rows=found, start_motor=positions[axis]))
        return result, ''

    def _save(self, take: Take, name: str, end: float, reason: str) -> Dict[str, Any]:
        joints = take.joint_series(end)
        frames = len(joints[0][2]) if joints else 0
        problem = rate_problem(joints)
        if problem:
            self._record_event('xtouch_record_refused', f'녹화 저장 거절 · {problem}', {'name': name})
            return {'success': False, 'state': 'idle', 'message': f'저장 안 함 · {problem}'}
        repository = self.bridge.project_repository
        try:
            project_id = repository.require_selected_project_id()
            file_name = save_unique(
                lambda candidate: repository.import_text(
                    project_id, 'motions', candidate, animation_text(candidate[:-len('.json')], joints)
                ),
                name,
            )
        except Exception as exc:  # noqa: BLE001 · 화면에 그대로
            self._record_event('xtouch_record_failed', f'녹화 저장 실패 · {exc}', {'name': name})
            return {'success': False, 'state': 'idle', 'message': f'저장 실패 · {exc}'}
        duration = frames * PERIOD_SEC
        content = f'X-Touch 녹화 저장 · {file_name} · {duration:.2f} s · {", ".join(j[0] for j in joints)}'
        if reason:
            content = f'{content} · {reason}'
        self._record_event('xtouch_record_saved', content, {
            'file': file_name, 'frames': frames, 'motion_ids': [j[0] for j in joints], 'reason': reason,
        })
        return {
            'success': True, 'state': 'saved', 'file': file_name, 'frames': frames,
            'duration_sec': duration, 'motion_ids': [j[0] for j in joints],
            'message': f'저장했습니다 · {file_name} · {duration:.2f} s' + (f' · {reason}' if reason else ''),
        }

    def _record_event(self, event_type: str, content: str, details: Dict[str, Any]) -> None:
        if self._event is None:
            return
        try:
            self._event(event_type, content, details)
        except Exception as exc:  # noqa: BLE001 · 기록 실패로 녹화를 막지 않는다 · 마지막 것만 둔다
            self.last_event_error = str(exc)


def _axis_list(axes: Any) -> List[int]:
    result: List[int] = []
    for value in axes if isinstance(axes, (list, tuple)) else []:
        try:
            axis = int(value)
        except (TypeError, ValueError):
            continue
        if axis >= 0 and axis not in result:
            result.append(axis)
    return result
