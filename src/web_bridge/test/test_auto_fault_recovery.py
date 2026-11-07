"""통신성 드라이브 알람 자동 초기화 · 수정 목록 178 (2026-11-08)

통신성(Err80 · 81 · 84 · 85 · 88)만 · 스케줄 모드만 · 2 s 그대로일 때 · 축마다 1시간 3번 ·
기구 · 부하성(과부하 · 위치 편차 · 리밋)은 자동으로 하지 않는다.
"""

from motion_web_bridge.auto_fault_recovery import (
    AUTO_RESET_CODES, LIMIT, RETRY_GAP_SEC, SETTLE_SEC, WINDOW_SEC, AutoFaultRecovery,
)


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _motor(axis, code, fault=True):
    return {'controller_index': axis, 'errorcode': code, 'fault': fault}


def _axes(plan):
    return [item['axis'] for item in plan['reset']]


def test_only_communication_alarms_are_reset_automatically():
    assert {80, 81, 84, 85, 88} <= set(AUTO_RESET_CODES)
    for mechanical in (16, 24, 38, 14, 15):
        assert mechanical not in AUTO_RESET_CODES


def test_a_communication_alarm_is_reset_after_it_settles():
    clock = _Clock()
    recovery = AutoFaultRecovery(clock=clock)
    motors = [_motor(2, 80)]
    assert _axes(recovery.plan(motors, enabled=True)) == [], '처음 보자마자는 하지 않는다'
    clock.now += SETTLE_SEC + 0.1
    plan = recovery.plan(motors, enabled=True)
    assert plan['reset'] == [{'axis': 2, 'code': 80, 'attempt': 1}]


def test_mechanical_alarms_and_warnings_are_left_alone():
    clock = _Clock()
    recovery = AutoFaultRecovery(clock=clock)
    motors = [_motor(0, 16), _motor(1, 24), _motor(2, 0xA0)]
    recovery.plan(motors, enabled=True)
    clock.now += 60.0
    assert recovery.plan(motors, enabled=True) == {'reset': [], 'exhausted': []}


def test_nothing_happens_outside_schedule_mode():
    clock = _Clock()
    recovery = AutoFaultRecovery(clock=clock)
    motors = [_motor(2, 80)]
    recovery.plan(motors, enabled=False)
    clock.now += 60.0
    assert _axes(recovery.plan(motors, enabled=False)) == []


def test_three_tries_an_hour_then_once_a_note_and_the_head_stays_stopped():
    clock = _Clock()
    recovery = AutoFaultRecovery(clock=clock)
    motors = [_motor(3, 85)]
    recovery.plan(motors, enabled=True)
    clock.now += SETTLE_SEC + 0.1
    attempts = []
    for _ in range(LIMIT):
        attempts += [item['attempt'] for item in recovery.plan(motors, enabled=True)['reset']]
        clock.now += RETRY_GAP_SEC + 0.1
    assert attempts == [1, 2, 3]
    plan = recovery.plan(motors, enabled=True)
    assert plan['reset'] == [] and plan['exhausted'] == [{'axis': 3, 'code': 85}]
    clock.now += RETRY_GAP_SEC + 0.1
    assert recovery.plan(motors, enabled=True) == {'reset': [], 'exhausted': []}, '알림은 한 번'
    clock.now += WINDOW_SEC
    assert _axes(recovery.plan(motors, enabled=True)) == [3], '1시간이 지나면 다시'


def test_a_cleared_alarm_starts_counting_the_settle_time_again():
    clock = _Clock()
    recovery = AutoFaultRecovery(clock=clock)
    recovery.plan([_motor(1, 80)], enabled=True)
    clock.now += SETTLE_SEC + 0.1
    assert _axes(recovery.plan([_motor(1, 80)], enabled=True)) == [1]
    recovery.plan([_motor(1, 0, fault=False)], enabled=True)     # 풀렸다
    clock.now += RETRY_GAP_SEC + 0.1
    assert _axes(recovery.plan([_motor(1, 80)], enabled=True)) == [], '다시 2 s 를 센다'
    clock.now += SETTLE_SEC + 0.1
    assert recovery.plan([_motor(1, 80)], enabled=True)['reset'][0]['attempt'] == 2, '한도 기록은 남는다'


def test_axes_are_counted_separately_and_bad_rows_are_ignored():
    clock = _Clock()
    recovery = AutoFaultRecovery(clock=clock)
    motors = [_motor(0, 80), _motor(1, 88), {'fault': True}, 'junk', None]
    recovery.plan(motors, enabled=True)
    clock.now += SETTLE_SEC + 0.1
    assert sorted(_axes(recovery.plan(motors, enabled=True))) == [0, 1]
