"""배열로 든 레코드 · 샘플이 옛 사전 길과 비트까지 같고 · 캐시가 바이트로 묶인다 · 수정 목록 170

NY 실물 2026-11-03 · 920 s × 20 조인트 애니를 재생 목록에 두고 3D 화면까지 켜자 floating4(4.7 GB)가
스왑으로 넘어가 motion_run_manager 가 답을 멈췄다 · 레코드(사전) 캐시만 파일 하나 88 MB 였다.

여기서 지키는 것:

    파일 → 조인트별 배열 · 옛 레코드 사전 목록(같은 값 · 같은 정렬)과 같다 · 단위 · 통짜 JSON 길도
    구간 자르기 · 옛 `slice_records` + `_motion_groups` 와 같다
    20 ms 재샘플 · 옛 사전 샘플(옛 식 그대로 옮긴 참조 구현)과 모든 칸이 비트까지 같다
    레코드 하나 32 B · 샘플 하나 (2 + 축 × 2) × 8 B
    캐시 · 바이트 예산을 넘으면 오래된 것부터 버린다 · 방금 넣은 것은 남긴다
"""

import json
import math
import struct

import pytest

from motion_common import joint_mapping, motion_segment, motion_table, motion_tracks, units
from motion_runtime import motion_run_rules
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.packed_samples import PackedSamples
from motion_runtime.plan_builder import _sample_plan
from motion_runtime.plan_cache import SingleFlightCache

JOINTS = ('f1_neck_yaw', 'f1_neck_pitch', 'f2_neck_yaw', 'f2_eye_pitch')


def _write(path, frames, *, unit='rad', shuffle=False):
    header = {'type': 'motion_header', 'rotation_unit': unit, 'fields': ['frame', 'time_sec', 'id', 'value']}
    lines = [json.dumps(header)]
    order = list(range(1, frames + 1))
    if shuffle:
        # 시각이 거꾸로 · 같은 시각 두 번 · 정렬 규칙(시각 → 이름 → 줄 번호)을 건드린다
        order = order[::-1] + [3, 3]
    for n, frame in enumerate(order):
        t = round(frame * 0.02, 4)
        row = [frame, t]
        for index, joint in enumerate(JOINTS):
            row += [joint, round(0.3 * math.sin(0.7 * t + index) + n * 1e-7, 9)]
        lines.append(json.dumps(row))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _old_records(path, keep=None):
    """옛 `_parse_motion_records` (JSON Lines 길) · 레코드 사전 · 참조용"""
    content = path.read_text(encoding='utf-8')
    rows, headers, _source, _warning = motion_table.extract_rows_from_content(content)
    records = []
    for row in rows:
        record, _error = motion_table.parse_row(row, headers)
        if record is None or (keep is not None and record['motion_id'] not in keep):
            continue
        record['row_index'] = len(records)
        records.append(record)
    motion_table.scale_record_values(records, motion_table.rotation_unit_from_content(content))
    return sorted(records, key=lambda r: (r['time_sec'], str(r['motion_id']), r['row_index']))


def _bits(value):
    return struct.pack('<d', float(value)) if isinstance(value, float) else value


def _same(a, b):
    """사전 · 목록 · double 을 비트까지 · 칸 순서까지"""
    if isinstance(a, dict):
        return isinstance(b, dict) and list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and _bits(a) == _bits(b)


@pytest.mark.parametrize('unit', ['rad', 'deg'])
@pytest.mark.parametrize('shuffle', [False, True])
@pytest.mark.parametrize('keep', [None, frozenset(JOINTS[:2])])
def test_tracks_are_the_old_records(tmp_path, unit, shuffle, keep):
    path = _write(tmp_path / 'a.json', 300, unit=unit, shuffle=shuffle)
    manager = MotionRunManager.__new__(MotionRunManager)
    tracks = manager._parse_motion_records(path) if keep is None else manager._parse_motion_records(path, keep)
    old = _old_records(path, keep)
    assert isinstance(tracks, motion_tracks.MotionTracks)
    assert _same(tracks.records(), old)
    assert list(tracks.tracks) == list(motion_run_rules._motion_groups(old))


