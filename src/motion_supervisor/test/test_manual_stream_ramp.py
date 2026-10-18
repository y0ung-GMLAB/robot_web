"""수동 스트림 램프 · 수정 목록 126 (사용자 결정 2026-10-13)

페이더를 잘못 찍어도 · 다이얼 한 칸을 10° 로 해도 · 조인트 2 °/s · 4 °/s² 로 천천히 ·
놓아도 마지막 목표까지 · 같은 조작은 새 목표로 · 다른 조작은 이동 중 거절 · 정지·세우기는 바로.
"""

import math
import threading

import pytest

from motion_common import manual_speed
from motion_supervisor import manual_ramp
from motion_supervisor.supervisor_node import MotionSupervisor

R = math.radians
D = math.degrees
DT = 0.02


class CapturePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class QuietLogger:
    def info(self, *_a, **_k):
        pass

    def warning(self, *_a, **_k):
        pass

    def error(self, *_a, **_k):
        pass


def _supervisor(axes=(0,), position_deg=0.0):
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._last_motion_run_command_at = 0.0
    supervisor._active_jogs = {}
    supervisor._active_actions = {}
    supervisor._emergency_latched = False
    supervisor._motion_stop_block_until = 0.0
    supervisor._command_lock = threading.RLock()
    supervisor._command_pub = CapturePublisher()
    supervisor._manual_stream_result_pub = CapturePublisher()
    supervisor._ensure_ramp_thread = lambda: None        # 시험은 주기를 손으로 돌린다
    supervisor.get_logger = lambda: QuietLogger()
    supervisor.motors = {
        axis: {
            'controller_index': axis,
            'state': 'detected',
            'fault': False,
            'motor_type': 'dynamixel',
            'lower': -3600.0,
            'upper': 3600.0,
            'position_rad': R(position_deg),
        }
        for axis in axes
    }
    supervisor._current_motors = lambda: list(supervisor.motors.values())
    return supervisor


def _target(axis, motor_deg, *, gain=None, source='fader', **extra):
    target = {'request_id': f'stream-1-{axis}', 'axis': axis, 'target_rad': R(motor_deg), 'source': source, **extra}
    if gain is not None:
        target.update(manual_speed.motor_limits(gain))
    return target


def _sent(supervisor):
    """발행된 명령마다 · 축 → 모터 deg"""
    rows = []
    for command in supervisor._command_pub.messages:
        rows.append({
            int(axis): D(float(command.position[slot]))
            for slot, axis in enumerate(command.controller_index)
            if int(command.number_of_target_interfaces[slot]) > 0
        })
    return rows


def _run(supervisor, ticks):
    for _ in range(ticks):
        supervisor._stream_ramp_tick(DT)


# ---------------------------------------------------------------- 계산 ---


def test_step_respects_speed_and_acceleration_and_lands_on_the_goal():
    position, velocity, vmax, amax = 0.0, 0.0, 1.0, 2.0
    speeds, accels = [], []
    for _ in range(2000):
        new_position, new_velocity, done = manual_ramp.step(position, velocity, 10.0, vmax, amax, DT)
        accels.append(abs(new_velocity - velocity) / DT)
        speeds.append(abs(new_velocity))
        assert new_position <= 10.0 + 1e-12          # 지나치지 않는다
        position, velocity = new_position, new_velocity
        if done:
            break
    assert done and position == 10.0 and abs(velocity) <= amax * DT + 1e-12
    assert max(speeds) <= vmax + 1e-12
    assert max(accels) <= amax + 1e-9                 # 멈추는 마지막 주기도 (수정 목록 156)


def test_step_turns_around_through_the_acceleration_limit():
    """가는 중 반대쪽 목표 · 줄였다가 돌아선다 · 속도가 한 번에 뒤집히지 않는다"""
    position, velocity = 0.0, 1.0
    previous = velocity
    for _ in range(2000):
        position, velocity, done = manual_ramp.step(position, velocity, -3.0, 1.0, 2.0, DT)
        assert abs(velocity - previous) <= 2.0 * DT * 2.0 + 1e-9
        previous = velocity
        if done:
            break
    assert done and position == -3.0


