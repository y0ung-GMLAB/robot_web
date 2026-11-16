"""정지 표지 · 재생 세션 · 시간 창 없이 · 수정 목록 200 · 203

- 200 · 감독은 정지 뒤 0.5 s 동안 모든 명령을 막았다(`_motion_stop_block_until`) · 그 0.5 s 가 지키던 것은
  **정지 전에 돌던 재생이 늦게 보내는 프레임**이다 · 재생 틱이 0.5 s 넘게 늦으면(GIL · 실측 419 ms 까지)
  차단이 풀린 뒤의 프레임이 정지한 축을 다시 움직였다 · 정지 직후의 주차 · 초기 이동은 반대로 거절됐다.
- 203 · 재생 소유는 프레임마다 0.15 s 임대였다 · 틱이 늦으면 「재생 중」 이 꺼졌다 켜졌고 그 틈에
  수동 조그가 재생 축을 잡았다.

이제 감독은 정지마다 표지를 올리고, 재생 노드가 그 표지로 연 세션의 프레임만 받는다 · 소유는 세션 동안
쥐고 세션이 닫힐 때 · 프레임에서 빠질 때 놓는다 · 시계는 고장 감지(죽은 재생 노드)에만 쓴다.

rclpy 노드 없이 돈다.
"""

import json
import math
import threading
import time

from motion_control_msgs.msg import MotorStatus
from std_msgs.msg import Int8MultiArray, String

from motion_supervisor import supervisor_node
from motion_supervisor.command_arbiter import CommandArbiter, CommandOwner
from motion_supervisor.supervisor_node import (
    MANUAL_BLOCKED_BY_STOP,
    PLAYBACK_SESSION_CLOSED_MESSAGE,
    MotionSupervisor,
)

R = math.radians


class Capture:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)

    def payloads(self):
        return [json.loads(message.data) for message in self.messages]


class Quiet:
    def __getattr__(self, _name):
        return lambda *_a, **_k: None


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _supervisor(axes=(0, 1), clock=None):
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._active_jogs = {}
    supervisor._active_actions = {}
    supervisor._last_motion_run_command_at = 0.0
    supervisor._emergency_latched = False
    supervisor._command_lock = threading.RLock()
    supervisor._command_arbiter = CommandArbiter(clock=clock) if clock else CommandArbiter()
    supervisor._project_generation = 1
    supervisor._command_pub = Capture()
    supervisor._safety_status_pub = Capture()
    supervisor._latest_state = {'motors': [], 'minas_absolute': {'state': 'ok'}}
    supervisor.action_period_sec = 0.02
    supervisor.get_logger = lambda: Quiet()
    supervisor._stop_boot = 'boot-a'
    supervisor._stop_epoch = 0
    supervisor._stop_settled = True
    supervisor._stop_started_at = 0.0
    supervisor._runtime_status_at = 0.0
    supervisor._runtime_session = {}
    supervisor._playback_session_accepted = False
    supervisor._current_motors = lambda: [
        {
            'controller_index': axis, 'state': 'detected', 'motor_type': 'ac_servo',
            'position_deg': 0.0, 'servo_on': True, 'fault': False,
        }
        for axis in axes
    ]
    return supervisor


def _frame(axes, driven=None, *, position=True):
    driven = set(axes if driven is None else driven)
    command = MotorStatus()
    command.controller_index = list(axes)
    command.number_of_target_interfaces = [
        (2 if position else 1) if axis in driven else 0 for axis in axes
    ]
    command.target_interface_id = [
        Int8MultiArray(data=[0, 1] if position else [0]) for _ in axes
    ]
    command.controlword = [0x3F] * len(axes)
    command.statusword = [0] * len(axes)
    command.errorcode = [0] * len(axes)
    command.position = [0.1] * len(axes)
    command.velocity = [0.0] * len(axes)
    command.effort = [0.0] * len(axes)
    return command


