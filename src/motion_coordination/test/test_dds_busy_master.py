"""실제 DDS 두 프로세스 · 바쁜 마스터는 빠지고 진행만 · 그 마스터의 로컬은 건드리지 않는다 · 수정 목록 136

`MOTION_RUN_DDS_INTEGRATION=1` 일 때만 돈다 (`test_dds_process_integration.py` 와 같은 길 · 빌드된
`motion_coordination_node` 필요).
"""

import os
import subprocess
from pathlib import Path

import pytest

from motion_common.group_config import GroupConfig, save_group_config
from test_dds_process_integration import (
    _FakeLocalWebBridge,
    _free_port,
    _get,
    _one_peer_snapshot,
    _post,
    _wait,
)

pytestmark = pytest.mark.skipif(
    os.environ.get('MOTION_RUN_DDS_INTEGRATION') != '1',
    reason='real DDS process integration is opt-in',
)


def test_a_master_running_solo_coordinates_a_group_it_does_not_join(tmp_path):
    executable = Path(
        os.environ.get('MOTION_COORDINATION_EXECUTABLE')
        or Path.cwd()
        / 'install/motion_coordination/lib/motion_coordination/'
        'motion_coordination_node'
    )
    if not executable.is_file():
        pytest.skip('motion_coordination_node is not built')
    master_bridge = _FakeLocalWebBridge(cycle_duration_sec=0.2)
    # 마스터는 단독 연속 재생 중(V-4)
    master_bridge._set_status({'state': 'running', 'phase': 'running'})
    slave_bridge = _FakeLocalWebBridge(cycle_duration_sec=0.2)
    bridges = [master_bridge, slave_bridge]
    ports = [_free_port(), _free_port()]
    configs = []
    for pc_id in ('dds-busy-a', 'dds-busy-b'):
        path = tmp_path / f'{pc_id}.yaml'
        save_group_config(path, GroupConfig(
            pc_id, pc_id, True, 'dds-busy-test', 83,
            is_master=pc_id.endswith('-a'),
            heartbeat_sec=0.1, warning_timeout_sec=0.8,
            peer_timeout_sec=1.6, start_lead_sec=0.5,
            schedule_ack_margin_sec=0.1,
            max_trigger_sync_uncertainty_ms=20.0,
            trigger_sync_samples=5, prepare_timeout_sec=3.0,
            trigger_report_timeout_sec=1.0,
        ))
        configs.append(path)
    processes = []
    try:
        for path, port, bridge in zip(configs, ports, bridges):
            environment = dict(os.environ)
            environment.update({
                'MOTION_COORDINATION_CONFIG': str(path),
                'MOTION_COORDINATION_LOCAL_PORT': str(port),
                'MOTION_WEB_BRIDGE_PORT': str(bridge.port),
                'ROS_LOCALHOST_ONLY': '0',
            })
            processes.append(subprocess.Popen(
                [str(executable)], env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
        for port in ports:
            _wait(lambda port=port: _get(port).get('node_connected'))
            assert _post(port, 'join')['success'] is True
        for port in ports:
            _wait(lambda port=port: _one_peer_snapshot(port))
        # 마스터가 제 로컬 상태(단독 재생)를 받을 때까지
        _wait(lambda: _get(ports[0]).get('start_preview', {}).get('excluded', {}).get('dds-busy-a'))

        started = _post(ports[0], 'start_group')

        assert started['success'] is True, started
        assert started['participants'] == ['dds-busy-b']
        assert started['excluded'] == {'dds-busy-a': '단독 재생 중'}
        _wait(lambda: slave_bridge.start_cycles()[:2] == [1, 2], timeout=10.0)
        assert _post(ports[0], 'stop_now')['success'] is True
        _wait(lambda: slave_bridge.calls('stop_now'), timeout=5.0)
        # 마스터 로컬에는 그룹 명령이 하나도 안 갔다 · 단독 재생 그대로
        for command in ('group_prepare', 'group_start_at', 'group_initialize_at', 'stop_now', 'group_cancel'):
            assert master_bridge.calls(command) == [], command
        assert _get(ports[0]).get('coordination_error', {}).get('active') is not True
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for bridge in bridges:
            bridge.close()
