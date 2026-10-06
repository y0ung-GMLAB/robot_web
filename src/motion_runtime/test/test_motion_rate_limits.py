"""조인트 최대 속도·가속도 · 넘는 애니메이션은 재생 거부 · 수정 목록 5-2 (2026-10-06)"""

from motion_runtime.plan_builder import _motion_rate_limit_error


def _samples(values, period=0.02):
    return [
        {'time_sec': index * period, 'motion_values': {'Neck_Yaw': value}}
        for index, value in enumerate(values)
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
