"""재생 라이브 오버라이드 · 조인트 뮤트 + 좁힌 리밋 · P7

재생 **중에** 이상한 조인트 이름을 바로 빼거나(뮤트 · 모터는 그 자리에 섬)
범위를 산 채로 좁힌다(클램프) · 계획(plan)과 매핑 파일은 건드리지 않아
되돌리면 즉시 원래대로 돈다 · 발행 직전에 읽으므로 다음 20ms 틱부터 듣는다.
"""

import sys
import types
from types import SimpleNamespace

# Windows 시험 환경에는 ROS 메시지가 없다 · 모양만 같은 대역
if 'std_msgs.msg' not in sys.modules:
    std_msgs = types.ModuleType('std_msgs')
    msg_module = types.ModuleType('std_msgs.msg')

    class _Message:
        def __init__(self, data=None):
            self.data = data

    msg_module.String = _Message
    msg_module.Int8MultiArray = _Message
    std_msgs.msg = msg_module
    sys.modules.setdefault('std_msgs', std_msgs)
    sys.modules['std_msgs.msg'] = msg_module

if 'motion_control_msgs.msg' not in sys.modules:
    motor_msgs = types.ModuleType('motion_control_msgs')
    motor_msg_module = types.ModuleType('motion_control_msgs.msg')

    class _MotorStatus:
        pass

    motor_msg_module.MotorStatus = _MotorStatus
    motor_msgs.msg = motor_msg_module
    sys.modules.setdefault('motion_control_msgs', motor_msgs)
    sys.modules['motion_control_msgs.msg'] = motor_msg_module

from motion_runtime.motion_player import MotionPlayer  # noqa: E402


def _player(overrides):
    manager = SimpleNamespace(live_override_snapshot=lambda: dict(overrides))
    return MotionPlayer(manager)


AXES = [
    {
        'motion_id': 'Neck_Yaw',
        'motor_axis': 1,
        'row': {'gear_ratio': 100.0, 'scale': 1.0, 'invert': False,
                'offset_deg': 0.0, 'reference_position_deg': 0.0},
    },
    {
        'motion_id': 'Eye_Pitch',
        'motor_axis': 2,
        'row': {'gear_ratio': 50.0, 'scale': 1.0, 'invert': False,
                'offset_deg': 0.0, 'reference_position_deg': 0.0},
    },
]


def test_mute_drops_that_joint_and_keeps_the_rest():
    player = _player({'Neck_Yaw': {'muted': True}})
    positions, values = player._apply_live_overrides(
        AXES, {1: 500.0, 2: 100.0}, {'Neck_Yaw': 5.0, 'Eye_Pitch': 2.0},
    )
    assert 1 not in positions, '뮤트한 조인트 이름은 명령에서 빠진다 · 모터는 그 자리에 선다'
    assert positions[2] == 100.0
    assert 'Neck_Yaw' not in values
    assert values['Eye_Pitch'] == 2.0


def test_clamp_cuts_the_joint_value_and_recomputes_only_that_motor():
    player = _player({'Neck_Yaw': {'clamp': [-3.0, 3.0]}})
    positions, values = player._apply_live_overrides(
        AXES, {1: 500.0, 2: 100.0}, {'Neck_Yaw': 5.0, 'Eye_Pitch': 2.0},
    )
    assert values['Neck_Yaw'] == 3.0
    assert positions[1] == 300.0            # 3° × 1:100 · 매핑 식으로 재계산
    assert positions[2] == 100.0            # 다른 축은 그대로
    assert values['Eye_Pitch'] == 2.0


def test_inside_the_clamp_nothing_changes():
    player = _player({'Neck_Yaw': {'clamp': [-10.0, 10.0]}})
    positions, values = player._apply_live_overrides(
        AXES, {1: 500.0}, {'Neck_Yaw': 5.0},
    )
    assert positions[1] == 500.0
    assert values['Neck_Yaw'] == 5.0


def test_no_overrides_is_a_passthrough():
    player = _player({})
    positions = {1: 500.0}
    values = {'Neck_Yaw': 5.0}
    out_positions, out_values = player._apply_live_overrides(AXES, positions, values)
    assert out_positions == positions
    assert out_values == values


def test_mute_also_filters_the_shared_publish_gate():
    """초기 위치 이동도 같은 길목을 지난다 · 고장난 모터는 초기 이동도 안 한다."""
    source = open(
        sys.modules['motion_runtime.motion_player'].__file__, encoding='utf-8',
    ).read()
    publish_start = source.index('def _publish_positions(')
    publish_body = source[publish_start:source.index('def _publish_motion_values', publish_start)]
    assert 'live_override_snapshot()' in publish_body
    assert 'muted_axes' in publish_body