def test_whole_json_path_gives_the_same_tracks(tmp_path):
    path = tmp_path / 'whole.json'
    path.write_text(json.dumps({
        'rotation_unit': 'deg',
        'data': [[2, 0.02, 'b', 3.0], [1, 0.0, 'a', 1.0], [1, 0.0, 'b', 2.0], [2, 0.02, 'a', 4.0]],
    }), encoding='utf-8')
    tracks = MotionRunManager.__new__(MotionRunManager)._parse_motion_records(path)
    assert [r['motion_id'] for r in tracks] == ['a', 'b', 'a', 'b']
    assert tracks.tracks['a'].values.tolist() == [math.radians(1.0), math.radians(4.0)]


@pytest.mark.parametrize('start, end', [(0.5, 0.0), (0.51, 2.333), (1.0, 99.0), (0.0, 1.5)])
def test_sliced_tracks_are_the_old_sliced_records(tmp_path, start, end):
    path = _write(tmp_path / 'a.json', 200, shuffle=True)
    old = _old_records(path)
    old_sliced, old_info = motion_segment.slice_records(old, start, end)
    tracks = MotionRunManager.__new__(MotionRunManager)._parse_motion_records(path)
    cut, info = tracks.sliced(start, end)
    assert info == old_info
    old_groups = motion_run_rules._motion_groups(old_sliced)
    assert list(cut.tracks) == list(old_groups)
    for motion_id, records in old_groups.items():
        track = cut.tracks[motion_id]
        assert _same([track.record(i) for i in range(len(track))], records)


def test_slice_errors_are_the_same(tmp_path):
    tracks = MotionRunManager.__new__(MotionRunManager)._parse_motion_records(_write(tmp_path / 'a.json', 50))
    with pytest.raises(ValueError, match='구간 시작'):
        tracks.sliced(5.0, 0.0)
    with pytest.raises(ValueError, match='구간 끝'):
        tracks.sliced(0.5, 0.4)


def _old_sample_plan(axes, groups, start_time, end_time, period_sec):
    """수정 목록 164 의 `_sample_plan`(사전 레코드 · 사전 샘플) 그대로 · 참조용"""
    duration = max(end_time - start_time, 0.0)
    sample_count = max(1, int(math.floor(duration / period_sec)) + 1)
    last_time = start_time + ((sample_count - 1) * period_sec)
    if end_time - last_time > 0.001:
        sample_count += 1
    group_times = {m: [float(r['time_sec']) for r in records] for m, records in groups.items()}
    samples = []
    for index in range(sample_count):
        sample_time = min(start_time + (index * period_sec), end_time)
        positions = {}
        motion_values = {}
        for axis in axes:
            motion_id = str(axis['motion_id'])
            value = motion_run_rules._interpolated_value(groups[motion_id], group_times[motion_id], sample_time)
            value = motion_run_rules._clamp_motion_value(
                value, axis.get('motion_limit_lower_rad'), axis.get('motion_limit_upper_rad'),
            )
            target = joint_mapping.motor_target(axis['row'], value, units.RAD)
            limits = axis.get('motor_for_limits')
            positions[int(axis['motor_axis'])] = (
                motion_run_rules._clamp_to_motor_limits(target, limits) if limits else target
            )
            motion_values[motion_id] = float(value)
        samples.append({
            'time_sec': sample_time - start_time, 'absolute_time_sec': sample_time,
            'positions': positions, 'motion_values': motion_values,
        })
    return samples


