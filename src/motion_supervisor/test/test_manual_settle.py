"""조그 · 목표 이동 끝 판정 · 목표 근처 출렁임 · 실물 R-11 · R-14 (2026-10-13)

R-11 · 축2 +50° 조그 뒤 목표 117.21° 근처 114.6~119.3° 를 1 분 넘게 출렁였다 · 다음 조그가
「2번 모터의 이전 조그가 아직 돌고 있습니다」 로 다 막혔다 · 감독 노드는 이미 다 보냈다.
R-14 · 앞 이동이 끝나고 2 초 뒤 「1번 모터의 이전 동작이 아직 돌고 있습니다」.

순수 모듈만 본다(rclpy 없음) · supervisor 가 이것을 쓰는지는 원문으로 본다.
"""

import math
from pathlib import Path

from motion_supervisor import manual_settle as ms

R = math.radians
TOL = R(0.05)
DONE_V = R(0.05)
NEAR = ms.near_for(True)
TARGET = R(117.21)


def _verdict(active, position, velocity, now, *, settle=ms.JOG_SETTLE_SEC, timed_out=False, near=NEAR):
    ms.observe(active, position, velocity, DONE_V, now)
    return ms.verdict(
        position=position, velocity=velocity, target=active['target_position'],
        tolerance=TOL, done_velocity=DONE_V,
        commands_sent_at=active.get('commands_sent_at'),
        peak_error=active.get('settle_peak_error'), moving_at=active.get('settle_moving_at'),
        near=near, settle_sec=settle, now=now, timed_out=timed_out,
    )


def _hunting(t):
    """R-11 · 목표 ±2.4° · 주기 약 1 초"""
    position = TARGET + R(2.4) * math.sin(2.0 * math.pi * t)
    velocity = R(2.4) * 2.0 * math.pi * math.cos(2.0 * math.pi * t)
    return position, velocity


def test_a_clean_arrival_ends_at_once():
    active = {'target_position': TARGET, 'commands_sent_at': 100.0}
    assert _verdict(active, TARGET + R(0.01), 0.0, 100.1) == ms.ARRIVED


def test_hunting_near_the_target_ends_after_the_settle_window_with_a_notice():
    active = {'target_position': TARGET, 'commands_sent_at': 100.0}
    results = []
    t = 0.0
    while t < 10.0:   # motion_state 10 Hz
        position, velocity = _hunting(t)
        result = _verdict(active, position, velocity, 100.0 + t)
        results.append((t, result))
        if result != ms.WAIT:
            break
        t = round(t + 0.1, 3)
    end_t, end = results[-1]
    assert end == ms.HUNTING
    # 예전엔 120 초 · 이제 자리 잡기 3 초 + 꺾이는 순간 한 번 더 보는 만큼
    assert ms.JOG_SETTLE_SEC <= end_t < ms.JOG_SETTLE_SEC + 1.0
    text = ms.notice_text(2, end, position=_hunting(end_t)[0], target=TARGET, peak_error=active['settle_peak_error'])
    assert text.startswith('2번 모터가 목표 근처에서 출렁입니다')
    assert '게인(강성)을 확인하세요' in text
    assert '최대 ±2.' in text   # 10 Hz 로 본 꼭대기


def test_the_turning_point_of_a_swing_is_not_a_stop():
    """출렁임이 꺾이는 순간(속도 0)에 보면 「못 미치고 섬」 이 아니다"""
    active = {'target_position': TARGET, 'commands_sent_at': 100.0, 'settle_moving_at': 103.2}
    assert _verdict(active, TARGET + R(2.4), 0.0, 103.3) == ms.WAIT


def test_stopped_short_ends_with_a_notice_instead_of_waiting_two_minutes():
    active = {'target_position': TARGET, 'commands_sent_at': 100.0}
    assert _verdict(active, TARGET - R(0.8), 0.0, 101.0) == ms.WAIT
    assert _verdict(active, TARGET - R(0.8), 0.0, 103.1) == ms.SHORT
    text = ms.notice_text(1, ms.SHORT, position=TARGET - R(0.8), target=TARGET)
    assert '못 미치고 섰습니다' in text and '0.80°' in text


def test_trembling_inside_the_tolerance_counts_as_arrived():
    active = {'target_position': TARGET, 'commands_sent_at': 100.0}
    assert _verdict(active, TARGET + R(0.02), R(0.3), 103.5) == ms.ARRIVED


def test_moving_far_from_the_target_keeps_waiting_until_the_hard_timeout():
    active = {'target_position': TARGET, 'commands_sent_at': 100.0}
    assert _verdict(active, TARGET - R(30.0), R(20.0), 104.0) == ms.WAIT
    assert _verdict(active, TARGET - R(30.0), R(20.0), 300.0, timed_out=True) == ms.TIMEOUT


def test_nothing_ends_while_the_commands_are_still_going_out():
    active = {'target_position': TARGET}
    assert _verdict(active, TARGET - R(5.0), R(10.0), 500.0) == ms.WAIT
    assert 'settle_peak_error' not in active


def test_dynamixel_has_no_hunting_band():
    active = {'target_position': TARGET, 'commands_sent_at': 100.0}
    near = ms.near_for(False)
    assert near == 0.0
    position, velocity = _hunting(0.1)
    assert _verdict(active, position, velocity, 104.0, near=near) == ms.WAIT


def test_the_next_command_takes_over_only_after_sending_and_near_the_target():
    sending = {'target_position': TARGET}
    assert not ms.can_take_over(sending, TARGET, NEAR, TOL)
    sent = {'target_position': TARGET, 'commands_sent_at': 100.0}
    assert ms.can_take_over(sent, TARGET + R(2.4), NEAR, TOL)          # R-11 출렁임 중
    assert ms.can_take_over(sent, TARGET + R(0.06), NEAR, TOL)         # R-14 자리 잡는 중
    assert not ms.can_take_over(sent, TARGET + R(30.0), NEAR, TOL)     # 목표에서 멀다
    assert not ms.can_take_over(sent, None, NEAR, TOL)
    assert not ms.can_take_over(sent, TARGET + R(0.06), 0.0, TOL)      # 다이나믹셀 · 도착 오차만


def test_notices_expire():
    notices = {2: {'axis': 2, 'message': 'a', 'stamp': 1000.0}, 0: {'axis': 0, 'message': 'b', 'stamp': 1290.0}}
    assert [n['axis'] for n in ms.recent_notices(notices, 1100.0)] == [0, 2]
    assert [n['axis'] for n in ms.recent_notices(notices, 1000.0 + ms.NOTICE_KEEP_SEC + 1)] == [0]


SUPERVISOR = Path(__file__).resolve().parents[1] / 'motion_supervisor' / 'supervisor_node.py'


def test_supervisor_uses_the_settle_rules_everywhere():
    source = SUPERVISOR.read_text(encoding='utf-8')
    # 거절 문구는 한 곳(넘겨받기 판정 안)에만 · 조그 · 다이나믹셀 조그 · AC · 다이나믹셀 목표 이동 네 길이 다 그곳을 지난다
    assert source.count('아직 돌고 있습니다') == 1
    assert source.count('self._previous_manual_busy_message(axis)') == 4
    assert source.count('self._manual_settle_verdict(') == 2
    # 알림은 안전 상태에 실려 화면으로 간다
    assert "'manual_notices': manual_settle.recent_notices(" in source
