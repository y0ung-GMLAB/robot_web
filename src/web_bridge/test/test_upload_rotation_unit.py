"""웹 검사·업로드도 애니메이션 각도 단위를 읽는다 · 수정 목록 6-2 (2026-10-06)"""

import json
import math

import pytest

from motion_web_bridge.motion_file_analysis import analyze_motion_json
from motion_web_bridge.project_repository import ProjectRepository


def _content(unit, value):
    header = {'type': 'motion_header', 'fields': ['frame', 'time_sec', 'id', 'value']}
    if unit is not None:
        header['rotation_unit'] = unit
    return '\n'.join([
        json.dumps(header),
        json.dumps([1, 0.0, 'Neck_Yaw', value]),
        json.dumps([2, 0.02, 'Neck_Yaw', value * 2]),
    ]) + '\n'


def test_analysis_shows_rad_files_in_the_same_unit_as_playback():
    result = analyze_motion_json(_content('rad', math.pi / 18), include_records=True)

    assert result['valid'] is True
    assert result['rotation_unit'] == 'rad'
    preview = sorted(record['value'] for record in result['preview_records'])
    graph = sorted(
        point['value'] for series in result['graph_series'] for point in series['points']
    )
    # 값은 내부 단위(rad) · 화면이 deg 로 바꿔 보여 준다 · 수정 목록 6
    assert result['value_unit'] == 'rad'
    assert preview == pytest.approx([math.radians(10.0), math.radians(20.0)])
    assert graph == pytest.approx([math.radians(10.0), math.radians(20.0)])


def test_analysis_refuses_an_unknown_unit():
    result = analyze_motion_json(_content('grad', 1.0), include_records=False)

    assert result['valid'] is False
    assert '각도 단위' in result['message']


def test_upload_refuses_an_unknown_unit_and_accepts_deg_rad_and_legacy():
    for unit in ('rad', 'deg', None):
        ProjectRepository._validate_content('motions', 'a.json', _content(unit, 1.0))
    with pytest.raises(ValueError, match='각도 단위'):
        ProjectRepository._validate_content('motions', 'a.json', _content('grad', 1.0))
