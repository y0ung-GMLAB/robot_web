"""애니메이션 상세 그래프 · 12 개 넘는 조인트도 빠지지 않는다 · 수정 목록 138

나레이션(f1~f4 × 5 = 20 조인트)에서 이름 순 12 개만 오고 8 개는 말없이 빠졌다 ·
이제 처음 12 개는 `graph_series`, 나머지는 같은 응답의 `graph_series_extra` 로 온다.
"""

import json

from motion_web_bridge import motion_file_analysis


def _content(joint_ids, frames=3):
    lines = [json.dumps({'type': 'motion_header', 'rotation_unit': 'rad',
                         'fields': ['frame', 'time_sec', 'id', 'value']})]
    for frame in range(1, frames + 1):
        row = [frame, round((frame - 1) * 0.02, 6)]
        for joint in joint_ids:
            row += [joint, 0.01 * frame]
        lines.append(json.dumps(row))
    return '\n'.join(lines) + '\n'


NARRATION = [f'f{robot}-{axis}' for robot in range(1, 5) for axis in range(1, 6)]


def test_twenty_joints_send_twelve_plus_eight_extra():
    result = motion_file_analysis.analyze_motion_json(_content(NARRATION), include_records=True)

    assert result['valid'] is True
    assert result['graph_series_total'] == 20
    assert len(result['graph_series']) == motion_file_analysis.GRAPH_SERIES_SHOWN == 12
    assert len(result['graph_series_extra']) == 8
    shown = [series['motion_id'] for series in result['graph_series']]
    extra = [series['motion_id'] for series in result['graph_series_extra']]
    assert shown + extra == sorted(NARRATION), '이름 순 · 겹침·빠짐 없음'
    assert all(len(series['points']) == 3 for series in result['graph_series_extra'])


def test_few_joints_have_no_extra():
    result = motion_file_analysis.analyze_motion_json(_content(['a', 'b']), include_records=True)

    assert result['graph_series_total'] == 2
    assert [series['motion_id'] for series in result['graph_series']] == ['a', 'b']
    assert result['graph_series_extra'] == []


def test_list_entry_drops_extra_graphs(tmp_path):
    motion_file_analysis._SUMMARY_CACHE.clear()
    path = tmp_path / 'narration.json'
    path.write_text(_content(NARRATION), encoding='utf-8')

    listed = motion_file_analysis.motion_file_entry(path, include_detail=False)['analysis']
    detail = motion_file_analysis.motion_file_entry(path, include_detail=True)['analysis']

    for key in ('graph_series', 'graph_series_extra', 'graph_series_total'):
        assert key not in listed, f'목록에는 {key} 를 싣지 않는다'
        assert key in detail
    assert listed['motion_id_count'] == 20
