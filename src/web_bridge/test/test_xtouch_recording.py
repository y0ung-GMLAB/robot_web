"""X-Touch 조종·녹화 · 수정 목록 156 (사용자 결정 2026-10-17 · 2026-10-18)

    상한     X-Touch 출처는 조인트 매핑 최대 속도·가속도 × |이득| · 비면 거절
    녹화     램프가 보낸 값(주기 번호로 이음) → 조인트 rad · 20 ms · 재생 검사 통과
    저장     JSON Lines(Blender 내보내기와 같은 모양) · 같은 이름이면 _2 · _3
    끊김     수신이 멈추면 끊긴 것으로 · 마지막으로 받은 순간까지 자동 저장 · 만진 축은 세움
"""

import asyncio
import json
import math
import sys
import types
from types import SimpleNamespace

import pytest

# Windows 시험 환경에는 ROS 메시지가 없다 · 모양만 같은 대역을 세운다 · 있으면 진짜(다른 시험이 같이 돈다)
try:
    import std_msgs.msg  # noqa: F401
except ImportError:
    std_msgs = types.ModuleType('std_msgs')
    msg_module = types.ModuleType('std_msgs.msg')

    class _String:
        def __init__(self, data=''):
            self.data = data

    msg_module.String = _String
    std_msgs.msg = msg_module
    sys.modules.setdefault('std_msgs', std_msgs)
    sys.modules['std_msgs.msg'] = msg_module

from motion_common import manual_speed, motion_table  # noqa: E402
from motion_supervisor import manual_ramp  # noqa: E402
from motion_web_bridge import manual_range_gate, xtouch_recording  # noqa: E402
from motion_web_bridge.manual_stream import ManualStreamService  # noqa: E402
from motion_web_bridge.xtouch_recording import PERIOD_SEC, RecordingService, Take, TakeAxis  # noqa: E402

R = math.radians


def _row(motion_id='neck_yaw', axis=1, gear=100.0, velocity=9.0, acceleration=14.0, **extra):
    row = {
        'motion_id': motion_id, 'enabled': True, 'motor_axis': axis, 'motor_ref': '',
        'gear_ratio': gear, 'scale': 1.0, 'invert': False, 'reference_position_rad': R(30.0),
        'motion_lower_rad': R(-15.0), 'motion_upper_rad': R(15.0), 'range_confirmed': True,
    }
    if velocity is not None:
        row['max_velocity_rad_s'] = R(velocity)
    if acceleration is not None:
        row['max_acceleration_rad_s2'] = R(acceleration)
    row.update(extra)
    return row


def _motor(axis, position_rad=0.0):
    return {'controller_index': axis, 'position_rad': position_rad}


# ------------------------------------------------------------------ 상한 ---


def test_xtouch_limits_are_the_mapping_rates_times_the_gain():
    limits, reason = manual_range_gate.xtouch_limits([_row()], [_motor(1)], 1)
    assert reason == ''
    assert limits[manual_speed.VELOCITY_FIELD] == pytest.approx(R(9.0) * 100.0)
    assert limits[manual_speed.ACCELERATION_FIELD] == pytest.approx(R(14.0) * 100.0)


def test_xtouch_limits_refuse_an_axis_without_rates_or_without_a_row():
    _, reason = manual_range_gate.xtouch_limits([_row(acceleration=None)], [_motor(1)], 1)
    assert '속도·가속도 상한을 먼저 채우세요' in reason
    _, reason = manual_range_gate.xtouch_limits([_row()], [_motor(1)], 3)
    assert '「사용」 줄에 없습니다' in reason


class _Publisher:
    def __init__(self):
        self.sent = []

    def publish(self, msg):
        self.sent.append(json.loads(msg.data))


def test_stream_target_from_xtouch_carries_the_mapping_limits_not_the_slow_ones():
    publisher = _Publisher()
    bridge = SimpleNamespace(
        current_project_generation=lambda: 1,
        manual_speed_limits=lambda axis: manual_speed.motor_limits(100.0),
        xtouch_speed_limits=lambda axis: ({manual_speed.VELOCITY_FIELD: 15.7, manual_speed.ACCELERATION_FIELD: 24.4}, ''),
    )
    service = ManualStreamService(bridge, publisher=publisher)
    assert service.send_target(1, 0.5, source='xtouch')['success'] is True
    assert service.send_target(1, 0.5, source='fader')['success'] is True
    xtouch, fader = publisher.sent
    assert xtouch['source'] == 'xtouch' and xtouch[manual_speed.VELOCITY_FIELD] == 15.7
    assert fader[manual_speed.VELOCITY_FIELD] == pytest.approx(manual_speed.motor_limits(100.0)[manual_speed.VELOCITY_FIELD])