def _axes():
    rows = [
        {'motion_id': JOINTS[0], 'gear_ratio': 37.0, 'scale': 1.1, 'invert': True,
         'reference_position_deg': 3.0, 'offset_deg': 1.5},
        {'motion_id': JOINTS[1], 'gear_ratio': 150.0, 'reference_position_deg': -7.25},
        {'motion_id': JOINTS[3], 'gear_ratio': 50.0, 'invert': True},
    ]
    axes = []
    for index, row in enumerate(rows):
        axes.append({
            'motion_id': row['motion_id'], 'motor_axis': index, 'row': row,
            'motion_limit_lower_rad': math.radians(-12.0) if index == 0 else None,
            'motion_limit_upper_rad': math.radians(12.0) if index == 0 else None,
            # 첫 축은 모터 한계를 범위 끝 근처에 · 자르기가 실제로 일어나게
            'motor_for_limits': {'lower_rad': -1e9, 'upper_rad': 1e9} if index else {
                'lower_rad': joint_mapping.motor_target(row, math.radians(-12.0), units.RAD) - 1e-9,
                'upper_rad': joint_mapping.motor_target(row, math.radians(12.0), units.RAD) + 1e-9,
            },
        })
    return axes


@pytest.mark.parametrize('segment', [None, (0.33, 3.217)])
def test_packed_samples_are_bit_identical_to_the_old_dict_samples(tmp_path, segment):
    path = _write(tmp_path / 'a.json', 400, shuffle=True)
    old = _old_records(path)
    tracks = MotionRunManager.__new__(MotionRunManager)._parse_motion_records(path)
    if segment:
        old, _ = motion_segment.slice_records(old, *segment)
        tracks, _ = tracks.sliced(*segment)
    old_groups = motion_run_rules._motion_groups(old)
    start = min(r['time_sec'] for r in old)
    end = max(r['time_sec'] for r in old)
    assert start == tracks.start_time() and end == tracks.end_time()

    axes = _axes()
    expected = _old_sample_plan(axes, old_groups, start, end, 0.02)
    samples, error = _sample_plan(axes, tracks.tracks, start, end, 0.02)
    assert error == ''
    assert isinstance(samples, PackedSamples)
    assert len(samples) == len(expected)
    assert _same(list(samples), expected)
    assert _same(samples[-1], expected[-1]) and _same(samples[3:6], expected[3:6])
    assert samples == expected
    assert samples.time_column().tolist() == [s['time_sec'] for s in expected]
    assert samples.motion_column(JOINTS[1]).tolist() == [s['motion_values'][JOINTS[1]] for s in expected]


def test_a_taken_sample_can_be_changed_without_touching_the_plan():
    samples = PackedSamples([0], ['a'])
    samples.append(0.0, 10.0, [1.5], [0.5])
    sample = samples[0]
    sample['positions'][0] = 99.0
    assert samples[0]['positions'] == {0: 1.5}


def test_compact_sizes(tmp_path):
    tracks = MotionRunManager.__new__(MotionRunManager)._parse_motion_records(_write(tmp_path / 'a.json', 100))
    assert tracks.nbytes == 32 * len(tracks) == 32 * 100 * len(JOINTS)
    samples = PackedSamples([0, 1, 2], ['a', 'b', 'c'])
    for index in range(10):
        samples.append(index * 0.02, index * 0.02, [0.0] * 3, [0.0] * 3)
    assert samples.nbytes == 10 * (2 + 3 * 2) * 8


class _Blob:
    def __init__(self, nbytes):
        self.nbytes = nbytes


def test_cache_drops_the_oldest_over_the_byte_budget():
    cache = SingleFlightCache(10, max_bytes=100)
    for key in 'abc':
        cache.get_or_compute(key, lambda: _Blob(40))
    assert cache.keys() == ['b', 'c'] and cache.nbytes == 80
    # 예산보다 큰 것 하나는 남긴다 · 바로 쓸 것이라
    big = cache.get_or_compute('d', lambda: _Blob(500))
    assert cache.keys() == ['d'] and big.nbytes == 500
    # 튜플 값은 칸마다 더한다(레코드 단계 캐시 · (배열, 정보))
    cache.get_or_compute('e', lambda: (_Blob(30), {'x': 1}))
    assert cache.keys() == ['e'] and cache.nbytes == 30


def test_count_bound_still_holds_without_a_byte_budget():
    cache = SingleFlightCache(2)
    for key in 'abc':
        cache.get_or_compute(key, lambda: _Blob(10 ** 9))
    assert cache.keys() == ['b', 'c']
