"""X-Touch 구간 덮어쓰기(펀치인) · 재생 노드가 프레임마다 부른다 · 수정 목록 156 ⑨-2 (사용자 결정 2026-10-17)

기존 애니메이션을 재생하는 중에 사람이 페이더를 잡으면 그 조인트만 사람 손으로 바꾼다 ·
놓으면 원본으로 돌아간다 · 재생 노드가 하므로 프레임 번호와 앞으로 올 원본 값을 정확히 안다 ·
그래서 보낸 값이 그대로 녹화 파일이 된다(재생과 같은 값 · 이음매가 없다).

    재생(play)    원본 값 그대로
    잡음(live)    램프(`motion_common.ramp`)가 페이더 목표로 · 시작은 지금 위치·속도 그대로(튐 없음) ·
                  상한 = 조인트 매핑 최대 속도·가속도
    놓음          마지막 목표까지 간 뒤
    잇기(blend)   선 자리(h)에서 원본(o)으로 · x = (1 − w)·h + w·o · w 는 5차 smoothstep(끝에서 속도·가속 0) ·
                  길이 = 상한 안에 드는 가장 짧은 길이 · 최소 0.5 초 · 잇는 중에 다시 잡으면 그 자리·속도에서 잡음
    끊김          잡은 채 입력이 0.5 초 안 오면(화면이 사라짐) 놓은 것으로

값은 모두 조인트 rad · 순수 계산만 · 시험은 이것을 본다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Dict, List, Optional, Tuple

from .ramp import step as ramp_step

#: 잇는 최소 길이 · 사용자 결정 2026-10-17
MIN_BLEND_SEC = 0.5
#: 잇는 길이를 늘려 보는 간격 · 프레임 · 길수록 20 % 씩(한 프레임 안에 끝나게 · 재생 주기 20 ms)
BLEND_STEP_FRAMES = 5
BLEND_GROWTH = 1.2
#: 잇는 최대 길이 · 이 안에 못 맞추면 이 길이로 잇고 상한 넘음으로 알린다(저장 검사가 막는다)
MAX_BLEND_SEC = 10.0
#: 잡은 채 입력이 이만큼 안 오면 놓은 것으로 · 초
INPUT_TIMEOUT_SEC = 0.5
#: 상한 비교 여유 · 재생 검사(`rate_check`)와 같다
TOLERANCE = 1e-6

PLAY = 'play'
LIVE = 'live'
BLEND = 'blend'


class SeriesTail(Sequence):
    """원본 목록의 뒷부분 · 복사하지 않는다(재생 노드가 프레임마다 만든다 · 10분 = 3만 값)"""

    def __init__(self, values: Sequence[float], start: int = 0) -> None:
        self._values = values
        self._start = max(0, int(start))

    def __len__(self) -> int:
        return max(0, len(self._values) - self._start)

    def __getitem__(self, index):
        if isinstance(index, slice):
            if index.step not in (None, 1):
                raise ValueError('step 은 1 만')
            start = 0 if index.start is None else int(index.start)
            if index.stop is None:
                return SeriesTail(self._values, self._start + start)
            return list(self._values[self._start + start:self._start + int(index.stop)])
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self._values[self._start + index]


def smoother(s: float) -> float:
    """0 → 1 · 양 끝에서 1·2차 미분 0 (5차)"""
    s = min(1.0, max(0.0, s))
    return s * s * s * (10.0 + s * (-15.0 + 6.0 * s))


def blend_values(hold: float, original: Sequence[float]) -> List[float]:
    """선 자리 → 원본 · 마지막 값 = 원본 · 길이 = len(original)"""
    count = len(original)
    return [
        (1.0 - w) * hold + w * float(value)
        for value, w in ((original[i], smoother((i + 1) / count)) for i in range(count))
    ]


def within_limits(values: Sequence[float], vmax: float, amax: float, dt: float) -> bool:
    """차분 속도·가속 · 재생 검사와 같은 잣대"""
    velocities = [(b - a) / dt for a, b in zip(values, values[1:])]
    if any(abs(v) > vmax * (1 + TOLERANCE) for v in velocities):
        return False
    return all(abs(b - a) / dt <= amax * (1 + TOLERANCE) for a, b in zip(velocities, velocities[1:]))


def plan_blend(
    before: Sequence[float],
    hold: float,
    original: Sequence[float],
    vmax: float,
    amax: float,
    dt: float,
) -> Tuple[List[float], bool]:
    """잇는 값 · (값들, 상한 안인가)

    before   이미 보낸 마지막 두 값(앞 이음매 검사)
    original 지금 프레임부터 끝까지 원본 · 잇기는 이 앞부분을 덮는다
    짧은 길이부터 늘려 본다(0.5 초 · 5 프레임 또는 20 % 씩) · 10 초(또는 끝)까지 못 맞추면 그 길이로 잇고
    False(저장 검사가 막는다)
    """
    total = min(len(original), max(1, int(round(MAX_BLEND_SEC / dt))))
    if total == 0:
        return [], True
    first = max(1, int(math.ceil(MIN_BLEND_SEC / dt - 1e-9)))
    count = min(first, total)
    while True:
        values = blend_values(hold, original[:count])
        after = list(original[count:count + 2])
        if within_limits(list(before[-2:]) + values + after, vmax, amax, dt):
            return values, True
        if count >= total:
            return values, False
        count = min(total, max(count + BLEND_STEP_FRAMES, int(count * BLEND_GROWTH)))


@dataclass
class PunchJoint:
    """조인트 하나 · 마지막으로 보낸 값과 속도를 늘 들고 있다(잡을 때 그 자리·속도에서)"""

    motion_id: str
    max_velocity: float
    max_acceleration: float
    lower: float = -math.inf
    upper: float = math.inf
    state: str = PLAY
    position: Optional[float] = None
    velocity: float = 0.0
    sent: List[float] = field(default_factory=list)
    target: Optional[float] = None
    released: bool = False
    last_input_at: float = 0.0
    blend: List[float] = field(default_factory=list)
    blend_ok: bool = True

    def clamp(self, value: float) -> float:
        return min(self.upper, max(self.lower, float(value)))


class PunchController:
    """한 번 재생 · 조인트마다 상태 · 입력은 다른 실(화면 → 브리지 → 재생 노드)이 넣으니 부르는 쪽이 잠근다"""

    def __init__(self, joints: Dict[str, Dict[str, float]], dt: float) -> None:
        self.dt = float(dt)
        self.joints: Dict[str, PunchJoint] = {
            str(motion_id): PunchJoint(
                motion_id=str(motion_id),
                max_velocity=float(spec['max_velocity']),
                max_acceleration=float(spec['max_acceleration']),
                lower=float(spec.get('lower', -math.inf)),
                upper=float(spec.get('upper', math.inf)),
            )
            for motion_id, spec in (joints or {}).items()
        }

    def input(self, motion_id: str, target: float, now: float) -> bool:
        joint = self.joints.get(str(motion_id))
        if joint is None or not math.isfinite(float(target)):
            return False
        joint.target = joint.clamp(target)
        joint.released = False
        joint.last_input_at = float(now)
        if joint.state != LIVE:
            # 재생·잇기 중이던 자리와 속도 그대로에서 램프 시작
            joint.state = LIVE
            joint.blend = []
        return True

    def release(self, motion_id: str) -> bool:
        joint = self.joints.get(str(motion_id))
        if joint is None or joint.state != LIVE:
            return False
        joint.released = True
        return True

    def active(self) -> bool:
        return any(joint.state != PLAY for joint in self.joints.values())

    def frame(self, original_from: Dict[str, Sequence[float]], now: float) -> Dict[str, Tuple[float, str]]:
        """한 프레임 · 조인트마다 (보낼 값, 상태) · original_from = 조인트 → 이 프레임부터 끝까지 원본"""
        out: Dict[str, Tuple[float, str]] = {}
        for motion_id, joint in self.joints.items():
            original = original_from.get(motion_id)
            if not original:
                continue
            state = joint.state
            if state == LIVE:
                if not joint.released and now - joint.last_input_at > INPUT_TIMEOUT_SEC:
                    joint.released = True
                start = joint.position if joint.position is not None else float(original[0])
                value, joint.velocity, arrived = ramp_step(
                    start, joint.velocity, joint.target if joint.target is not None else start,
                    joint.max_velocity, joint.max_acceleration, self.dt,
                )
                # 목표가 끝에서 멈추면 못 서고 조금 지날 수 있다 · 조인트 범위 밖으로는 안 보낸다
                value = joint.clamp(value)
                if arrived and joint.released:
                    # 다음 프레임부터 원본으로 잇는다 · 앞 이음매는 이번 값까지 넣어 잰다
                    joint.blend, joint.blend_ok = plan_blend(
                        joint.sent[-1:] + [value], value, original[1:],
                        joint.max_velocity, joint.max_acceleration, self.dt,
                    )
                    joint.state = BLEND if joint.blend else PLAY
            elif state == BLEND:
                value = joint.blend.pop(0)
                if not joint.blend:
                    joint.state = PLAY
            else:
                value = float(original[0])
            if joint.position is not None and state != LIVE:
                joint.velocity = (value - joint.position) / self.dt
            joint.position = value
            joint.sent = (joint.sent + [value])[-2:]
            out[motion_id] = (value, state)
        return out
