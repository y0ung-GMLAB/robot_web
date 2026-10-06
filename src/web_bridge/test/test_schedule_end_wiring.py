"""스케줄 끝 동작의 배선 · 브리지 정지·시작 · 스케줄러 · 그룹 전달 · 수정 목록 36"""

from motion_web_bridge.bridge_node import MotionWebBridge


class _End:
    def __init__(self, *, active=False, blocker=''):
        self._active = active
        self._blocker = blocker
        self.begun = 0
        self.checked = 0

    def active(self):
        return self._active

    def status(self):
        return {'state': 'parking' if self._active else 'idle', 'message': '기준점 이동 중'}

    def begin(self):
        self.begun += 1
        return {'state': 'waiting_cycle'}

    def start_blocker(self):
        self.checked += 1
        return self._blocker


def _bridge(end):
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.schedule_end = end
    sent = []
    bridge._request_motion_run = lambda command, payload, timeout_sec=2.0: (
        sent.append(command) or {'success': True, 'message': command}
    )
    return bridge, sent


def test_schedule_end_stop_begins_parking_and_plain_stop_does_not():
    end = _End()
    bridge, sent = _bridge(end)

    bridge.motion_run_stop_after_cycle({'reason': 'schedule_end'})
    bridge.motion_run_stop_after_cycle({})
    bridge.motion_run_stop_after_cycle()

    assert sent == ['stop_after_cycle'] * 3
    assert end.begun == 1


def test_repeated_schedule_stops_do_not_cut_the_park_move():
    end = _End(active=True)
    bridge, sent = _bridge(end)

    result = bridge.motion_run_stop_after_cycle({'reason': 'schedule_end'})

    assert result['success'] is True
    assert sent == []          # 주차 중인 초기 위치 이동에 회차 후 정지를 보내지 않는다
    assert end.begun == 0


def test_start_gate_restores_servos_except_for_the_park_move_itself():
    end = _End(blocker='서보를 켜지 못했습니다')
    bridge, _sent = _bridge(end)

    assert bridge.schedule_end_start_blocker({}) == '서보를 켜지 못했습니다'
    assert bridge.schedule_end_start_blocker({'request_source': 'schedule_end'}) == ''
    assert end.checked == 1


def test_scheduler_sends_the_reason_only_in_schedule_mode():
    from motion_schedule import motion_schedule_node as node_module

    source = open(node_module.__file__, encoding='utf-8').read()
    assert "reason='schedule_end' if self._run_mode == SCHEDULE_MODE else ''" in source
    assert '"reason": reason' in source


def test_group_stop_carries_the_reason_to_every_pc():
    import motion_coordination.coordination_node as coordination_node

    source = open(coordination_node.__file__, encoding='utf-8').read()
    assert "'reason': str(getattr(message, 'stop_reason', '') or '')" in source
    assert 'stop_reason=reason' in source
