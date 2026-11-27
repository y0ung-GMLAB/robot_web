"""애니메이션 json 의 조인트 값 · 웹 3D 「Blender 뷰」 · 수정 목록 98

재생과 같은 파서 · 헤더 `rotation_unit` 대로 rad 로 · 고른 시각표 · 캐시.
"""

import json
import math

from motion_web_bridge import motion_joint_values


def _content(unit, rows):
    header = {'type': 'motion_header', 'fields': ['frame', 'time_sec', 'id', 'value']}
    if unit:
        header['rotation_unit'] = unit
    return '\n'.join([json.dumps(header)] + [json.dumps(row) for row in rows]) + '\n'


def test_rad_file_is_resampled_on_an_even_grid():
    content = _content('rad', [[1, 0.0, 'a', 0.0, 'b', 1.0], [2, 0.2, 'a', 0.2, 'b', 1.0]])
    payload = motion_joint_values.joint_values_from_content(content, fps=10)
    assert payload['success'] is True
    assert payload['sample_count'] == 3
    assert payload['joints']['a'] == [0.0, 0.1, 0.2]
    assert payload['joints']['b'] == [1.0, 1.0, 1.0]
    assert payload['duration_sec'] == 0.2


def test_deg_and_headerless_files_become_rad():
    for unit in ('deg', ''):
        payload = motion_joint_values.joint_values_from_content(
            _content(unit, [[1, 0.0, 'a', 90.0], [2, 0.04, 'a', 90.0]]), fps=25)
        assert math.isclose(payload['joints']['a'][0], math.pi / 2, abs_tol=1e-6), unit


def test_unreadable_file_says_why():
    assert motion_joint_values.joint_values_from_content('')['success'] is False


def test_file_payload_is_cached_until_it_changes(tmp_path):
    path = tmp_path / 'm.json'
    path.write_text(_content('rad', [[1, 0.0, 'a', 0.0], [2, 0.04, 'a', 0.04]]), encoding='utf-8')
    first = motion_joint_values.joint_values_payload(path)
    assert first['file_id'] == 'm.json'
    assert motion_joint_values.joint_values_payload(path) is first
    path.write_text(_content('rad', [[1, 0.0, 'a', 1.0], [2, 0.04, 'a', 1.0]]), encoding='utf-8')
    assert motion_joint_values.joint_values_payload(path)['joints']['a'][0] == 1.0
    assert motion_joint_values.joint_values_payload(tmp_path / 'none.json')['success'] is False