def _runtime_says(supervisor, *, active, epoch, seen=None, streaming=True, boot='boot-a'):
    """재생 노드 상태 한 장 · `/motion_run/status` 의 `playback_session`"""
    seen = epoch if seen is None else seen
    supervisor._motion_run_status_callback(String(data=json.dumps({
        'state': 'running' if active else 'stopped',
        'playback_session': {
            'active': active, 'streaming': streaming,
            'stop_boot': boot, 'stop_epoch': epoch,
            'seen_stop_boot': boot, 'seen_stop_epoch': seen,
        },
    })))


def _last_safety(supervisor):
    return supervisor._safety_status_pub.payloads()[-1]


# --------------------------------------------------------------------------- #
# 200 · 정지 뒤 늦은 프레임 · 정지 직후의 새 실행 · 「정지 정리 끝」
# --------------------------------------------------------------------------- #

def test_a_late_frame_of_the_stopped_run_is_dropped_no_matter_how_late():
    """정지 전 재생의 프레임 · 0.5 s 가 지나도(전에는 여기서 다시 받았다) 버린다"""
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._motion_run_command_callback(_frame([0, 1]))
    assert len(supervisor._command_pub.messages) == 1

    supervisor._handle_safety_stop(False)
    sent = len(supervisor._command_pub.messages)          # 정지가 낸 「현재 위치에 서라」 까지
    # 전에는 `_motion_stop_block_until` 이 0.5 s 뒤 풀렸다 · 그 시각을 지나 보낸다(시계를 쓰지 않으니 어떤 늦음도 같다)
    supervisor._stop_started_at -= 10.0
    supervisor._runtime_status_at = time.monotonic()       # 재생 노드는 살아 있다(정리 확인 전)
    supervisor._motion_run_command_callback(_frame([0, 1]))

    assert len(supervisor._command_pub.messages) == sent, '정지 전 재생의 늦은 프레임이 모터로 갔다'
    assert supervisor._motion_run_drop_reason == PLAYBACK_SESSION_CLOSED_MESSAGE
    assert supervisor._command_arbiter.axis_owners() == {}, '늦은 프레임이 축을 다시 쥐면 안 된다'


def test_a_run_opened_with_the_new_marker_plays_right_after_the_stop():
    """정지 직후의 주차 · 초기 이동 · 새 표지로 연 세션은 기다림 없이 받는다(191 ⑤ · 전에는 「정지 처리 중」 거절)"""
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._handle_safety_stop(False)
    assert _last_safety(supervisor)['stop_epoch'] == 1

    _runtime_says(supervisor, active=True, epoch=1)        # 재생 노드 · 새 표지로 실행을 잡았다
    before = len(supervisor._command_pub.messages)
    supervisor._motion_run_command_callback(_frame([0, 1]))

    assert len(supervisor._command_pub.messages) == before + 1
    safety = _last_safety(supervisor)
    assert safety['stop_settled'] is True and safety['motion_stop_settling'] is False
    assert safety['commands_blocked'] is False


def test_the_stop_settles_when_the_runtime_confirms_not_when_time_passes():
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._handle_safety_stop(False)

    safety = _last_safety(supervisor)
    assert safety['stop_settled'] is False and safety['motion_stop_settling'] is True
    assert safety['message'] == '전체 동작 정지 처리 중'
    # 「정리 중」 은 이제 명령을 막지 않는다 · 수동 조작 · 새 실행이 기다리지 않는다
    assert safety['commands_blocked'] is False

    # 재생 노드는 살아 있고 아직 옛 표지만 봤다 · 시간이 지나도(0.5 s · 1 s) 끝나지 않는다
    supervisor._stop_started_at -= 1.0
    _runtime_says(supervisor, active=True, epoch=0, seen=0)
    supervisor._publish_safety_status()
    assert _last_safety(supervisor)['stop_settled'] is False

    # 새 표지를 봤고 옛 세션을 닫았다 → 정리 끝 · 바로 알린다(0.5 s 주기를 기다리지 않음)
    published = len(supervisor._safety_status_pub.messages)
    _runtime_says(supervisor, active=False, epoch=0, seen=1)
    assert len(supervisor._safety_status_pub.messages) == published + 1
    assert _last_safety(supervisor)['stop_settled'] is True


