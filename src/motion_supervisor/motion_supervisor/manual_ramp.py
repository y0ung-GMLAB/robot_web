"""수동 스트림(페이더 · 다이얼) 램프 · 수정 목록 126 (사용자 결정 2026-10-13)

화면이 보내는 목표는 「가고 싶은 곳」 · 실제로 모터에 보내는 목표는 주기마다 속도·가속
상한만큼만 다가간다 · 페이더 트랙을 잘못 찍어도 그 자리까지 천천히 간다.

    놓음(release)     멈추지 않고 마지막 목표까지 · 도착하면 끝
    같은 조작         새 목표로 바꿈 · 방향을 바꾸면 가속 상한으로 줄였다가 돌아섬
    다른 조작         움직이는 중이면 거절(페이더 가는 중 다이얼 등)
    정지 · 끊김(hold) 그 자리에서 끝

X-Touch 는 날 값을 보내고 스무딩은 여기서 · 램프 앞에 `motion_common.smoothing` (요청 `smooth_sec` ·
화면에서 고름 · 0 이면 안 거름 · 사용자 결정 2026-10-19 · 수정 목록 156) · 놓은 뒤에도 거른 값이 날 값에 닿을 때까지 간다.

순수 계산만 · 시험은 이것을 본다 · 주기 · 발행은 supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# 한 주기 계산은 motion_common 하나 · X-Touch 구간 덮어쓰기(재생 노드)도 같은 램프 · 수정 목록 156
from motion_common.ramp import ARRIVE_RAD, step  # noqa: F401 · step 은 이 모듈 이름으로도 쓴다
from motion_common.smoothing import Smoother, smooth_sec_from
#: 도착한 채 목표가 안 오면 끝낸다 · 화면이 놓기 없이 사라져도 남지 않게 · 초
IDLE_EXPIRE_SEC = 1.0
#: 출처가 없으면(옛 화면 · MIDI) 이 이름 · 같은 출처끼리는 새 목표로 바꾼다
DEFAULT_SOURCE = 'stream'
SOURCE_LABELS = {'fader': '페이더', 'dial': '다이얼', 'xtouch': 'X-Touch', DEFAULT_SOURCE: '수동 스트림'}


@dataclass
class AxisRamp:
    """축 하나 · 값은 모두 모터 rad · rad/s"""

    axis: int
    goal: float
    position: float
    max_velocity: float
    max_acceleration: float
    source: str = DEFAULT_SOURCE
    velocity: float = 0.0
    released: bool = False
    arrived: bool = False
    updated_at: float = 0.0
    arrived_at: float = 0.0
    #: 결과·발행에 실을 마지막 요청 칸(request_id · motion_id · channel …)
    request: Dict[str, Any] = field(default_factory=dict)
    #: 스무딩 시간 · 초 · 0 이면 안 거름 · `goal` 은 날 값 그대로, 램프는 거른 값을 따라간다
    smooth_sec: float = 0.0
    smoother: Optional[Smoother] = None

    def __post_init__(self) -> None:
        # 지금 자리에서 시작 · 잡자마자 날 값으로 튀지 않게
        if self.smoother is None:
            self.smoother = Smoother(self.position)

    @property
    def moving(self) -> bool:
        return not self.arrived

    def retarget(
        self, goal: float, max_velocity: float, max_acceleration: float, request: Dict[str, Any], now: float,
        smooth_sec: float = 0.0,
    ) -> None:
        self.goal = float(goal)
        self.smooth_sec = float(smooth_sec)
        self.max_velocity = float(max_velocity)
        self.max_acceleration = float(max_acceleration)
        self.request = dict(request)
        self.released = False
        self.updated_at = now
        if abs(self.goal - self.position) > ARRIVE_RAD:
            self.arrived = False

    def advance(self, dt: float, now: float) -> float:
        """한 주기 움직이고 보낼 목표를 돌려준다"""
        if not self.arrived:
            smoothed = self.smoother.update(self.goal, dt, self.smooth_sec)
            self.position, self.velocity, reached = step(
                self.position, self.velocity, smoothed,
                self.max_velocity, self.max_acceleration, dt,
            )
            # 거른 값이 아직 날 값으로 가는 중이면 안 끝남 · 램프는 그 값에 닿은 속도 그대로 이어 간다
            if reached and self.smoother.settled(self.goal):
                self.arrived = True
                self.arrived_at = now
        else:
            # 서 있는 주기 · 같은 값을 보내므로 차분 속도 0 · 다음 새 목표는 0 에서 (수정 목록 156)
            self.velocity = 0.0
        return self.position

    def finished(self, now: float) -> bool:
        """도착했고 놓았거나, 도착한 채 목표가 한동안 안 왔으면 끝"""
        if not self.arrived:
            return False
        return self.released or now - max(self.updated_at, self.arrived_at) >= IDLE_EXPIRE_SEC


def smooth_of(request: Any) -> float:
    """요청의 스무딩 시간 · 초 · X-Touch 만 싣는다 · 없으면 0"""
    return smooth_sec_from(request.get('smooth_sec')) if isinstance(request, dict) else 0.0


def source_of(request: Any) -> str:
    value = str((request or {}).get('source') or '').strip().lower() if isinstance(request, dict) else ''
    return value or DEFAULT_SOURCE


def conflict_message(axis: int, ramp: AxisRamp, source: str) -> str:
    """다른 조작이 움직이는 축에 들어왔을 때 · 빈 글자면 받아도 됨"""
    if ramp.arrived or ramp.source == source:
        return ''
    label = SOURCE_LABELS.get(ramp.source, ramp.source)
    return f'{axis}번 모터 이동 중({label}) · 도착하거나 「동작 취소」 뒤에 조작하세요'
