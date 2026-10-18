"""속도·가속 상한 램프 한 주기 · 수동 스트림(supervisor)과 X-Touch 구간 덮어쓰기(재생 노드)가 같이 쓴다

수정 목록 126 · 156 · 단위는 부르는 쪽 마음(모터 rad 든 조인트 rad 든 한 단위로만).
"""

from __future__ import annotations

import math

#: 이만큼 가까우면 도착 · rad · 조그 도착 판정(0.05°)보다 훨씬 작게
ARRIVE_RAD = math.radians(1e-4)


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
    # 남은 거리에서 멈출 수 있는 최고 속도 · 이번 주기에 s·dt 를 가고도 그 뒤 주기마다 dv 씩 줄여
    # 멈출 수 있게(s·dt + s²/2a + s·dt/2 ≤ 거리) · 고정 목표를 지나치지 않는다
    braking = math.sqrt(max(0.0, 2.0 * amax * abs(distance) + (1.5 * dv) ** 2)) - 1.5 * dv
    wanted = math.copysign(min(vmax, max(braking, 0.0)), distance)
    change = max(-dv, min(dv, wanted - velocity))
    new_velocity = velocity + change
    return position + new_velocity * dt, new_velocity, False
