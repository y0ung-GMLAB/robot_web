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


def test_schedule_end_reason_reaches_the_runtime():
    """구간 끝 이유를 런타임까지 넘긴다 · 끝 문구 「구간 끝 · 회차 후 정지」 · 수정 목록 141"""
    end = _End()
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.schedule_end = end
    payloads = []
    bridge._request_motion_run = lambda command, payload, timeout_sec=2.0: (
        payloads.append((command, dict(payload))) or {'success': True, 'message': command}
    )

    bridge.motion_run_stop_after_cycle({'reason': 'schedule_end'})
    bridge.motion_run_stop_after_cycle({})

    assert payloads == [
        ('stop_after_cycle', {'reason': 'schedule_end'}),
        ('stop_after_cycle', {}),
    ]


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


def test_idle_schedule_end_is_not_reported_as_a_refused_stop():
    """멈춰 있던 로봇 · 런타임은 「반복 실행 중일 때만」 으로 정지를 거절한다 · 주차가 시작됐으면 성공 · 사용자 2026-10-13"""
    end = _End()
    bridge, _sent = _bridge(end)
    bridge._request_motion_run = lambda command, payload, timeout_sec=2.0: {
        'success': False, 'message': '반복 모션 실행 중일 때만 현재 회차 후 정지를 사용할 수 있습니다',
    }

    result = bridge.motion_run_stop_after_cycle({'reason': 'schedule_end'})

    assert result['success'] is True and end.begun == 1
    assert '반복 모션' in result['stop_message']
    assert bridge.motion_run_stop_after_cycle({})['success'] is False, '사람이 누른 정지는 그대로'


def test_a_failed_schedule_end_keeps_the_refusal():
    end = _End()
    end.begin = lambda: {'state': 'failed', 'message': '알람'}
    bridge, _sent = _bridge(end)
    bridge._request_motion_run = lambda command, payload, timeout_sec=2.0: {'success': False, 'message': '거절'}

    assert bridge.motion_run_stop_after_cycle({'reason': 'schedule_end'})['success'] is False


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


def test_window_reader_trusts_only_a_fresh_schedule_status():
    """주차 다시 시도를 그만두는 「구간이 다시 열림」 · 마스터 스케줄 노드 상태만 · 늙으면 안 믿음 · 수정 목록 131"""
    bridge = MotionWebBridge.__new__(MotionWebBridge)

    def status(**values):
        bridge.schedule_node_status = lambda: {'received': True, 'age_sec': 1.0, 'active_schedule_id': 's1', **values}

    status()
    assert bridge._schedule_window_open() is True
    status(active_schedule_id='')
    assert bridge._schedule_window_open() is False
    status(age_sec=60.0)
    assert bridge._schedule_window_open() is False, '스케줄 노드가 죽었다'
    status(received=False, age_sec=None)
    assert bridge._schedule_window_open() is False, '슬레이브 · 스케줄 노드가 말하지 않는다'


def test_schedule_end_wiring_reports_failures_and_resumes():
    """주차 실패 기록 · 구간 판단 · 다시 켜졌을 때 이어 하기 · 상태 프레임에 실음 · 수정 목록 131"""
    import inspect

    source = open(inspect.getsourcefile(MotionWebBridge), encoding='utf-8').read()
    assert 'in_window=self._schedule_window_open' in source
    assert "category='system', event_type=event_type, target='스케줄 끝'" in source
    assert 'self._resume_schedule_end()' in source and 'self.schedule_end.resume()' in source
    snapshot = inspect.getsource(MotionWebBridge.snapshot)
    assert "'schedule_end': (" in snapshot and 'self.schedule_end.status()' in snapshot
