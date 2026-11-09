"""시간표 재생 · 연동 노드에 줄 이 PC 의 칸 · 수정 목록 186 (2026-11-09)"""

import json
import time
from pathlib import Path

import yaml

from motion_web_bridge.timetable_source import (
    DEFAULT_INITIAL_MOVE_SEC, TimetableSource, initial_move_of, motion_duration_sec, playlist_of,
)


def _motion(path: Path, seconds: float, rows: int = 2000) -> Path:
    lines = [json.dumps({'title': 't', 'type': 'motion_header', 'rotation_unit': 'rad',
                         'fields': ['frame', 'time_sec', 'id', 'value']})]
    for index in range(rows):
        time_sec = seconds * index / (rows - 1)
        lines.append(json.dumps([index + 1, round(time_sec, 3), 'f1_neck_yaw', 0.01]))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def test_the_duration_is_read_from_the_last_row_only(tmp_path):
    path = _motion(tmp_path / 'a.json', 920.0, rows=30000)
    assert motion_duration_sec(path) == 920.0
    assert motion_duration_sec(tmp_path / 'none.json') == 0.0
    (tmp_path / 'b.json').write_text('not a motion', encoding='utf-8')
    assert motion_duration_sec(tmp_path / 'b.json') == 0.0


def test_playlist_and_initial_move_follow_the_mapping():
    assert playlist_of({'motion_playlist': ['a', ' ', 'b'], 'motion_file_id': 'a'}) == ['a', 'b']
    assert playlist_of({'motion_file_id': 'a'}) == ['a']
    assert playlist_of(None) == []
    mapping = {'mappings': [{'initial_move_time_sec': 5}, {'initial_move_time_sec': 7.0}, {'x': 1}]}
    assert initial_move_of(mapping) == 7.0
    assert initial_move_of({}) == DEFAULT_INITIAL_MOVE_SEC


class _Repository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def selected_project_id(self):
        return 'p1'

    def active_file_name(self, project_id, category):
        return 'm.yaml' if category == 'motion_axis_matching' else ''

    def get_project(self, project_id):
        raise AssertionError('get_project 는 화면용 · 0.5 s · 로컬 상태에서 부르지 않는다(수정 목록 188)')

    def export_path(self, project_id, kind, name):
        return self.root / kind / name


def test_the_source_gives_schedules_playlist_and_the_need(tmp_path):
    (tmp_path / 'motions').mkdir()
    (tmp_path / 'motion_axis_matching').mkdir()
    _motion(tmp_path / 'motions' / 'a.json', 600.0)
    _motion(tmp_path / 'motions' / 'b.json', 920.0)
    (tmp_path / 'motion_axis_matching' / 'm.yaml').write_text(yaml.safe_dump({
        'motion_playlist': ['a.json', 'b.json'], 'mappings': [{'initial_move_time_sec': 7}],
    }), encoding='utf-8')
    project = tmp_path / 'motion_projects' / 'p1'
    project.mkdir(parents=True)
    (project / 'schedule_store.json').write_text(json.dumps({
        'version': 2, 'mode': 'schedule',
        'schedules': [{'schedule_id': 's1', 'start_time': '10:00:00', 'stop_time': '18:00:00'}],
    }), encoding='utf-8')
    bridge = type('B', (), {})()
    bridge.project_repository = _Repository(tmp_path)
    bridge.workspace_root = tmp_path
    fields = TimetableSource(bridge).fields()
    assert fields['motion_playlist'] == ['a.json', 'b.json']
    assert fields['cycle_need_sec'] == 927.0, '가장 긴 920 + 초기 이동 7'
    assert [item['schedule_id'] for item in fields['schedule_items']] == ['s1']


def test_the_timezone_name_comes_from_etc(tmp_path):
    from motion_web_bridge.timetable_source import local_timezone_name
    (tmp_path / 'timezone').write_text('America/New_York\n', encoding='utf-8')
    assert local_timezone_name(tmp_path) == 'America/New_York'
    (tmp_path / 'timezone').unlink()
    zone = tmp_path / 'usr' / 'share' / 'zoneinfo' / 'Asia'
    zone.mkdir(parents=True)
    (zone / 'Seoul').write_text('', encoding='utf-8')
    (tmp_path / 'localtime').symlink_to(zone / 'Seoul')
    assert local_timezone_name(tmp_path) == 'Asia/Seoul'


def test_a_refresh_in_progress_does_not_block_other_callers():
    """다시 읽는 중에 들어온 요청은 기다리지 않고 지난 값 · 수정 목록 188"""
    import threading
    entered = threading.Event()
    release = threading.Event()
    reads = []

    class Slow(TimetableSource):
        def _read(self):
            reads.append(1)
            entered.set()
            release.wait(5)
            return {'timezone': 'X'}

    source = Slow(type('B', (), {})())
    source._cache = (-1e9, {'timezone': 'old'})
    worker = threading.Thread(target=source.fields)
    worker.start()
    assert entered.wait(5)
    started = time.monotonic()
    assert source.fields() == {'timezone': 'old'}
    assert time.monotonic() - started < 0.05
    release.set()
    worker.join(5)
    assert len(reads) == 1, '한 번에 하나만 읽는다'
    assert source.fields() == {'timezone': 'X'}