def test_a_dead_runtime_settles_the_stop_by_the_failure_detector_only():
    """재생 노드 상태가 `RUNTIME_SILENT_SEC` 넘게 없다 · 죽은 노드는 프레임을 못 보낸다 · 고장 감지로 끝"""
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._handle_safety_stop(False)
    assert supervisor._stop_settled_now() is False

    silent = supervisor_node.RUNTIME_SILENT_SEC + 0.1
    supervisor._runtime_status_at -= silent
    supervisor._stop_started_at -= silent

    assert supervisor._stop_settled_now() is True


def test_emergency_stop_still_blocks_everything():
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._handle_safety_stop(True)
    _runtime_says(supervisor, active=True, epoch=1)        # 새 표지 세션이어도
    before = len(supervisor._command_pub.messages)

    supervisor._motion_run_command_callback(_frame([0, 1]))

    assert len(supervisor._command_pub.messages) == before
    safety = _last_safety(supervisor)
    assert safety['emergency_latched'] is True and safety['commands_blocked'] is True


def test_a_stream_request_that_raced_the_stop_is_dropped_and_a_later_one_goes_at_once():
    """정지와 겹쳐 들어온 페이더 요청은 버린다 · 정지 **뒤에** 들어온 요청은 0.5 s 기다리지 않고 간다"""
    supervisor = _supervisor(axes=(1,))
    supervisor._current_motors = lambda: [{
        'controller_index': 1, 'state': 'detected', 'motor_type': 'dynamixel',
        'fault': False, 'lower': -180.0, 'upper': 180.0,
    }]
    target = [{'request_id': 'f', 'channel': 1, 'axis': 1, 'target_rad': R(10.0)}]

    supervisor._mark_request_entry()                       # 요청이 들어왔다 · 처리 도중
    supervisor._handle_safety_stop(False)                  # 다른 콜백 묶음의 정지
    success, message, _ = supervisor._handle_manual_stream_batch(target)
    supervisor._clear_request_entry()
    assert success is False and message == MANUAL_BLOCKED_BY_STOP

    supervisor._mark_request_entry()                       # 정지 뒤 새 요청
    success, _, _ = supervisor._handle_manual_stream_batch(target)
    supervisor._clear_request_entry()
    assert success is True, '정지 뒤 새 조작이 「정지 처리 중」 으로 막혔다'


def test_a_jog_trajectory_that_raced_the_stop_sends_nothing_and_clears_itself():
    """정지가 표를 비운 **뒤에** 들어간 조그(정지와 겹친 요청) · 첫 점도 안 보내고 표에서 빠진다"""
    supervisor = _supervisor(axes=(0,))
    supervisor._action_setpoint_clear_sec = lambda: 0.0
    supervisor._mark_request_entry()
    entry_epoch = supervisor._entry_stop_epoch()
    supervisor._handle_safety_stop(False)
    sent = len(supervisor._command_pub.messages)
    supervisor._active_jogs[0] = {
        'stop_epoch': entry_epoch, 'steps': 3.0, 'start_position': 0.0, 'target_position': 0.01,
        'command_period_sec': 0.02, 'motors': supervisor._current_motors(),
        'motor': supervisor._current_motors()[0],
    }
    supervisor._jog_threads = {}
    supervisor._clear_request_entry()

    supervisor._run_ac_servo_jog_trajectory(0)

    assert len(supervisor._command_pub.messages) == sent, '정지 뒤에 조그가 나갔다'
    assert 0 not in supervisor._active_jogs, '끝나지 않은 조그로 남아 다음 조작을 막는다'


