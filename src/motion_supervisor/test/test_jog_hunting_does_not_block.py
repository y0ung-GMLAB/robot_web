"""조그 뒤 드라이브가 목표 근처에서 출렁여도 다음 조작을 막지 않는다 · 실물 R-11 · R-14 (2026-10-13)

판정 자체는 `test_manual_settle.py` · 여기는 supervisor 가 그 판정으로 조그 · 동작을 끝내고
알림을 안전 상태에 싣는지 · 다음 조작이 넘겨받는지.
"""

import math
import threading
import time

from motion_supervisor import manual_settle
from motion_supervisor.command_arbiter import CommandArbiter
from motion_supervisor.supervisor_node import MotionSupervisor

R = math.radians


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, **_kwargs):
        self.warnings.append(message)

    warn = warning

    def info(self, *_a, **_k):
        pass


def _supervisor(position_deg, velocity_deg_s, axis=2):
    motors = [{
        'controller_index': axis, 'state': 'detected', 'motor_type': 'ac_servo',
        'servo_on': True, 'fault': False,
        'position_rad': R(position_deg), 'velocity_rad_s': R(velocity_deg_s),
    }]
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._active_jogs = {}
    supervisor._active_actions = {}
    supervisor._action_threads = {}
    supervisor._jog_threads = {}
    supervisor._manual_notices = {}
    supervisor._emergency_latched = False
    supervisor._motion_stop_block_until = 0.0
    supervisor._command_lock = threading.RLock()
    supervisor._command_arbiter = CommandArbiter()
    supervisor.state_timeout_sec = 1.0
    supervisor.action_period_sec = 0.02
    supervisor._current_motors = lambda: motors
    logger = _Logger()
    supervisor.get_logger = lambda: logger
    results = []
    supervisor._publish_action_result = lambda request_id, success, message: results.append((request_id, success, message))
    return supervisor, logger, results


def _jog(target_deg, *, sent_ago):
    now = time.time()
    return {
        'request_id': 'jog-1', 'target_position': R(target_deg),
        'started_at': now - sent_ago - 1.0, 'commands_sent_at': now - sent_ago,
        'applied_duration_sec': 1.0, 'steps': 5.0, 'last_step': 5.0,
    }


def test_hunting_jog_is_finished_with_a_notice_after_the_settle_window():
    supervisor, logger, _ = _supervisor(119.3, 12.0)   # R-11 · 목표 117.21 근처 114.6~119.3
    supervisor._active_jogs[2] = _jog(117.21, sent_ago=manual_settle.JOG_SETTLE_SEC + 0.5)
    supervisor._clear_completed_jogs()
    assert 2 not in supervisor._active_jogs
    notices = supervisor._manual_activity_snapshot()['manual_notices']
    assert [n['axis'] for n in notices] == [2]
    assert notices[0]['kind'] == 'hunting'
    assert '게인(강성)을 확인하세요' in notices[0]['message']
    assert logger.warnings and '출렁입니다' in logger.warnings[0]


def test_a_jog_still_inside_the_settle_window_keeps_waiting():
    supervisor, _, _ = _supervisor(119.3, 12.0)
    supervisor._active_jogs[2] = _jog(117.21, sent_ago=1.0)
    supervisor._clear_completed_jogs()
    assert 2 in supervisor._active_jogs
    assert supervisor._manual_activity_snapshot()['manual_notices'] == []


def test_the_next_jog_takes_over_a_hunting_one_instead_of_being_refused():
    supervisor, _, _ = _supervisor(119.3, 12.0)
    supervisor._active_jogs[2] = _jog(117.21, sent_ago=1.0)
    assert supervisor._previous_manual_busy_message(2) == ''
    assert 2 not in supervisor._active_jogs


def test_a_jog_still_sending_is_refused_with_where_the_motor_is():
    supervisor, _, _ = _supervisor(60.0, 300.0)
    active = _jog(117.21, sent_ago=0.0)
    active.pop('commands_sent_at')
    supervisor._active_jogs[2] = active
    message = supervisor._previous_manual_busy_message(2)
    assert message.startswith('2번 모터의 이전 조그가 아직 돌고 있습니다')
    assert '목표 117.210 deg' in message and '지금 60.000 deg' in message


def test_a_settling_action_is_taken_over_and_reported_done():
    """R-14 · 앞 이동이 끝나고 2 초 · 자리 잡는 중 · 다음 조작이 이어받는다"""
    supervisor, _, results = _supervisor(30.06, 0.2, axis=1)
    supervisor._active_actions[1] = {**_jog(30.0, sent_ago=1.0), 'request_id': 'act-1', 'label': 'AC Servo'}
    assert supervisor._previous_manual_busy_message(1) == ''
    assert 1 not in supervisor._active_actions
    assert results and results[-1][0] == 'act-1' and results[-1][1] is True


def test_a_hunting_action_completes_with_the_notice_in_its_result():
    supervisor, _, results = _supervisor(32.0, 15.0, axis=1)
    supervisor._active_actions[1] = {**_jog(30.0, sent_ago=3.0), 'request_id': 'act-2', 'label': 'AC Servo'}
    supervisor._clear_completed_actions()
    assert 1 not in supervisor._active_actions
    request_id, success, message = results[-1]
    assert request_id == 'act-2' and success is True
    assert 'trajectory completed' in message and '출렁입니다' in message
