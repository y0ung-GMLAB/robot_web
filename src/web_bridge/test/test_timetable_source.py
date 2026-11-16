"""시간표 재생 · 연동 노드에 줄 이 PC 의 칸 · 수정 목록 186 (2026-11-09)"""

import json
import math
import time
from pathlib import Path

import yaml

from motion_common.timing import INITIAL_MOVE_FALLBACK_SEC
from motion_web_bridge.timetable_source import (
    TimetableSource, initial_move_of, motion_duration_sec, playlist_of,
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
    # 매핑에 없으면 0(모름) · 짐작한 5 s 를 「이 PC 값」 으로 보내지 않는다 · 수정 목록 205
    assert initial_move_of({}) == 0.0


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
    assert fields['initial_move_sec'] == 7.0


def test_a_mapping_without_an_initial_move_time_reports_none_and_needs_the_longest_option(tmp_path):
    """초기 이동 시간이 없는 매핑 · 칸을 빼고 보낸다 · 필요 시간은 가장 긴 선택지(10 s)로 · 수정 목록 205

    전에는 5 s 를 「이 PC 값」 으로 보내 연동 노드의 10 s 짐작과 갈렸다.
    """
    (tmp_path / 'motions').mkdir()
    (tmp_path / 'motion_axis_matching').mkdir()
    _motion(tmp_path / 'motions' / 'a.json', 600.0)
    (tmp_path / 'motion_axis_matching' / 'm.yaml').write_text(yaml.safe_dump({
        'motion_file_id': 'a.json', 'mappings': [{'motion_id': 'f1_neck_yaw', 'initial_mode': 'first_frame'}],
    }), encoding='utf-8')
    bridge = type('B', (), {})()
    bridge.project_repository = _Repository(tmp_path)
    bridge.workspace_root = tmp_path
    fields = TimetableSource(bridge).fields()
    assert 'initial_move_sec' not in fields
    assert fields['cycle_need_sec'] == 600.0 + INITIAL_MOVE_FALLBACK_SEC == 610.0


# ---------------------------------------------------------------------- #
# 206 뒤처리 · 13-1 · 기준점(기본) 방식이고 첫 프레임 ≠ 0 이면 재생 관리자는 초기 이동을 두 번 한다
# (초기 위치 = 모션 0° → 같은 시간으로 첫 프레임까지) · 웹의 필요 시간은 한 번만 세어 자동 회차 간격이 모자랐다
# ---------------------------------------------------------------------- #

def _source(tmp_path, mappings, files):
    (tmp_path / 'motions').mkdir()
    (tmp_path / 'motion_axis_matching').mkdir()
    for name, (seconds, first) in files.items():
        _first_frame_motion(tmp_path / 'motions' / name, seconds, first)
    (tmp_path / 'motion_axis_matching' / 'm.yaml').write_text(yaml.safe_dump({
        'motion_playlist': list(files), 'mappings': mappings,
    }), encoding='utf-8')
    bridge = type('B', (), {})()
    bridge.project_repository = _Repository(tmp_path)
    bridge.workspace_root = tmp_path
    return TimetableSource(bridge)


def _first_frame_motion(path: Path, seconds: float, first: dict, unit: str = 'rad') -> Path:
    """Blender 내보내기 꼴(한 줄에 모든 조인트) · 첫 줄 값 `first` · 그 뒤는 다른 값"""
    lines = [json.dumps({'title': 't', 'type': 'motion_header', 'rotation_unit': unit,
                         'fields': ['frame', 'time_sec', 'id', 'value']})]
    rows = 200
    for index in range(rows):
        time_sec = round(seconds * index / (rows - 1), 3)
        row = [index + 1, time_sec]
        for motion_id, value in first.items():
            row += [motion_id, value if index == 0 else value + 0.2]
        lines.append(json.dumps(row))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def test_reference_mode_with_a_nonzero_first_frame_counts_the_initial_move_twice(tmp_path):
    source = _source(tmp_path, [
        {'motion_id': 'f1_neck_yaw', 'initial_move_time_sec': 5.0},          # 방식 없음 = 기준점(기본)
        {'motion_id': 'f1_neck_pitch', 'initial_move_time_sec': 5.0, 'initial_mode': 'reference'},
    ], {'a.json': (600.0, {'f1_neck_yaw': 0.1, 'f1_neck_pitch': 0.0})})
    fields = source.fields()
    assert fields['initial_move_sec'] == 5.0
    assert fields['cycle_need_sec'] == 600.0 + 2 * 5.0, '기준점 → 첫 프레임(0.1 rad) · 같은 5 s 로 한 번 더'


def test_first_frame_mode_keeps_one_move_as_on_the_ny_robots(tmp_path):
    """NY 플로팅 · 모든 줄이 첫 프레임 방식 · 초기 위치 = 첫 프레임 · 한 번 · 전과 같다"""
    source = _source(tmp_path, [
        {'motion_id': 'f1_neck_yaw', 'initial_move_time_sec': 10.0, 'initial_mode': 'first_frame'},
        {'motion_id': 'f1_eye_pitch', 'initial_move_time_sec': 10.0, 'initial_mode': 'first_frame'},
    ], {'a.json': (920.0, {'f1_neck_yaw': 0.2, 'f1_eye_pitch': -0.1})})
    assert source.fields()['cycle_need_sec'] == 930.0


def test_reference_mode_with_a_zero_first_frame_is_one_move(tmp_path):
    """첫 프레임이 기준점(0) 그대로 · 허용 오차(관절 0.05°) 안 · 재생 관리자도 잇지 않는다 · deg 파일도 같은 규칙"""
    (tmp_path / 'motions').mkdir()
    (tmp_path / 'motion_axis_matching').mkdir()
    _first_frame_motion(tmp_path / 'motions' / 'a.json', 600.0, {'f1_neck_yaw': 0.04}, unit='deg')
    _first_frame_motion(tmp_path / 'motions' / 'b.json', 300.0, {'f1_neck_yaw': 3.0}, unit='deg')
    (tmp_path / 'motion_axis_matching' / 'm.yaml').write_text(yaml.safe_dump({
        'motion_playlist': ['a.json', 'b.json'],
        'mappings': [{'motion_id': 'f1_neck_yaw', 'initial_move_time_sec': 7.0}],
    }), encoding='utf-8')
    bridge = type('B', (), {})()
    bridge.project_repository = _Repository(tmp_path)
    bridge.workspace_root = tmp_path
    # a · 600 + 7(한 번) · b · 300 + 14(두 번 · 첫 프레임 3°) · 회차마다 큰 쪽
    assert TimetableSource(bridge).fields()['cycle_need_sec'] == 607.0


def test_manual_mode_and_range_clamps_follow_the_runtime_rule():
    from motion_common import timed_cycle

    rows = [{'motion_id': 'a', 'initial_mode': 'manual', 'initial_motion_position_deg': 10.0,
             'motion_lower_deg': -5.0, 'motion_upper_deg': 5.0}]
    # 직접 지정 10° 와 첫 프레임 20° 가 둘 다 범위 5° 로 잘린다 · 같다 → 잇지 않음
    assert timed_cycle.blends_to_first_frame(rows, {'a': math.radians(20.0)}) is False
    assert timed_cycle.blends_to_first_frame(rows, {'a': math.radians(1.0)}) is True
    # 끈 줄 · 파일에 없는 조인트는 빠진다
    assert timed_cycle.blends_to_first_frame([{**rows[0], 'enabled': False}], {'a': 1.0}) is False
    assert timed_cycle.blends_to_first_frame(rows, {'b': 1.0}) is False
    # 첫 프레임을 못 읽으면 길게(기준점 · 직접 지정 줄이 있을 때만)
    assert timed_cycle.blends_to_first_frame(rows, None) is True
    assert timed_cycle.blends_to_first_frame([{'motion_id': 'a', 'initial_mode': 'first_frame'}], None) is False
    assert timed_cycle.planned_initial_move_sec(7.0, True) == 14.0
    assert timed_cycle.planned_initial_move_sec(7.0, False) == 7.0


def test_the_first_frame_is_read_from_the_head_of_a_long_file_only(tmp_path):
    """25 MB 파일도 앞 몇 줄 · 끝까지 읽지 않는다 · 머리 줄 없는 꼴은 모름(None)"""
    from motion_web_bridge.timetable_source import first_frame_values

    path = _first_frame_motion(tmp_path / 'a.json', 920.0, {'x': 0.5, 'y': -0.25})
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write('this line would break a full read\n')
    assert first_frame_values(path, ['x', 'y']) == {'x': 0.5, 'y': -0.25}
    (tmp_path / 'b.csv').write_text('frame,time,motion_id,value\n1,0,x,1\n', encoding='utf-8')
    assert first_frame_values(tmp_path / 'b.csv', ['x']) is None


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
