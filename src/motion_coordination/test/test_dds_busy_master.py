"""실제 DDS 두 프로세스 · 바쁜 마스터는 빠지고 진행만 · 그 마스터의 로컬은 건드리지 않는다 · 수정 목록 136

`MOTION_RUN_DDS_INTEGRATION=1` 일 때만 돈다 (`test_dds_process_integration.py` 와 같은 길 · 빌드된
`motion_coordination_node` 필요) · 마스터의 단독 재생은 가짜 재생 관리자 상태(로컬 DDS)로 보인다 · 수정 목록 209.
"""

import os

import pytest

from test_dds_process_integration import _Group, _get, _post, _wait

pytestmark = pytest.mark.skipif(
    os.environ.get('MOTION_RUN_DDS_INTEGRATION') != '1',
    reason='real DDS process integration is opt-in',
)


def test_a_master_running_solo_coordinates_a_group_it_does_not_join(tmp_path):
    group = _Group(tmp_path, 'dds-busy', 83, 98, [
        # 마스터는 단독 연속 재생 중(V-4)
        {'cycle': 0.2, 'status': {'state': 'running', 'phase': 'running'}},
        {'cycle': 0.2},
    ])
    master, slave = group.pcs
    try:
        group.join_all()
        # 마스터가 제 로컬 상태(단독 재생)를 받을 때까지
        _wait(lambda: _get(group.ports[0]).get('start_preview', {}).get('excluded', {}).get('dds-busy-a'))

        started = _post(group.ports[0], 'start_group')

        assert started['success'] is True, started
        assert started['participants'] == ['dds-busy-b']
        assert started['excluded'] == {'dds-busy-a': '단독 재생 중'}
        _wait(lambda: slave.start_cycles()[:2] == [1, 2], timeout=10.0)
        assert _post(group.ports[0], 'stop_now')['success'] is True
        _wait(lambda: slave.calls('stop_now'), timeout=5.0)
        # 마스터 로컬에는 그룹 명령이 하나도 안 갔다 · 단독 재생 그대로
        for command in ('group_prepare', 'group_start_at', 'group_initialize_at', 'stop_now', 'group_cancel'):
            assert master.calls(command) == [], command
        assert master.safety_stops == 0, '감독 안전 정지도 안 보낸다'
        assert _get(group.ports[0]).get('coordination_error', {}).get('active') is not True
    finally:
        group.close()
