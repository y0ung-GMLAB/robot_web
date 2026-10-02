"""로봇 팩 형식 · 웹 업로드 검사와 sim 실행기가 같은 검사를 쓴다

오류 = 교체 거부 · 경고 = 표시만 · 모델 로드(MuJoCo)는 여기 몫이 아니다.
"""

import shutil
from pathlib import Path

import yaml

from motion_common import robot_pack

WORKSPACE = Path(__file__).resolve().parents[3]
CATALOG = WORKSPACE / 'catalog'

ROBOT = {
    'axes': [
        {'joint': 'neck_pitch', 'motion_id': '2-1', 'motor': 'MSMF082L1T2', 'reducer': 'KHY-90-2-RV',
         'ratio': 150, 'range_deg': [-10, 13], 'servo_bw_hz': 5},
        {'joint': 'eye_yaw_l', 'motion_id': '2-4', 'motor': 'MSMF5AZL1', 'reducer': 'PGX44-H',
         'ratio': 35, 'range_deg': [-12, 12], 'servo_bw_hz': 12},
    ],
    'drive': {'profile_velocity_deg_s': 18000, 'profile_accel_deg_s2': 180000},
    'env': {
        'settle_body': 'base', 'settle_s': 10, 'torsion_k': 500, 'torsion_c': 150,
        'camera': {'lookat': [0, -0.2, 3.5], 'distance': 5.5, 'azimuth': -60, 'elevation': -5},
    },
}


def make_pack(root: Path, robot=None, *, pack=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pack.yaml').write_text(yaml.safe_dump(
        pack or {'name': 'demo', 'version': '1.0', 'created': '2026-10-02'}), encoding='utf-8')
    (root / 'robot.yaml').write_text(yaml.safe_dump(robot or ROBOT), encoding='utf-8')
    (root / 'model.xml').write_text('<mujoco/>', encoding='utf-8')
    shutil.copytree(CATALOG, root / 'catalog')
    return root


def _robot(**changes):
    robot = yaml.safe_load(yaml.safe_dump(ROBOT))
    for key, value in changes.items():
        robot[key] = value
    return robot


def test_stack_catalog_is_valid():
    motors, reducers, errors = robot_pack.load_catalog(CATALOG)
    assert errors == []
    assert {'MSMF082L1T2', 'MSMF011L1', 'MSMF5AZL1'} <= set(motors)
    assert {'KHY-90-2-RV', 'KSD-90-2', 'KHY55-R44V', 'PGX44-H'} <= set(reducers)


def test_unknown_motor_type_is_refused():
    errors = robot_pack.validate_catalog({'X': {'type': 'stepper'}}, {})
    assert any('type 알 수 없음' in e for e in errors)


def test_dynamixel_needs_only_its_own_fields():
    motors = {'XM430': {'type': 'dynamixel', 'max_rpm': 46, 'stall_torque_nm': 4.1}}
    assert robot_pack.validate_catalog(motors, {}) == []


def test_good_pack_passes_and_loads(tmp_path):
    pack = make_pack(tmp_path / 'p')
    report = robot_pack.inspect_pack(pack)
    assert report.errors == [] and report.warnings == []
    robot = robot_pack.load_robot(pack)
    assert [a.joint for a in robot.axes] == ['neck_pitch', 'eye_yaw_l']
    assert robot.axes[0].reducer_spec['t2n_nm'] == 95
    assert robot.settle_body == 'base' and robot.version == '1.0'


def test_missing_files_are_named(tmp_path):
    pack = make_pack(tmp_path / 'p')
    (pack / 'model.xml').unlink()
    assert robot_pack.validate_pack_dir(pack) == ['model.xml · 파일 없음']


def test_pack_must_carry_its_catalog(tmp_path):
    pack = make_pack(tmp_path / 'p')
    shutil.rmtree(pack / 'catalog')
    errors = robot_pack.validate_pack_dir(pack)
    assert 'catalog/motors.yaml · 파일 없음' in errors
    assert any('팩 catalog/motors.yaml 에 없음' in e for e in errors)


def test_axis_errors_are_all_reported(tmp_path):
    axes = [
        dict(ROBOT['axes'][0], motor='NOPE'),
        dict(ROBOT['axes'][0], range_deg=[5, 5]),        # joint·motion_id 중복 + 범위
        dict(ROBOT['axes'][1], ratio=0, servo_bw_hz='fast'),
    ]
    errors = robot_pack.validate_pack_dir(make_pack(tmp_path / 'p', _robot(axes=axes)))
    text = '\n'.join(errors)
    for expected in ('motor · 팩 catalog/motors.yaml 에 없음', 'joint 중복', 'motion_id 중복',
                     '최소 < 최대', 'ratio · 0보다 커야 함', 'servo_bw_hz · 숫자 필요'):
        assert expected in text


def test_ratio_differing_from_catalog_is_only_a_warning(tmp_path):
    axes = [dict(ROBOT['axes'][1], ratio=40)]
    report = robot_pack.inspect_pack(make_pack(tmp_path / 'p', _robot(axes=axes)))
    assert report.errors == []
    assert any('ratio 40 ≠ 카탈로그 PGX44-H 35' in w for w in report.warnings)


def test_axis_without_reducer_is_allowed(tmp_path):
    axes = [dict(ROBOT['axes'][1], reducer=None, ratio=1)]
    robot = robot_pack.load_robot(make_pack(tmp_path / 'p', _robot(axes=axes)))
    assert robot.axes[0].reducer is None and robot.axes[0].reducer_spec == {}


def test_drive_and_env_are_required(tmp_path):
    robot = _robot(drive={'profile_velocity_deg_s': -1}, env={'settle_body': 'base'})
    text = '\n'.join(robot_pack.validate_pack_dir(make_pack(tmp_path / 'p', robot)))
    assert 'profile_velocity_deg_s · 0보다 커야 함' in text
    assert 'profile_accel_deg_s2 · 숫자 필요' in text
    assert 'settle_s · 숫자 필요' in text
    assert 'camera · 표 필요' in text


def test_load_robot_raises_with_every_reason(tmp_path):
    pack = make_pack(tmp_path / 'p', pack={'name': 'x'})
    try:
        robot_pack.load_robot(pack)
    except ValueError as exc:
        assert 'pack.yaml · version · 값 필요' in str(exc)
        assert 'pack.yaml · created · 값 필요' in str(exc)
    else:
        raise AssertionError('오류 팩이 통과했다')


def test_fingerprint_follows_content_not_install_record(tmp_path):
    pack = make_pack(tmp_path / 'p')
    first = robot_pack.pack_fingerprint(pack)
    (pack / robot_pack.INSTALLED_NAME).write_text('{"uploaded_at": "now"}', encoding='utf-8')
    assert robot_pack.pack_fingerprint(pack) == first
    (pack / 'model.xml').write_text('<mujoco model="b"/>', encoding='utf-8')
    assert robot_pack.pack_fingerprint(pack) != first


def test_current_fingerprint_prefers_install_record(tmp_path):
    pack = make_pack(tmp_path / 'p')
    assert robot_pack.current_fingerprint(pack) == robot_pack.pack_fingerprint(pack)
    (pack / robot_pack.INSTALLED_NAME).write_text('{"fingerprint": "abc"}', encoding='utf-8')
    assert robot_pack.current_fingerprint(pack) == 'abc'
    assert robot_pack.current_fingerprint(tmp_path / 'none') == ''