def test_manager_clears_overrides_when_the_context_changes():
    """옛 조인트 이름의 오버라이드가 새 연결에 몰래 따라붙으면 안 된다.

    motion_run_manager 는 rclpy 를 끌어서 Windows 에선 import 할 수 없다 ·
    소스로 계약만 고정하고, 동작은 미니PC rclpy 시험이 본다.
    """
    import pathlib
    path = pathlib.Path(__file__).resolve().parents[1] / 'motion_runtime' / 'motion_run_manager.py'
    text = path.read_text(encoding='utf-8')
    apply_start = text.index('def _apply_execution_context(')
    assert text.index('self._clear_live_overrides()', apply_start) < text.index(
        'self._project_asset_dirs', apply_start,
    )
    assert "router.register('set_live_override', self._set_live_override)" in text
    assert "result['live_overrides'] = self.live_override_snapshot()" in text


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _blend_player(monkeypatch, overrides):
    import motion_runtime.motion_player as player_module
    clock = _Clock()
    monkeypatch.setattr(player_module.time, 'monotonic', clock)
    player = _player({})
    player.manager.live_override_snapshot = lambda: {k: dict(v) for k, v in overrides.items()}
    player._reset_override_resume()
    axes = {1: dict(AXES[0], row=dict(AXES[0]['row'], initial_move_time_sec=5.0))}
    return player, clock, axes


def test_unmute_ramps_from_where_it_stopped_instead_of_jumping(monkeypatch):
    """다시 켠 축은 선 자리 → 계획값을 초기 이동 시간(5초) 동안 잇는다 · 40."""
    overrides = {}
    player, clock, axes = _blend_player(monkeypatch, overrides)
    assert player._blend_override_changes(axes, {1: 100.0}, overrides) == {1: 100.0}

    overrides['Neck_Yaw'] = {'muted': True}            # 끔 · 발행에서 빠진다
    clock.now += 1.0
    assert player._blend_override_changes(axes, {}, overrides) == {}

    overrides.pop('Neck_Yaw')                           # 다시 켬 · 계획은 그새 900
    clock.now += 1.0
    first = player._blend_override_changes(axes, {1: 900.0}, overrides)[1]
    assert first == 100.0, '켠 순간은 선 자리 그대로'
    clock.now += 2.5                                   # 절반 · smoothstep 0.5
    assert player._blend_override_changes(axes, {1: 900.0}, overrides)[1] == 500.0
    clock.now += 2.6                                   # 5초 넘음 · 계획값
    assert player._blend_override_changes(axes, {1: 900.0}, overrides)[1] == 900.0
    clock.now += 0.02
    assert player._blend_override_changes(axes, {1: 910.0}, overrides)[1] == 910.0


def test_changing_the_live_limit_also_ramps(monkeypatch):
    overrides = {'Neck_Yaw': {'clamp': [-1.0, 1.0]}}
    player, clock, axes = _blend_player(monkeypatch, overrides)
    assert player._blend_override_changes(axes, {1: 100.0}, overrides)[1] == 100.0
    overrides.pop('Neck_Yaw')                           # 리밋 해제 · 계획 500
    clock.now += 0.02
    assert player._blend_override_changes(axes, {1: 500.0}, overrides)[1] == 100.0
    clock.now += 2.5
    assert player._blend_override_changes(axes, {1: 500.0}, overrides)[1] == 300.0


def test_a_new_run_does_not_pull_toward_the_last_runs_target(monkeypatch):
    """재생을 새로 시작하면 지난 실행의 마지막 목표에서 잇지 않는다 (그새 조그했을 수 있다)."""
    overrides = {'Neck_Yaw': {'muted': True}}
    player, clock, axes = _blend_player(monkeypatch, overrides)
    player._last_sent_positions[1] = 100.0
    overrides.pop('Neck_Yaw')                           # 멈춘 동안 다시 켬
    player._reset_override_resume()                     # 새 실행 시작
    clock.now += 1.0
    assert player._blend_override_changes(axes, {1: 900.0}, overrides)[1] == 900.0
    source = open(sys.modules['motion_runtime.motion_player'].__file__, encoding='utf-8').read()
    run_start = source.index('def _prepare_and_run(')
    assert source.index('self._reset_override_resume()', run_start) < source.index('try:', run_start)