# --------------------------------------------------------------------------- #
# 203 · 재생 소유는 세션으로 · 임대 0.15 s 없음
# --------------------------------------------------------------------------- #

def test_playback_keeps_its_axes_through_a_late_tick():
    """재생 틱이 150 ms 넘게 늦어도(실측 419 ms) 재생 축을 수동이 가져가지 못한다 · 「재생 중」 도 그대로"""
    clock = FakeClock()
    supervisor = _supervisor(clock=clock)
    _runtime_says(supervisor, active=True, epoch=0, streaming=True)
    supervisor._motion_run_command_callback(_frame([0, 1]))

    clock.now += 0.5                                       # 다음 틱이 0.5 s 늦다
    acquired, owner = supervisor._command_arbiter.acquire(CommandOwner.MANUAL, axes=[0])

    assert acquired is False and owner is CommandOwner.PLAYBACK
    assert supervisor._playback_streaming() is True


def test_closing_the_session_releases_the_axes_at_once():
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._motion_run_command_callback(_frame([0, 1]))
    assert supervisor._command_arbiter.axis_owners() == {'0': 'playback', '1': 'playback'}

    _runtime_says(supervisor, active=False, epoch=0)       # 실행 끝 · 정지 · 오류

    assert supervisor._command_arbiter.axis_owners() == {}
    assert supervisor._playback_streaming() is False


def test_an_axis_the_frame_no_longer_drives_goes_to_midi_at_once():
    """오버더빙 · 재생 구간이 끝난 축은 그 프레임에서 놓는다 · MIDI 가 0.15 s 기다리지 않는다 · §6-72"""
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._motion_run_command_callback(_frame([0, 1]))
    supervisor._motion_run_command_callback(_frame([0, 1], driven={0}))

    assert supervisor._command_arbiter.axis_owners() == {'0': 'playback'}
    acquired, _ = supervisor._command_arbiter.acquire(CommandOwner.STREAM, axes=[1], lease_sec=1.0)
    assert acquired is True


def test_a_control_word_only_frame_does_not_release_axes():
    """서보 켜기 준비(제어어만)는 위치를 안 준다 · 그 프레임으로 다른 축을 놓지 않는다"""
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._motion_run_command_callback(_frame([0, 1]))
    supervisor._motion_run_command_callback(_frame([0, 1], driven={0}, position=False))

    assert supervisor._command_arbiter.axis_owners() == {'0': 'playback', '1': 'playback'}


def test_a_dead_player_session_is_closed_by_the_liveness_detector():
    """세션이 열린 채 재생 노드가 죽었다(닫는 알림이 없다) · 프레임도 상태도 끊기면 고장 감지로 닫는다"""
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._motion_run_command_callback(_frame([0, 1]))

    supervisor._safety_status_tick()
    assert supervisor._command_arbiter.axis_owners() != {}, '살아 있는 동안은 닫지 않는다'

    silent = supervisor_node.PLAYBACK_LIVENESS_SEC + 0.1
    supervisor._runtime_status_at -= silent
    supervisor._last_motion_run_received_at -= silent
    supervisor._safety_status_tick()

    assert supervisor._command_arbiter.axis_owners() == {}
    assert _last_safety(supervisor)['playback_session']['accepted'] is False


def test_a_session_opened_before_the_stop_is_not_accepted_again():
    """정지 뒤에도 재생 노드가 옛 표지의 세션을 「열림」 으로 알리면(아직 못 봄) 받지 않는다"""
    supervisor = _supervisor()
    _runtime_says(supervisor, active=True, epoch=0)
    supervisor._handle_safety_stop(False)

    _runtime_says(supervisor, active=True, epoch=0, seen=0)

    assert supervisor._playback_session_accepted is False
    assert _last_safety(supervisor)['stop_settled'] is False