def test_step_differences_stay_inside_the_limits_with_a_moving_goal():
    """보낸 목표의 차분(재생 검사와 같은 잣대) · 목표가 끌리며 갑자기 가까워져도 상한 안 · 수정 목록 156

    전에는 빠르게 가는 중 목표가 바로 앞으로 오면 그 자리에 섰다(차분 가속이 상한의 수백 배)
    """
    import random
    rng = random.Random(7)
    for _ in range(300):
        vmax, amax = rng.uniform(0.05, 3.0), rng.uniform(0.05, 10.0)
        position, velocity, goal = rng.uniform(-1, 1), 0.0, rng.uniform(-1, 1)
        path = [position]
        done = False
        for tick in range(100000):
            if tick < 300 and rng.random() < 0.2:
                goal += rng.uniform(-0.05, 0.05)
            position, velocity, done = manual_ramp.step(position, velocity, goal, vmax, amax, DT)
            path.append(position)
            if done and tick >= 300:
                break
        assert done and position == goal
        speeds = [0.0] + [(b - a) / DT for a, b in zip(path, path[1:])] + [0.0]
        assert max(abs(v) for v in speeds) <= vmax * (1 + 1e-6)
        assert max(abs(b - a) / DT for a, b in zip(speeds, speeds[1:])) <= amax * (1 + 1e-6)


# ---------------------------------------------------------- supervisor ---


def test_a_far_click_goes_there_slowly_at_two_joint_degrees_per_second():
    """페이더 트랙 끝을 한 번 찍음 · 이득 150(목 상하) · 모터 300 °/s · 조인트 2 °/s"""
    supervisor = _supervisor()
    ok, _, results = supervisor._accept_stream_goals([_target(0, 150.0 * 10.0, gain=150.0)])
    assert ok and results[0]['success']
    assert supervisor._command_pub.messages == []       # 받기만 · 보내는 것은 주기

    _run(supervisor, 1)
    first = _sent(supervisor)[0][0]
    assert 0.0 < first <= 300.0 * DT + 1e-9               # 한 번에 가지 않는다

    _run(supervisor, 400)                                 # 8 s
    path = [0.0] + [row[0] for row in _sent(supervisor)]
    steps = [b - a for a, b in zip(path, path[1:])]
    assert max(steps) <= 300.0 * DT + 1e-6                # 모터 300 °/s = 조인트 2 °/s
    assert path[-1] == pytest.approx(1500.0)              # 끝까지 감 (10° 를 약 6 s)


def test_release_keeps_going_to_the_last_goal_then_ends():
    supervisor = _supervisor()
    supervisor._accept_stream_goals([_target(0, 100.0, gain=10.0)])
    _run(supervisor, 5)
    ok, message = supervisor._release_stream_ramps([0])
    assert ok and '목표까지' in message
    assert 0 in supervisor._stream_ramps                  # 놓아도 계속

    _run(supervisor, 2000)
    assert _sent(supervisor)[-1][0] == pytest.approx(100.0)
    assert supervisor._stream_ramps == {}                 # 도착 뒤 끝


def test_hold_stops_at_the_current_position_and_ends_the_ramp():
    """정지 · 소켓 끊김 · MIDI SELECT 놓기 · 그 자리"""
    supervisor = _supervisor()
    supervisor._accept_stream_goals([_target(0, 100.0, gain=10.0)])
    _run(supervisor, 5)
    supervisor.motors[0]['position_rad'] = R(1.5)

    ok, _, _ = supervisor._handle_stream_hold_axes([0], None)

    assert ok
    assert supervisor._stream_ramps == {}
    assert _sent(supervisor)[-1][0] == pytest.approx(1.5)
    count = len(supervisor._command_pub.messages)
    _run(supervisor, 10)
    assert len(supervisor._command_pub.messages) == count  # 더 안 간다


def test_safety_stop_ends_every_ramp():
    supervisor = _supervisor(axes=(0, 1))
    supervisor._servo_alarm_guard = None
    supervisor._publish_safety_status = lambda: None
    supervisor._publish_action_result = lambda *_a: None
    supervisor._accept_stream_goals([_target(0, 100.0), _target(1, -100.0)])
    assert set(supervisor._stream_ramps) == {0, 1}

    supervisor._handle_safety_stop(emergency=False)

    assert supervisor._stream_ramps == {}


def test_same_control_retargets_and_another_control_is_refused_while_moving():
    supervisor = _supervisor()
    supervisor._accept_stream_goals([_target(0, 100.0, gain=10.0, source='fader')])
    _run(supervisor, 5)

    ok, _, results = supervisor._accept_stream_goals([_target(0, -50.0, gain=10.0, source='fader')])
    assert ok and supervisor._stream_ramps[0].goal == pytest.approx(R(-50.0))

    ok, _, results = supervisor._accept_stream_goals([_target(0, 30.0, gain=10.0, source='dial')])
    assert not ok
    assert '이동 중(페이더)' in results[0]['message']
    assert supervisor._stream_ramps[0].goal == pytest.approx(R(-50.0))


