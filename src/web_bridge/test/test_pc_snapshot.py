"""PC 설정 사진 · 껐다 켜기 전후 비교 · 2026-10-09 (scripts/pc_snapshot.py)"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('pc_snapshot', ROOT / 'scripts/pc_snapshot.py')
pc_snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc_snapshot)


def test_addresses_default_to_the_robot_web_port():
    assert pc_snapshot.base_url('172.16.8.21') == 'http://172.16.8.21:8000'
    assert pc_snapshot.base_url('172.16.8.30:8100') == 'http://172.16.8.30:8100'
    assert pc_snapshot.base_url('http://floating4.local:8000/') == 'http://floating4.local:8000'


def test_diff_shows_only_settings_not_clocks_or_positions():
    before = {'http://a:8000': {'/api/coordination': {
        'config': {'group_id': 'stage-a', 'joined': True}, 'status_age_sec': 0.3,
        'runtime': {'peers': [{'pc_id': 'b'}], 'joined': True},
    }, '/api/system/time': {'clock': {'local_time': '09:00', 'timezone': 'Asia/Seoul'}}}}
    after = {'http://a:8000': {'/api/coordination': {
        'config': {'group_id': 'stage-a', 'joined': False}, 'status_age_sec': 1.9,
        'runtime': {'peers': [], 'joined': False},
    }, '/api/system/time': {'clock': {'local_time': '09:05', 'timezone': 'Asia/Seoul'}}}}
    lines = pc_snapshot.diff(before, after)
    assert lines[0] == '== http://a:8000 · 바뀐 칸 2개'
    assert any('config.joined: true → false' in line for line in lines)
    assert not any('local_time' in line or 'status_age_sec' in line or 'peers' in line for line in lines)


def test_only_get_requests():
    source = (ROOT / 'scripts/pc_snapshot.py').read_text(encoding='utf-8')
    assert 'method=' not in source and 'data=' not in source, '읽기만 한다'
