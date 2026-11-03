"""조인트 최대 속도·가속도 · 넘는 애니메이션은 재생 거부 · 수정 목록 5-2 (2026-10-06)"""

import math

from motion_runtime.plan_builder import _motion_rate_limit_error


def _samples(values_deg, period=0.02):
    """재생 계획의 조인트 값은 rad · 읽기 쉽게 deg 로 적고 바꿔 넣는다 · 수정 목록 6"""
    return [
        {'time_sec': index * period, 'motion_values': {'Neck_Yaw': math.radians(value)}}
        for index, value in enumerate(values_deg)
    ]


def _axis(**limits):
    return [{'motion_id': 'Neck_Yaw', 'row': dict(limits)}]


def test_no_limits_means_no_check():
    assert _motion_rate_limit_error(_axis(), _samples([0, 100, 0]), 0.02) == ''


def test_velocity_over_the_limit_is_refused_with_time_and_value():
    # 0.02 s 에 1° = 50 deg/s
    error = _motion_rate_limit_error(_axis(max_velocity_deg_s=40), _samples([0, 0, 1, 2]), 0.02)
    assert 'Neck_Yaw 속도 50.0 deg/s > 상한 40' in error
    assert _motion_rate_limit_error(_axis(max_velocity_deg_s=50), _samples([0, 0, 1, 2]), 0.02) == ''


def test_acceleration_over_the_limit_is_refused():
    # 정지 → 50 deg/s 로 0.02 s 만에 = 2500 deg/s²
    error = _motion_rate_limit_error(_axis(max_acceleration_deg_s2=1000), _samples([0, 0, 1, 2]), 0.02)
    assert '가속도 2500 deg/s² > 상한 1000' in error
    assert _motion_rate_limit_error(_axis(max_acceleration_deg_s2=3000), _samples([0, 0, 1, 2]), 0.02) == ''


def test_rad_limits_from_a_new_mapping_file_give_the_same_answer():
    """새 매핑 파일은 rad/s 로 적는다 · 같은 상한이면 같은 판정"""
    samples = _samples([0, 0, 1, 2])
    error = _motion_rate_limit_error(_axis(max_velocity_rad_s=math.radians(40)), samples, 0.02)
    assert 'Neck_Yaw 속도 50.0 deg/s > 상한 40' in error
    assert _motion_rate_limit_error(_axis(max_velocity_rad_s=math.radians(50)), samples, 0.02) == ''


# -- 수정 목록 168 · 매핑 범위로 잘려서 튄 가속도는 그렇다고 말한다 ---------------------------- #
#   실물 2026-11-02 NY · f2_neck_yaw 애니 최소 −15.82° · 매핑 범위 ±15 → 자른 자리에서 21 deg/s² ·
#   원래 애니는 8.9 · 「애니가 너무 빠르다」 로 읽혀 엉뚱한 곳을 고쳤다

def _clipped_axis(values_deg, lower=-15.0, upper=15.0, **limits):
    """재생 계획이 싣는 칸 그대로 · 범위로 자른 값을 재고 자르기 전 최소·최대를 같이 싣는다"""
    clipped = [min(max(value, lower), upper) for value in values_deg]
    axis = [{
        'motion_id': 'Neck_Yaw', 'row': dict(limits),
        'motion_limit_lower_rad': math.radians(lower), 'motion_limit_upper_rad': math.radians(upper),
        'source_motion_min_rad': math.radians(min(values_deg)), 'source_motion_max_rad': math.radians(max(values_deg)),
    }]
    samples = [
        {'time_sec': index * 0.02, 'motion_values': {'Neck_Yaw': math.radians(value)}}
        for index, value in enumerate(clipped)
    ]
    # 범위 끝값은 rad 로 바꾼 값이 정확히 같아야 한다(재생 계획은 rad 범위로 자른다)
    for sample, value in zip(samples, clipped):
        if value == lower:
            sample['motion_values']['Neck_Yaw'] = math.radians(lower)
        if value == upper:
            sample['motion_values']['Neck_Yaw'] = math.radians(upper)
    return axis, samples


def test_a_spike_made_by_the_mapping_range_says_so():
    # −5 deg/s 로 꾸준히 내려가 −15.9 까지 · 원래 가속도 0 · −15 에서 잘려 0.02 s 만에 멈춤 = 250 deg/s²
    values = [-14.0 - 0.1 * index for index in range(20)]
    axis, samples = _clipped_axis(values, max_acceleration_deg_s2=14)
    error = _motion_rate_limit_error(axis, samples, 0.02)
    assert 'Neck_Yaw 가속도 250 deg/s² > 상한 14' in error, error
    assert '매핑 범위(−15~15°)에서 잘린 곳 · 애니가 범위를 넘음(최소 −15.9°)' in error, error


def test_a_real_spike_inside_the_range_gets_no_range_hint():
    # 위 끝(15)에서 잘린 곳도 있지만(꺾임 125 deg/s²) 가장 나쁜 곳은 범위 안의 진짜 튐(2500)
    values = [14.90, 14.95, 15.0, 15.05, 15.10, 15.0, 14.98, 14.96, 14.94, 14.94, 13.94, 12.94]
    axis, samples = _clipped_axis(values, max_acceleration_deg_s2=1000)
    error = _motion_rate_limit_error(axis, samples, 0.02)
    assert 'Neck_Yaw 가속도 2500 deg/s² > 상한 1000' in error, error
    assert '매핑 범위' not in error
    # 상한을 낮춰 잘린 곳(125)만 넘게 하면 그때는 범위 이야기
    error = _motion_rate_limit_error(_clipped_axis(values[:9], max_acceleration_deg_s2=100)[0],
                                     _clipped_axis(values[:9])[1], 0.02)
    assert '가속도 125 deg/s² > 상한 100' in error and '애니가 범위를 넘음(최대 15.1°)' in error, error


def test_no_range_info_means_the_old_message():
    """X-Touch 녹화 검사는 범위 칸 없이 부른다 · 글은 예전 그대로"""
    error = _motion_rate_limit_error(_axis(max_acceleration_deg_s2=1000), _samples([0, 0, 1, 2]), 0.02)
    assert error.endswith('Neck_Yaw 가속도 2500 deg/s² > 상한 1000 (0.04 s)')