def test_another_control_is_accepted_once_the_axis_has_arrived():
    supervisor = _supervisor()
    supervisor._accept_stream_goals([_target(0, 0.5, gain=10.0, source='fader')])
    _run(supervisor, 200)
    assert supervisor._stream_ramps[0].arrived

    ok, _, _ = supervisor._accept_stream_goals([_target(0, 10.0, gain=10.0, source='dial')])

    assert ok and supervisor._stream_ramps[0].source == 'dial'


def test_a_request_without_limits_uses_gain_one_the_slowest():
    """MIDI · 옛 길 · 브리지가 상한을 안 실으면 모터 2 °/s"""
    supervisor = _supervisor()
    supervisor._accept_stream_goals([{'request_id': 'midi-1', 'axis': 0, 'target_rad': R(100.0)}])
    ramp = supervisor._stream_ramps[0]
    assert D(ramp.max_velocity) == pytest.approx(manual_speed.JOINT_MAX_VELOCITY_DEG_S)
    assert ramp.source == manual_ramp.DEFAULT_SOURCE


def test_axes_with_different_gears_move_at_the_same_joint_speed():
    supervisor = _supervisor(axes=(0, 1))
    supervisor._accept_stream_goals([
        _target(0, 150.0 * 5.0, gain=150.0),
        _target(1, 35.0 * 5.0, gain=35.0),
    ])
    _run(supervisor, 100)                       # 2 s · 아직 가는 중
    last = _sent(supervisor)[-1]
    assert last[0] / 150.0 == pytest.approx(last[1] / 35.0, rel=1e-6)


def test_goal_outside_the_motor_limit_is_refused():
    supervisor = _supervisor()
    ok, _, results = supervisor._accept_stream_goals([_target(0, 5000.0)])
    assert not ok and '상한' in results[0]['message']
    assert supervisor._stream_ramps == {}


def test_a_failed_tick_ends_that_ramp_and_reports_it():
    """서보가 꺼지는 등 발행이 거절되면 그 축 램프는 끝 · 결과로 알린다"""
    supervisor = _supervisor()
    supervisor._accept_stream_goals([_target(0, 100.0)])
    supervisor.motors[0]['state'] = 'lost'

    _run(supervisor, 1)

    assert supervisor._stream_ramps == {}
    assert supervisor._manual_stream_result_pub.messages


def test_the_ramp_thread_runs_to_the_goal_and_exits():
    """실제 주기 실 · 도착하고 놓으면 실이 스스로 끝난다"""
    import time
    supervisor = _supervisor()
    del supervisor._ensure_ramp_thread
    supervisor.action_period_sec = 0.005
    supervisor._accept_stream_goals([_target(0, 0.2, gain=10.0)])
    supervisor._release_stream_ramps([0])
    deadline = time.monotonic() + 5.0
    while supervisor._ramp_thread is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert supervisor._ramp_thread is None
    assert _sent(supervisor)[-1][0] == pytest.approx(0.2)


# ------------------------------------------------------- X-Touch 녹화 값 ---


def test_xtouch_ramp_ticks_are_published_for_recording_with_a_running_seq():
    """X-Touch 램프 값만 · 주기마다 하나 · 번호가 이어진다 · 녹화가 이것으로 프레임을 잇는다 · 수정 목록 156"""
    import json as _json

    supervisor = _supervisor(axes=(0, 1))
    supervisor._manual_stream_samples_pub = CapturePublisher()
    supervisor._accept_stream_goals([
        _target(0, 50.0, gain=100.0, source='xtouch'),
        _target(1, 50.0, gain=100.0, source='fader'),
    ])
    _run(supervisor, 3)
    sent = [_json.loads(message.data) for message in supervisor._manual_stream_samples_pub.messages]
    assert [item['seq'] for item in sent] == [1, 2, 3]
    assert all([sample[0] for sample in item['samples']] == [0] for item in sent)   # 웹 페이더 축은 안 실음
    commanded = [row[0] for row in _sent(supervisor)]
    assert [D(item['samples'][0][1]) for item in sent] == pytest.approx(commanded)  # 모터로 보낸 값 그대로
