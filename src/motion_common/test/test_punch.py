"""X-Touch 구간 덮어쓰기 · 재생 중 잡기 · 놓으면 원본으로 잇기 · 수정 목록 156 ⑨-2"""

import math

from motion_common import punch, rate_check

DT = 0.02
R = math.radians
VMAX, AMAX = R(13.0), R(35.0)


def _original(seconds=20.0):
    count = int(seconds / DT)
    return [R(8.0) * math.sin(2 * math.pi * 0.15 * k * DT) for k in range(count)]


def _run(original, events):
    """events · 프레임 → [('input', 값) | ('release',)] · 보낸 값 · 상태 목록"""
    controller = punch.PunchController({'eye': {'max_velocity': VMAX, 'max_acceleration': AMAX,
                                                'lower': R(-11.3), 'upper': R(11.3)}}, DT)
    sent, states = [], []
    for k in range(len(original)):
        now = k * DT
        for event in events.get(k, []):
            if event[0] == 'input':
                controller.input('eye', event[1], now)
            else:
                controller.release('eye')
        value, state = controller.frame({'eye': original[k:]}, now)['eye']
        sent.append(value)
        states.append(state)
    return sent, states


def _check(values):
    rows = [{'time_sec': (k + 1) * DT, 'motion_values': {'eye': v}} for k, v in enumerate(values)]
    axis = [{'motion_id': 'eye', 'row': {'max_velocity_rad_s': VMAX, 'max_acceleration_rad_s2': AMAX}}]
    return rate_check.rate_limit_error(axis, rows, DT)


def test_without_input_the_original_goes_out_unchanged():
    original = _original(5.0)
    sent, states = _run(original, {})
    assert sent == original
    assert set(states) == {'play'}


def test_grab_move_release_rejoins_the_original_inside_the_limits():
    original = _original()
    events = {100: [('input', R(-5.0))]}
    # 끄는 동안 목표가 계속 옴(0.02 s 마다)
    for k in range(101, 300):
        events.setdefault(k, []).append(('input', R(-5.0) + R(6.0) * (k - 100) / 200))
    events[300] = [('release',)]
    sent, states = _run(original, events)
    assert sent[:100] == original[:100]                              # 잡기 전은 원본 그대로
    assert 'live' in states and 'blend' in states
    back = states.index('play', 300)
    assert sent[back:] == original[back:]                            # 다 이은 뒤는 원본 그대로
    assert abs(sent[back - 1] - original[back - 1]) < 1e-12          # 잇기 끝 = 원본
    blend_frames = states.count('blend')
    assert blend_frames >= int(punch.MIN_BLEND_SEC / DT)             # 최소 0.5 초
    assert _check(sent) == ''                                        # 저장 검사와 같은 잣대 · 통과
    assert max(abs(v - o) for v, o in zip(sent[150:250], original[150:250])) > R(2.0)   # 실제로 바뀌었다


def test_regrab_during_the_blend_continues_from_where_it_is():
    original = _original()
    events = {50: [('input', R(6.0))]}
    for k in range(51, 120):
        events.setdefault(k, []).append(('input', R(6.0)))
    events[120] = [('release',)]
    sent, states = _run(original, {**events, 200: [('input', R(-2.0))], 230: [('release',)]})
    assert _check(sent) == ''
    assert states[-1] == 'play'


def test_a_silent_screen_counts_as_released():
    original = _original(10.0)
    sent, states = _run(original, {20: [('input', R(4.0))]})       # 한 번 잡고 끊김
    assert 'blend' in states and states[-1] == 'play'
    assert _check(sent) == ''


def test_targets_are_kept_inside_the_joint_range():
    original = [0.0] * 600
    sent, _ = _run(original, {k: [('input', R(40.0))] for k in range(10, 400)})
    assert max(sent) <= R(11.3) + 1e-12


def test_plan_blend_reports_when_it_cannot_fit():
    values, ok = punch.plan_blend([0.0, 0.0], 0.0, [R(10.0)] * 30, VMAX, AMAX, DT)
    assert ok is False and len(values) == 30
    values, ok = punch.plan_blend([0.0, 0.0], 0.0, [R(1.0)] * 400, VMAX, AMAX, DT)
    assert ok is True and len(values) >= 25
