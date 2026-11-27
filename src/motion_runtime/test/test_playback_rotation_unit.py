"""rad 애니메이션과 deg 애니메이션이 같은 값으로 재생된다 · 수정 목록 6-2 (2026-10-06)

재생 파서 · 조인트 매핑 화면(첫 프레임) · 웹 검사 · 시뮬 · 같은 함수를 거친다.
"""

import json
import math
from pathlib import Path

import pytest

from motion_runtime.motion_mapping_manager import MotionMappingManager
from motion_runtime.motion_run_manager import MotionRunManager

DEG_ROWS = [(1, 0.0, 10.0), (2, 0.02, -30.0), (3, 0.04, 90.0)]


def _write(path: Path, unit):
    header = {'type': 'motion_header', 'fields': ['frame', 'time_sec', 'id', 'value']}
    if unit:
        header['rotation_unit'] = unit
    scale = math.pi / 180.0 if unit == 'rad' else 1.0
    lines = [json.dumps(header)]
    for frame, time_sec, value in DEG_ROWS:
        lines.append(json.dumps([frame, time_sec, 'Neck_Yaw', value * scale, 'Eye_Pitch', -value * scale]))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _values(records, motion_id):
    """재생 안쪽 값은 rad(수정 목록 6-3) · 읽기 쉽게 deg 로 바꿔 견준다"""
    return [
        round(math.degrees(record['value']), 9)
        for record in sorted(records, key=lambda item: item['time_sec'])
        if record['motion_id'] == motion_id
    ]


@pytest.mark.parametrize('unit', ['rad', 'deg', None])
def test_runtime_reads_every_unit_as_the_same_motion(tmp_path, unit):
    manager = MotionRunManager.__new__(MotionRunManager)
    records = manager._parse_motion_records(_write(tmp_path / 'm.json', unit))

    assert _values(records, 'Neck_Yaw') == [10.0, -30.0, 90.0]
    assert _values(records, 'Eye_Pitch') == [-10.0, 30.0, -90.0]


def test_text_fallback_path_also_reads_the_unit(tmp_path):
    # 첫 줄이 헤더 객체가 아닌 통짜 JSON · 두 번째 길
    path = tmp_path / 'whole.json'
    path.write_text(json.dumps({
        'rotation_unit': 'rad',
        'data': [[1, 0.0, 'Neck_Yaw', math.pi / 4]],
    }), encoding='utf-8')
    manager = MotionRunManager.__new__(MotionRunManager)

    assert _values(manager._parse_motion_records(path), 'Neck_Yaw') == [45.0]


def test_mapping_screen_first_frame_uses_the_same_unit(tmp_path):
    manager = MotionMappingManager.__new__(MotionMappingManager)
    manager.motion_files_dir = tmp_path
    _write(tmp_path / 'r.json', 'rad')

    values, error = manager._motion_file_first_values('r.json')

    assert error == ''
    assert values['Neck_Yaw'] == pytest.approx(math.radians(10.0))
    assert values['Eye_Pitch'] == pytest.approx(math.radians(-10.0))