def test_stream_target_from_xtouch_is_refused_when_the_rates_are_empty():
    publisher = _Publisher()
    bridge = SimpleNamespace(
        current_project_generation=lambda: 1,
        xtouch_speed_limits=lambda axis: ({}, '속도·가속도 상한을 먼저 채우세요'),
    )
    service = ManualStreamService(bridge, publisher=publisher)
    result = service.send_target(1, 0.5, source='xtouch')
    assert result['success'] is False and '상한' in result['message']
    assert publisher.sent == []


# ------------------------------------------------------------------ 녹화 ---


def _take(t0=100.0, start=0.0):
    take = Take(t0=t0)
    take.add_axis(TakeAxis(axis=1, rows=[_row()], start_motor=start))
    return take


def test_take_chains_frames_by_seq_and_anchors_a_new_burst_by_wall_time():
    take = _take()
    # 첫 묶음 · 받은 시각이 흔들려도 seq 가 이어지면 다음 프레임
    take.add_samples(10, 100.041, [(1, 1.0)])          # 프레임 2
    take.add_samples(11, 100.049, [(1, 2.0)])          # 프레임 3 (시각으론 2)
    take.add_samples(12, 100.101, [(1, 3.0)])          # 프레임 4
    # 쉬었다가 다시 · 시각으로 자리
    take.add_samples(40, 100.200, [(1, 4.0)])          # 프레임 10
    values = take.series(100.24)[1]
    assert len(values) == 13
    assert values[:2] == [0.0, 0.0]                    # 첫 값 전 = 시작 위치
    assert values[2:5] == [1.0, 2.0, 3.0]
    assert values[5:10] == [3.0] * 5                    # 서 있는 동안 그대로
    assert values[10:] == [4.0] * 3


def test_values_during_the_countdown_only_set_the_first_frame():
    take = _take(t0=100.0, start=0.0)
    take.add_samples(1, 98.0, [(1, 5.0)])
    take.add_samples(2, 98.02, [(1, 6.0)])
    assert take.series(100.04)[1] == [6.0, 6.0, 6.0]


def test_samples_for_axes_not_recorded_are_ignored():
    take = _take()
    take.add_samples(1, 100.02, [(0, 9.0), (1, 1.0)])
    assert set(take.series(100.04)) == {1}


def _ramp_take(goals, vmax_joint=9.0, amax_joint=14.0, gear=100.0):
    """램프가 실제로 보내는 값 · 가는 중 목표가 바뀌고 놓았다 다시 잡음"""
    row = _row(gear=gear, velocity=vmax_joint, acceleration=amax_joint)
    vmax, amax = R(vmax_joint) * gear, R(amax_joint) * gear
    start = R(30.0)
    take = Take(t0=0.0)
    take.add_axis(TakeAxis(axis=1, rows=[row], start_motor=start))
    position, velocity, seq, wall = start, 0.0, 0, 0.0
    for goal_joint, ticks in goals:
        goal = R(30.0) + R(goal_joint) * gear
        done = False
        for tick in range(ticks):
            seq += 1
            # 받은 시각은 흔들린다 · 주기 번호가 이어지는 동안은 상관없어야 한다
            wall += PERIOD_SEC + (0.006 if tick % 7 == 3 else -0.003 if tick % 7 == 5 else 0.0)
            position, velocity, done = manual_ramp.step(position, velocity, goal, vmax, amax, PERIOD_SEC)
            take.add_samples(seq, wall, [(1, position)])
            if done:
                break
        if done:
            # 도착해서 램프가 끝남 · 쉬는 동안 번호가 끊긴다(다른 축만 돌았다) · 다음은 시각으로 자리
            seq += 5
            wall += 0.3
            velocity = 0.0     # 새 램프는 선 채로 시작
        # 안 끝났으면 같은 램프가 새 목표로 이어 간다(같은 조작이 끌기를 계속)
    return take, wall


