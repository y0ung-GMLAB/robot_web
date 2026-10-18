"""X-Touch 바탕 위 녹화 · 재생 노드 쪽 · 프레임 알림 · 덮어쓴 조인트만 바꿔 보냄 · 수정 목록 156 ⑨-2"""

import json
import math
import threading
from types import SimpleNamespace

from motion_runtime.xtouch_take import TakePlayback

R = math.radians


class _Pub:
    def __init__(self):
        self.sent = []

    def publish(self, msg):
        self.sent.append(json.loads(msg.data))


def _plan(count=200):
    row = {'gear_ratio': 100.0, 'scale': 1.0, 'invert': False, 'reference_position_rad': 0.0, 'offset_rad': 0.0}
    samples = [
        {'time_sec': k * 0.02, 'positions': {1: 100.0 * 0.001 * k, 2: 0.0},
         'motion_values': {'neck_yaw': 0.001 * k, 'eye': 0.0}}
        for k in range(count)
    ]
    return {
        'xtouch_take': True, 'xtouch_take_id': 'abc',
        'axes': [
            {'motion_id': 'neck_yaw', 'motor_axis': 1, 'row': row, 'motor_for_limits': {}},
            {'motion_id': 'eye', 'motor_axis': 2, 'row': row, 'motor_for_limits': {}},
        ],
        'punch_joints': {'neck_yaw': {'max_velocity': R(9), 'max_acceleration': R(14), 'lower': R(-15), 'upper': R(15)}},
        'samples': samples,
    }


def _manager():
    return SimpleNamespace(period_sec=0.02, _punch_lock=threading.Lock(), _punch_controller=None, _take_frame_pub=_Pub())


def test_frames_are_announced_and_untouched_joints_go_out_as_planned():
    manager = _manager()
    plan = _plan()
    take = TakePlayback(manager, plan)
    assert manager._punch_controller is take.controller
    sample = plan['samples'][5]
    positions, values = take.apply(5, sample['positions'], sample['motion_values'])
    assert positions == sample['positions'] and values == sample['motion_values']
    assert manager._take_frame_pub.sent[-1]['frame'] == 5
    assert manager._take_frame_pub.sent[-1]['take_id'] == 'abc'
    assert manager._take_frame_pub.sent[-1]['values'] == {}
    take.close()
    assert manager._punch_controller is None
    assert manager._take_frame_pub.sent[-1]['end'] is True


def test_a_grabbed_joint_is_replaced_and_reported_and_the_plan_is_not_changed():
    manager = _manager()
    plan = _plan()
    take = TakePlayback(manager, plan)
    import time
    for k in range(60):
        if 10 <= k < 40:
            manager._punch_controller.input('neck_yaw', R(3.0), time.monotonic())
        if k == 40:
            manager._punch_controller.release('neck_yaw')
        sample = plan['samples'][k]
        positions, values = take.apply(k, sample['positions'], sample['motion_values'])
        report = manager._take_frame_pub.sent[-1]
        if 11 <= k < 40:
            assert 'neck_yaw' in report['values']
            assert values['neck_yaw'] == report['values']['neck_yaw']
            assert abs(positions[1] - 100.0 * values['neck_yaw']) < 1e-9     # 매핑 식으로 모터 값
            assert values['eye'] == 0.0 and positions[2] == 0.0                # 다른 조인트 그대로
    assert plan['samples'][20]['motion_values']['neck_yaw'] == 0.02           # 계획은 안 바뀜
