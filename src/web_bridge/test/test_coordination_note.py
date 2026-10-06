"""연동 노드가 남기는 운영 로그 · 그룹 실행에서 뺀 PC · 수정 목록 30-2"""

from motion_web_bridge.coordination_bridge import local_motion_control


class _Bridge:
    def __init__(self):
        self.notes = []

    def record_coordination_note(self, event_type, content, details):
        self.notes.append((event_type, content, details))
        return {'success': True}


def test_group_note_goes_to_the_operation_log_without_touching_motion():
    bridge = _Bridge()
    result = local_motion_control(bridge, {
        'command': 'group_note', 'event_type': 'group_excluded',
        'message': '그룹 실행 시작 · 뺀 PC pc-c(미접속)',
        'excluded': {'pc-c': '미접속'}, 'participants': ['pc-a'], 'execution_id': 'exec-1',
        'ignored': 'x',
    })
    assert result == {'success': True}
    assert bridge.notes == [(
        'group_excluded', '그룹 실행 시작 · 뺀 PC pc-c(미접속)',
        {'execution_id': 'exec-1', 'excluded': {'pc-c': '미접속'}, 'participants': ['pc-a']},
    )]


class _JoinBridge(_Bridge):
    def __init__(self):
        super().__init__()
        self.prepared = []
        self.commits = []

    def motion_group_prepare(self, request):
        self.prepared.append(dict(request))
        return {'success': True}

    def motion_group_join_commit(self, payload):
        self.commits.append(dict(payload))
        return {'success': True}

    def motion_run_status(self):
        return {'status': {}}


def test_group_join_prepares_without_an_initialize_time(monkeypatch):
    """수정 목록 30-3 · 복귀 PC 는 계획만 만든다 · 움직이는 시각은 합류 확정 뒤 회차 초기화"""
    from motion_web_bridge import coordination_bridge
    monkeypatch.setattr(coordination_bridge, '_local_motion_selection', lambda _bridge: {
        'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml',
    })
    bridge = _JoinBridge()
    result = local_motion_control(bridge, {
        'command': 'group_join', 'execution_id': 'exec-a', 'join_cycle_number': 3,
        'repeat_mode': 'reinitialize', 'run_mode': 'continuous', 'sync_mode': 'lockstep',
        'initialize_monotonic': 123.0,
    })
    assert result == {'success': True}
    [request] = bridge.prepared
    assert request['join_cycle_number'] == 3
    assert 'initialize_monotonic' not in request
    assert request['group_execution'] is True and request['run_mode'] == 'continuous'

    assert local_motion_control(bridge, {'command': 'group_join', 'execution_id': 'x'})['success'] is False
    local_motion_control(bridge, {'command': 'group_join_commit', 'execution_id': 'exec-a', 'cycle_number': 3})
    assert bridge.commits == [{'execution_id': 'exec-a', 'cycle_number': 3}]