def test_a_recorded_ramp_passes_the_same_rate_check_as_playback():
    take, end = _ramp_take([(10.0, 40), (-12.0, 25), (5.0, 400), (14.0, 3), (-3.0, 400)])
    joints = take.joint_series(end)
    assert joints[0][0] == 'neck_yaw'
    assert max(abs(v) for v in joints[0][2]) > R(4.0)     # 실제로 움직였다
    assert xtouch_recording.rate_problem(joints) == ''


def test_the_rate_check_refuses_a_jump():
    row = _row()
    joints = [('neck_yaw', row, [0.0, 0.0, R(5.0), R(5.0)])]
    assert '속도' in xtouch_recording.rate_problem(joints)


def test_animation_text_is_the_blender_export_shape_and_plays():
    take, end = _ramp_take([(5.0, 200)])
    joints = take.joint_series(end)
    text = xtouch_recording.animation_text('take1', joints)
    lines = text.splitlines()
    header = json.loads(lines[0])
    assert header['type'] == 'motion_header' and header['rotation_unit'] == 'rad'
    assert header['fields'] == ['frame', 'time_sec', 'id', 'value']
    first = json.loads(lines[1])
    assert first[:3] == [1, 0.02, 'neck_yaw']
    assert len(lines) - 1 == len(joints[0][2])
    motion_table.validate_motion_content(text)      # 저장소·재생 파서가 읽는다


def test_save_unique_numbers_the_name_and_keeps_the_old_file():
    taken = {'take.json', 'take_2.json'}
    written = []

    def write(name):
        if name in taken:
            raise ValueError(f'같은 이름의 파일이 이미 있습니다: {name}')
        written.append(name)

    assert xtouch_recording.save_unique(write, 'take') == 'take_3.json'
    assert written == ['take_3.json']


def test_clean_name_strips_unsafe_text_and_defaults_to_a_timestamp():
    assert xtouch_recording.clean_name('목 좌우/1.json') == '목_좌우_1'
    assert xtouch_recording.clean_name('').startswith('xtouch_')


# ------------------------------------------------------------ 녹화 상태 ---


class _Repository:
    def __init__(self, existing=()):
        self.files = {name: '' for name in existing}

    def require_selected_project_id(self):
        return 'p'

    def import_text(self, project_id, category, name, text):
        assert category == 'motions'
        if name in self.files:
            raise ValueError(f'같은 이름의 파일이 이미 있습니다: {name}')
        self.files[name] = text


class _Gate:
    def __init__(self, rows, motors):
        self.rows, self.motor_list = rows, motors

    def saved_rows(self):
        return self.rows

    def motors(self):
        return self.motor_list


class _Log:
    def __init__(self):
        self.events = []

    def append(self, **event):
        self.events.append(event)


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def _bridge(rows=None, existing=(), block=''):
    gate = _Gate(rows if rows is not None else [_row()], [_motor(1, R(30.0))])
    return SimpleNamespace(
        manual_range_blocker=lambda: block,
        gate=gate,
        project_repository=_Repository(existing),
        _motor_event_log=_Log(),
    )


def _service(bridge, clock):
    log = bridge._motor_event_log
    return RecordingService(
        bridge,
        mapping=lambda: (bridge.gate.saved_rows(), bridge.gate.motors()),
        record_event=lambda event_type, content, details: log.append(
            category='system', event_type=event_type, target='X-Touch 녹화', content=content, details=details,
        ),
        clock=clock,
    )


def _samples_msg(seq, wall, axis, value):
    return SimpleNamespace(data=json.dumps({'seq': seq, 't': wall, 'samples': [[axis, value]]}))


def test_recording_counts_down_records_and_saves_with_a_numbered_name():
    clock = _Clock()
    bridge = _bridge(existing=('take.json',))
    service = _service(bridge, clock)
    owner = object()
    started = service.start(owner, [1], 'take')
    assert started['success'] and started['state'] == 'countdown'
    assert started['starts_in_sec'] == pytest.approx(3.0)
    for k in range(1, 51):                                # 1 s · 3 s 카운트다운 뒤
        service.samples_callback(_samples_msg(k, 1003.0 + k * PERIOD_SEC, 1, R(30.0) + k * 1e-3))
    clock.now = 1004.0
    result = service.stop(owner)
    assert result['success'] and result['file'] == 'take_2.json'
    assert result['frames'] == 51
    assert bridge.project_repository.files['take.json'] == ''      # 기존 파일 그대로
    assert any(event['event_type'] == 'xtouch_record_saved' for event in bridge._motor_event_log.events)


