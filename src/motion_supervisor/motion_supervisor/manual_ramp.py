"""수동 스트림(페이더 · 다이얼) 램프 · 수정 목록 126 (사용자 결정 2026-10-13)

화면이 보내는 목표는 「가고 싶은 곳」 · 실제로 모터에 보내는 목표는 주기마다 속도·가속
상한만큼만 다가간다 · 페이더 트랙을 잘못 찍어도 그 자리까지 천천히 간다.

    놓음(release)     멈추지 않고 마지막 목표까지 · 도착하면 끝
    같은 조작         새 목표로 바꿈 · 방향을 바꾸면 가속 상한으로 줄였다가 돌아섬
    다른 조작         움직이는 중이면 거절(페이더 가는 중 다이얼 등)
    정지 · 끊김(hold) 그 자리에서 끝

순수 계산만 · 시험은 이것을 본다 · 주기 · 발행은 supervisor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict

#: 이만큼 가까우면 도착 · rad (모터) · 조그 도착 판정(0.05°)보다 훨씬 작게
ARRIVE_RAD = math.radians(1e-4)
#: 도착한 채 목표가 안 오면 끝낸다 · 화면이 놓기 없이 사라져도 남지 않게 · 초
IDLE_EXPIRE_SEC = 1.0
#: 출처가 없으면(옛 화면 · MIDI) 이 이름 · 같은 출처끼리는 새 목표로 바꾼다
DEFAULT_SOURCE = 'stream'
SOURCE_LABELS = {'fader': '페이더', 'dial': '다이얼', 'xtouch': 'X-Touch', DEFAULT_SOURCE: '수동 스트림'}


def step(
    position: float,
    velocity: float,
    goal: float,
    max_velocity: float,
    max_acceleration: float,
    dt: float,
) -> tuple[float, float, bool]:
    """한 주기 · (새 위치, 새 속도, 도착) · 속도·가속 상한 · 목표에서 멈출 수 있게 미리 줄인다

    속도 = 이번 주기에 간 거리 ÷ 주기 · 그래서 보낸 목표를 차분으로 재도 상한 안이다(재생 검사
    `plan_builder._motion_rate_limit_error` 와 같은 잣대 · 녹화 파일이 그대로 재생된다 · 수정 목록 156) ·
    전에는 목표에 「바로 세우기」 가 두 군데 있어 차분 가속이 상한의 몇 배가 됐다(움직이는 목표가 갑자기
    가까워지면 빠른 채로 그 자리에 섰다) · 이제 못 서면 지나쳤다가 돌아온다.
    """
    vmax = abs(float(max_velocity))
    amax = abs(float(max_acceleration))
    dt = max(float(dt), 1e-6)
    dv = amax * dt
    distance = goal - position
    # 목표에 세울 수 있나 · 이번 주기 속도(거리 ÷ 주기)로 바꾸는 것도, 다음 주기 0 으로 서는 것도 상한 안 ·
    # 도착 속도는 그대로 돌려준다(0 이 아니라) · 다음 주기가 새 목표면 그 속도에서 이어 간다
    landing = distance / dt
    if abs(landing) <= min(dv, vmax) * (1 + 1e-9) and abs(landing - velocity) <= dv * (1 + 1e-9):
        return goal, landing, True
    # 남은 거리에서 멈출 수 있는 최고 속도 · 주기마다 dv 씩 줄이면 s·dt + (s − dv)·dt + … ≤ 거리
    braking = math.sqrt(max(0.0, 2.0 * amax * abs(distance) + (dv / 2.0) ** 2)) - dv / 2.0
    wanted = math.copysign(min(vmax, max(braking, 0.0)), distance)
    change = max(-dv, min(dv, wanted - velocity))
    new_velocity = velocity + change
    return position + new_velocity * dt, new_velocity, False


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

    @property
    def moving(self) -> bool:
        return not self.arrived

    def retarget(self, goal: float, max_velocity: float, max_acceleration: float, request: Dict[str, Any], now: float) -> None:
        self.goal = float(goal)
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
            self.position, self.velocity, arrived = step(
                self.position, self.velocity, self.goal,
                self.max_velocity, self.max_acceleration, dt,
            )
            if arrived:
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


def source_of(request: Any) -> str:
    value = str((request or {}).get('source') or '').strip().lower() if isinstance(request, dict) else ''
    return value or DEFAULT_SOURCE


def conflict_message(axis: int, ramp: AxisRamp, source: str) -> str:
    """다른 조작이 움직이는 축에 들어왔을 때 · 빈 글자면 받아도 됨"""
    if ramp.arrived or ramp.source == source:
        return ''
    label = SOURCE_LABELS.get(ramp.source, ramp.source)
    return f'{axis}번 모터 이동 중({label}) · 도착하거나 「동작 취소」 뒤에 조작하세요'
