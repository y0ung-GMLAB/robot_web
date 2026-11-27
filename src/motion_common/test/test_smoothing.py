"""X-Touch 스무딩 · 화면은 날 값 · 거르는 것은 중간 · 수정 목록 156 (사용자 결정 2026-10-19)"""

import math

from motion_common import punch, smoothing
from motion_common.smoothing import Smoother, smooth_sec_from

R = math.radians
DT = 0.02


def test_smooth_sec_from_clamps_and_defaults():
    assert smooth_sec_from(None) == 0.0
    assert smooth_sec_from('x') == 0.0
    assert smooth_sec_from(-1) == 0.0
    assert smooth_sec_from(float('nan')) == 0.0
    assert smooth_sec_from(0.25) == 0.25
    assert smooth_sec_from(9) == smoothing.MAX_SMOOTH_SEC


def test_zero_passes_raw_through():
    s = Smoother(0.0)
    assert s.update(1.0, DT, 0.0) == 1.0
    assert s.settled(1.0)


def test_step_has_no_velocity_jump_and_settles():
    """계단 하나 · 두 번 거르면 첫 주기 움직임이 아주 작고(속도 튐 없음) · 고른 시간쯤에 대부분 · 결국 닿는다"""
    s = Smoother(0.0)
    values = [s.update(1.0, DT, 0.25) for _ in range(200)]
    assert values[0] < 0.03
    assert 0.45 < values[int(0.25 / DT) - 1] < 0.75
    steps = [b - a for a, b in zip([0.0] + values, values)]
    assert all(b >= -1e-12 for b in steps), '넘치지 않음'
    assert max(abs(b - a) for a, b in zip(steps, steps[1:])) < 0.02, '속도가 툭 뛰지 않음'
    assert values[-1] == 1.0 and s.settled(1.0)


def test_punch_live_follows_smoothed_and_blends_after_settle():
    """펀치 · 잡자마자 날 값으로 안 튐 · 놓으면 거른 값이 닿은 뒤 원본으로"""
    joints = {'neck_yaw': {'max_velocity': R(20), 'max_acceleration': R(80)}}
    controller = punch.PunchController(joints, DT)
    original = [0.0] * 2000
    now = 0.0
    controller.frame({'neck_yaw': original}, now)
    controller.input('neck_yaw', R(5), now, smooth_sec=0.5)
    sent = []
    for frame in range(1, 400):
        now = frame * DT
        if frame == 5:
            controller.release('neck_yaw')
        value, state = controller.frame({'neck_yaw': original[frame:]}, now)['neck_yaw']
        sent.append((value, state))
    assert sent[0][0] < R(0.05), '첫 프레임은 조금만'
    reached = next(i for i, (v, _) in enumerate(sent) if v >= R(5) - 1e-6)
    assert reached > int(0.5 / DT), '거른 시간보다 늦게 닿음'
    assert any(state == punch.BLEND for _, state in sent[reached:]), '닿은 뒤 원본으로 잇기'
    assert all(state == punch.LIVE for _, state in sent[:reached]), '닿기 전엔 잇지 않음'