def test_recording_refuses_an_axis_without_rate_limits():
    service = _service(_bridge(rows=[_row(velocity=None)]), _Clock())
    result = service.start(object(), [1], 'take')
    assert result['success'] is False and '속도·가속도 상한을 먼저 채우세요' in result['message']


def test_recording_is_refused_outside_manual_mode_and_while_another_runs():
    service = _service(_bridge(block='수동 조작 불가 · 스케줄 모드'), _Clock())
    assert service.start(object(), [1], 'take')['success'] is False
    service = _service(_bridge(), _Clock())
    assert service.start(object(), [1], 'a')['success'] is True
    assert '이미 녹화 중' in service.start(object(), [1], 'b')['message']


def test_stopping_during_the_countdown_saves_nothing():
    clock = _Clock()
    bridge = _bridge()
    service = _service(bridge, clock)
    owner = object()
    service.start(owner, [1], 'take')
    clock.now += 1.0
    result = service.stop(owner)
    assert result['success'] is False and '카운트다운' in result['message']
    assert bridge.project_repository.files == {}


# ------------------------------------------------------------- 소켓 끊김 ---


class _Socket:
    """보낼 글을 차례로 주고 · 다 주면 아무것도 안 온다(무선이 멈춘 것처럼)"""

    def __init__(self, messages):
        self.incoming = [json.dumps(item) for item in messages]
        self.sent = []
        self.closed = False

    async def accept(self):
        pass

    async def receive_text(self):
        if self.incoming:
            return self.incoming.pop(0)
        await asyncio.sleep(3600)

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self):
        self.closed = True


def test_a_silent_socket_is_treated_as_disconnected_and_the_take_is_saved(monkeypatch):
    from motion_web_bridge import manual_stream_socket

    monkeypatch.setattr(manual_stream_socket, 'WATCHDOG_MIN_SEC', 0.05)
    clock = _Clock(now=0.0)
    bridge = _bridge()
    held = []
    bridge.manual_stream = SimpleNamespace(
        send_target=lambda axis, target, **kw: {'success': True, 'axis': axis},
        pop_result=lambda axis: None,
        hold=lambda axes: held.append(list(axes)) or {'success': True, 'axes': axes},
        release=lambda axes: {'success': True},
    )
    bridge.manual_range_axis_blocker = lambda axis: ''
    bridge.xtouch_recording = _service(bridge, clock)
    # 소켓 블록 판정은 실제 시간 · 녹화는 가짜 시계(카운트다운이 이미 끝난 것으로)
    monkeypatch.setattr(manual_stream_socket, '_stream_block_reason', lambda b: '')
    monkeypatch.setattr(manual_stream_socket.time, 'time', lambda: 10.0)

    original_start = bridge.xtouch_recording.start

    def start_then_skip_countdown(owner, axes, name='', base=''):
        result = original_start(owner, axes, name, base)
        clock.now = 5.0          # t0 = 3.0 · 마지막으로 받은 시각(10.0)까지 저장
        return result

    bridge.xtouch_recording.start = start_then_skip_countdown
    socket = _Socket([
        {'type': 'hello', 'watchdog_sec': 0.05},
        {'type': 'record_start', 'axes': [1], 'name': 'live'},
        {'type': 'target', 'axis': 1, 'target_rad': R(30.5), 'source': 'xtouch'},
    ])
    asyncio.run(manual_stream_socket.run_manual_stream_socket(bridge, socket))
    assert socket.closed is True
    assert held == [[1]]                                     # 만진 축은 그 자리에
    assert 'live.json' in bridge.project_repository.files    # 끊긴 순간까지 저장
    lines = bridge.project_repository.files['live.json'].splitlines()
    assert len(lines) - 1 == 351                             # 3.0 → 10.0 s · 20 ms
    saved = [event for event in bridge._motor_event_log.events if event['event_type'] == 'xtouch_record_saved']
    assert saved and '끊김' in saved[0]['content']
