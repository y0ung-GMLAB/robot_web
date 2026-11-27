"""상위 서비스 비정상 종료 표지 · 수정 목록 72"""

import json

from motion_common import upper_restart


def test_only_abnormal_exits_leave_a_marker(tmp_path):
    for code in (0, -2, -15, None):
        assert upper_restart.write_marker(tmp_path, 'motion_supervisor', code) is False
    assert not upper_restart.marker_path(tmp_path).exists()

    assert upper_restart.write_marker(tmp_path, 'motion_supervisor', -9, now=1000.0) is True
    data = json.loads(upper_restart.marker_path(tmp_path).read_text(encoding='utf-8'))
    assert data == {'node': 'motion_supervisor', 'returncode': -9, 'stopped_at': 1000.0}


def test_take_marker_reads_once_and_removes_it(tmp_path):
    upper_restart.write_marker(tmp_path, 'motion_state_monitor', 1, now=1000.0)

    marker = upper_restart.take_marker(tmp_path)

    assert marker['node'] == 'motion_state_monitor' and marker['returncode'] == 1
    assert upper_restart.take_marker(tmp_path) is None
    content = upper_restart.event_content(marker)
    assert 'motion_state_monitor 비정상 종료(코드 1' in content and '자동 재시작' in content


def test_broken_marker_is_dropped(tmp_path):
    path = upper_restart.marker_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{broken', encoding='utf-8')
    assert upper_restart.take_marker(tmp_path) is None
    assert not path.exists()
