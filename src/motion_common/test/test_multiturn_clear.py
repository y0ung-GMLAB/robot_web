"""다회전 클리어 뒤 기준점 보호 · PC 단위 표시 · 판정 하나 · 수정 목록 140 ③"""

from motion_common import multiturn_clear as mc


def test_record_then_block_until_a_reference_is_saved_after_the_clear(tmp_path):
    path = mc.marker_path(tmp_path)
    assert path == tmp_path / 'runtime' / 'multiturn_clear.json'
    assert mc.block_reason(mc.load(path)) == ''                   # 파일 없음 = 막지 않음

    axes = mc.record_clear(path, [
        {'axis': 1, 'serial': 4321, 'master_index': 0, 'slave_position': 1},
        {'axis': None, 'slave_position': 2},                       # 미등록 드라이브는 적지 않음
    ], now=1000.0)
    assert axes == [1]
    state = mc.load(path)
    assert state['axes']['1']['serial'] == 4321 and state['axes']['1']['pending'] is True
    assert mc.block_reason(state) == '1번 모터 다회전 클리어 뒤 기준점 다시 지정 필요'

    # 클리어 전에 지정한 기준점은 못 푼다 · 뒤에 지정하면 푼다
    assert mc.mark_reference_saved(path, [{'motor_axis': 1, 'reference_set_at': 999.0}]) == []
    assert mc.mark_reference_saved(path, [{'motor_axis': 1, 'reference_set_at': 1001.0}]) == [1]
    state = mc.load(path)
    assert mc.pending_axes(state) == [] and state['axes']['1']['cleared_at'] == 1000.0
    assert mc.block_reason(state) == ''


def test_other_projects_with_an_older_reference_stay_blocked(tmp_path):
    path = mc.marker_path(tmp_path)
    mc.record_clear(path, [{'axis': 1}, {'axis': 3}], now=1000.0)
    mc.mark_reference_saved(path, [{'motor_axis': 1, 'reference_set_at': 2000.0}, {'motor_axis': 3, 'reference_set_at': 2000.0}])
    state = mc.load(path)
    other_project = [
        {'motion_id': 'a', 'motor_axis': 1, 'reference_set_at': 500.0},
        {'motion_id': 'b', 'motor_axis': 3},                       # 칸 없음 = 클리어 전
        {'motion_id': 'c', 'motor_axis': 0},                       # 클리어한 적 없는 축
        {'motion_id': 'd', 'motor_axis': 3, 'enabled': False},
    ]
    assert mc.stale_axes(state, other_project) == [1, 3]
    assert mc.block_reason(state, other_project) == '1번 · 3번 모터 다회전 클리어 뒤 기준점 다시 지정 필요'
    summary = mc.summary(state, other_project)
    assert summary['pending_axes'] == [] and summary['blocked_axes'] == [1, 3]


def test_a_second_clear_resets_the_time_and_pending(tmp_path):
    path = mc.marker_path(tmp_path)
    mc.record_clear(path, [{'axis': 1}], now=1000.0)
    mc.mark_reference_saved(path, [{'motor_axis': 1, 'reference_set_at': 1500.0}])
    mc.record_clear(path, [{'axis': 1}], now=3000.0)
    state = mc.load(path)
    assert mc.pending_axes(state) == [1]
    assert mc.stale_axes(state, [{'motor_axis': 1, 'reference_set_at': 1500.0}]) == [1]


def test_reference_times_take_the_oldest_row_per_axis_and_broken_files_read_empty(tmp_path):
    assert mc.reference_times([
        {'motor_axis': 1, 'reference_set_at': 5.0}, {'motor_axis': 1}, {'motor_axis': None}, 'x',
    ]) == {1: 0.0}
    path = mc.marker_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{not json', encoding='utf-8')
    assert mc.load(path) == {'version': 1, 'axes': {}}
    path.write_text('{"axes": {"2": {"cleared_at": "x"}, "3": {"cleared_at": 1}}}', encoding='utf-8')
    assert list(mc.load(path)['axes']) == ['3']
