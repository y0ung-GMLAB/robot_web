"""구간 재생 · 낱말의 주인 · 요청 읽기 · 줄 자르기 (2026-10-16)"""

import pytest

from motion_common import motion_segment


def _records(times, values, motion_id='1-1', **extra):
    return [
        {'motion_id': motion_id, 'time_sec': t, 'value': v, 'frame': index + 1, **extra}
        for index, (t, v) in enumerate(zip(times, values))
    ]


def test_time_text_matches_the_screen():
    assert motion_segment.format_time(80) == '1:20'
    assert motion_segment.format_time(80.5) == '1:20.5'
    assert motion_segment.format_time(0) == '0:00'
    assert motion_segment.format_time(None) == '-'
    assert motion_segment.label(80, 105) == '구간 1:20~1:45'
    assert motion_segment.label(80, 0) == '구간 1:20~끝'
    assert motion_segment.label(0, 0) == ''


def test_parse_reads_the_screen_shape_and_the_inner_shape():
    assert motion_segment.parse({}) == (0.0, 0.0)
    assert motion_segment.parse(None) == (0.0, 0.0)
    assert motion_segment.parse({'segment': {'start_sec': 80, 'end_sec': 105}}) == (80.0, 105.0)
    assert motion_segment.parse({'segment': {'start_sec': '', 'end_sec': None}}) == (0.0, 0.0)
    assert motion_segment.parse({'segment_start_sec': 1.5, 'segment_end_sec': 0}) == (1.5, 0.0)
    assert motion_segment.parse({'segment': None, 'segment_start_sec': 2}) == (2.0, 0.0)


@pytest.mark.parametrize('payload, words', [
    ({'segment_start_sec': -1}, '0초 이상'),
    ({'segment_end_sec': 'abc'}, '숫자가 아닙니다'),
    ({'segment_start_sec': float('nan')}, '숫자가 아닙니다'),
    ({'segment_start_sec': True}, '숫자가 아닙니다'),
    ({'segment': {'start_sec': 80, 'end_sec': 70}}, '구간 끝 1:10 이 구간 시작 1:20 보다 뒤여야 합니다'),
    ({'segment': {'start_sec': 80, 'end_sec': 80}}, '보다 뒤여야'),
    ({'segment': 'oops'}, '{start_sec, end_sec}'),
    ({'segment_start_sec': 10 ** 7}, '너무 깁니다'),
])
def test_parse_refuses_with_a_reason(payload, words):
    with pytest.raises(ValueError, match=words.replace('{', r'\{').replace('}', r'\}')):
        motion_segment.parse(payload)


def test_apply_to_payload_flattens_and_schedule_is_always_whole():
    out = motion_segment.apply_to_payload({'a': 1, 'segment': {'start_sec': 3, 'end_sec': 9}})
    assert out == {'a': 1, 'segment_start_sec': 3.0, 'segment_end_sec': 9.0}
    whole = motion_segment.apply_to_payload({'segment': {'start_sec': 3}}, allowed=False)
    assert whole == {'segment_start_sec': 0.0, 'segment_end_sec': 0.0}
    assert motion_segment.is_active(3, 0) and motion_segment.is_active(0, 9)
    assert not motion_segment.is_active(0, 0) and not motion_segment.is_active(None, None)


def test_slice_interpolates_the_first_and_last_frame_and_restarts_at_zero():
    # 0.02 s 칸 · 값 = 시각 × 10 (선형) · 파일이 0.02 에서 시작해도 첫 줄이 0
    times = [0.02 + 0.02 * index for index in range(101)]   # 0.02 ~ 2.02 · 길이 2.0
    records = _records(times, [t * 10.0 for t in times])
    sliced, info = motion_segment.slice_records(records, 0.51, 1.25)

    assert info == {
        'source_duration_sec': pytest.approx(2.0),
        'segment_start_sec': 0.51, 'segment_end_sec': 1.25, 'end_clamped': False,
    }
    assert sliced[0]['time_sec'] == 0.0
    assert sliced[0]['value'] == pytest.approx((0.02 + 0.51) * 10.0)
    assert sliced[-1]['time_sec'] == pytest.approx(0.74)
    assert sliced[-1]['value'] == pytest.approx((0.02 + 1.25) * 10.0)
    inner = sliced[1:-1]
    assert all(0.0 < r['time_sec'] < 0.74 for r in inner)
    assert all(r['value'] == pytest.approx((r['time_sec'] + 0.53) * 10.0) for r in inner)
    assert [r['time_sec'] for r in sliced] == sorted(r['time_sec'] for r in sliced)
    assert sliced[0]['motion_id'] == '1-1'
    # 원본은 그대로
    assert records[0]['time_sec'] == 0.02


def test_slice_to_the_end_and_end_longer_than_the_file():
    records = _records([0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    to_end, info = motion_segment.slice_records(records, 0.5, 0.0)
    assert info['segment_end_sec'] == pytest.approx(2.0) and not info['end_clamped']
    assert [(r['time_sec'], r['value']) for r in to_end] == [(0.0, 0.5), (0.5, 1.0), (1.5, 0.0)]

    longer, info = motion_segment.slice_records(records, 0.5, 9.0)
    assert info['end_clamped'] is True
    assert info['segment_end_sec'] == pytest.approx(2.0)
    assert longer == to_end


def test_slice_keeps_every_joint_and_holds_a_joint_that_ends_early():
    records = (
        _records([0.0, 1.0, 2.0], [0.0, 1.0, 2.0], motion_id='a')
        + _records([0.0, 0.5], [5.0, 6.0], motion_id='b')   # 0.5 s 에서 끝난 축 · 끝값 유지(재생 보간과 같음)
    )
    sliced, _ = motion_segment.slice_records(records, 1.0, 1.5)
    b = [r for r in sliced if r['motion_id'] == 'b']
    assert [(r['time_sec'], r['value']) for r in b] == [(0.0, 6.0), (0.5, 6.0)]
    a = [r for r in sliced if r['motion_id'] == 'a']
    assert [(r['time_sec'], r['value']) for r in a] == [(0.0, 1.0), (0.5, 1.5)]


@pytest.mark.parametrize('start, end, words', [
    (192.0, 0.0, '구간 시작 3:12 이 애니메이션 길이 2:40 보다 깁니다'),
    (160.0, 0.0, '구간 시작 2:40 이 애니메이션 길이 2:40 보다 깁니다'),
    (100.0, 90.0, '구간 끝 1:30 이 구간 시작 1:40 보다 뒤여야 합니다'),
])
def test_slice_refuses(start, end, words):
    records = _records([0.0, 160.0], [0.0, 1.0])
    with pytest.raises(ValueError, match=words):
        motion_segment.slice_records(records, start, end)
