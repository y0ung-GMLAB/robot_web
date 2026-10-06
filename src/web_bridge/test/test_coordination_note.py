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
