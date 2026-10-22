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
         'ratio': 50, 'range_deg': [-12, 12], 'servo_bw_hz': 12},
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
    assert any('ratio 40 ≠ 카탈로그 PGX44-H 50' in w for w in report.warnings)


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


def test_hand_placed_pack_is_hashed_once_until_a_file_changes(tmp_path, monkeypatch):
    """손으로 놓은 팩 · 목록 파일마다 메쉬까지 다시 읽던 것 → 1회 · 수정 목록 5-4."""
    pack = make_pack(tmp_path / 'p')
    calls = []
    real = robot_pack.pack_fingerprint
    monkeypatch.setattr(robot_pack, 'pack_fingerprint', lambda p: calls.append(p) or real(p))
    robot_pack._FINGERPRINT_CACHE.clear()

    first = robot_pack.current_fingerprint(pack)
    assert robot_pack.current_fingerprint(pack) == first
    assert robot_pack.current_fingerprint(pack) == first
    assert len(calls) == 1

    model = pack / 'model.xml'
    model.write_text(model.read_text(encoding='utf-8') + '<!-- changed -->', encoding='utf-8')
    # 서명은 크기·수정시각 · 여기선 크기가 바뀌었다 (같은 크기면 mtime 이 잡는다)
    assert robot_pack.current_fingerprint(pack) != first
    assert len(calls) == 2


def test_current_fingerprint_prefers_install_record(tmp_path):
    pack = make_pack(tmp_path / 'p')
    assert robot_pack.current_fingerprint(pack) == robot_pack.pack_fingerprint(pack)
    (pack / robot_pack.INSTALLED_NAME).write_text('{"fingerprint": "abc"}', encoding='utf-8')
    assert robot_pack.current_fingerprint(pack) == 'abc'
    assert robot_pack.current_fingerprint(tmp_path / 'none') == ''


# --------------------------------------------------------------------------- #
# 선택 파일 scene.glb · 웹 3D 「Blender 뷰」 · 수정 목록 50
# --------------------------------------------------------------------------- #

def _glb(json_bytes=b'{"asset":{"version":"2.0"}}', *, version=2, length=None):
    import struct
    pad = (4 - len(json_bytes) % 4) % 4
    chunk = json_bytes + b' ' * pad
    total = 12 + 8 + len(chunk)
    return (b'glTF' + struct.pack('<II', version, total if length is None else length)
            + struct.pack('<I', len(chunk)) + b'JSON' + chunk)


def test_scene_glb_is_optional_and_checked_when_present(tmp_path):
    pack = make_pack(tmp_path / 'p')
    assert robot_pack.scene_glb_path(pack) is None
    assert robot_pack.validate_pack_dir(pack) == []
    (pack / 'scene.glb').write_bytes(_glb())
    assert robot_pack.scene_glb_path(pack) == pack / 'scene.glb'
    assert robot_pack.validate_pack_dir(pack) == []


def test_scene_glb_must_be_a_whole_gltf2_binary(tmp_path):
    pack = make_pack(tmp_path / 'p')
    (pack / 'scene.glb').write_bytes(b'{"asset":{}}')
    assert 'glTF 바이너리(.glb)가 아닙니다' in '\n'.join(robot_pack.validate_pack_dir(pack))
    (pack / 'scene.glb').write_bytes(_glb(version=1))
    assert 'glTF 버전 1' in '\n'.join(robot_pack.validate_pack_dir(pack))
    (pack / 'scene.glb').write_bytes(_glb(length=999))
    assert '파일이 잘렸습니다' in '\n'.join(robot_pack.validate_pack_dir(pack))


def test_scene_glb_size_limit_keeps_the_pack_under_the_zip_limit(tmp_path, monkeypatch):
    pack = make_pack(tmp_path / 'p')
    (pack / 'scene.glb').write_bytes(_glb())
    monkeypatch.setattr(robot_pack, 'SCENE_GLB_MAX_BYTES', 10)
    assert '크기 초과' in '\n'.join(robot_pack.validate_pack_dir(pack))
    assert robot_pack.SCENE_GLB_NAME == 'scene.glb'


# scene_glb.joints · 애니메이션 json 값으로 노드 돌리기 · 수정 목록 98
# --------------------------------------------------------------------------- #

def _joint_pack(tmp_path, joints, *, nodes=('f1_neck_yaw', 'f1_neck_pitch'), animations=0):
    import json as _json
    document = {'asset': {'version': '2.0'}, 'nodes': [{'name': name} for name in nodes]}
    if animations:
        document['animations'] = [{'channels': [], 'samplers': []}] * animations
    pack = make_pack(tmp_path / 'p', pack={'name': 'demo', 'version': '1.0', 'created': '2026-10-12',
                                           'scene_glb': {'joints': joints}})
    (pack / 'scene.glb').write_bytes(_glb(_json.dumps(document).encode()))
    return pack


def test_scene_glb_joints_are_read_and_axis_is_normalized(tmp_path):
    pack = _joint_pack(tmp_path, {'f1_neck_yaw': {'node': 'f1_neck_yaw', 'axis': [0, 0, 2]},
                                  'f1_neck_pitch': {'node': 'f1_neck_pitch', 'axis': [1, 0, 0]}})
    report = robot_pack.inspect_pack(pack)
    assert report.errors == []
    assert not any('scene_glb' in w for w in report.warnings), report.warnings
    joints = robot_pack.scene_glb_joints(pack)
    assert joints['f1_neck_yaw'] == {'node': 'f1_neck_yaw', 'axis': [0.0, 0.0, 1.0]}
    assert robot_pack.glb_info(pack / 'scene.glb')['nodes'] == ['f1_neck_yaw', 'f1_neck_pitch']


def test_scene_glb_joints_missing_node_and_bad_axis_are_errors(tmp_path):
    pack = _joint_pack(tmp_path, {'f1_neck_yaw': {'node': 'no_such_node', 'axis': [0, 1, 0]},
                                  'f1_neck_pitch': {'node': 'f1_neck_pitch', 'axis': [0, 0, 0]},
                                  'f1_eye': {'axis': [1, 0, 0]}})
    errors = '\n'.join(robot_pack.validate_pack_dir(pack))
    assert "노드 'no_such_node' 가 scene.glb 에 없습니다" in errors
    assert 'f1_neck_pitch · axis 는 길이 0 이 아닌 숫자 3개' in errors
    assert 'f1_eye · node(glb 노드 이름) 필요' in errors
    # 모양이 틀린 줄만 뺀다 · 노드 없음은 팩 검사가 오류로 거절해 깔리지 않는다
    assert set(robot_pack.scene_glb_joints(pack)) == {'f1_neck_yaw'}


def test_scene_glb_baked_clips_are_only_a_warning_in_joint_mode(tmp_path):
    pack = _joint_pack(tmp_path, {'f1_neck_yaw': {'node': 'f1_neck_yaw', 'axis': [0, 0, 1]}}, animations=2)
    report = robot_pack.inspect_pack(pack)
    assert report.errors == []
    assert any('애니메이션 2개 · joints 방식에서는 쓰지 않습니다' in w for w in report.warnings)


def test_scene_glb_without_joints_or_animations_warns(tmp_path):
    pack = make_pack(tmp_path / 'p')
    (pack / 'scene.glb').write_bytes(_glb())
    report = robot_pack.inspect_pack(pack)
    assert any('scene_glb.joints 도 derived 도 없음' in w for w in report.warnings)
    assert robot_pack.scene_glb_joints(pack) == {}


# scene_glb.derived · 파생 관절 표 · 수정 목록 159
# --------------------------------------------------------------------------- #

def _b64(values):
    import base64
    import struct
    return base64.b64encode(struct.pack('<%df' % len(values), *values)).decode()


def _identity_trs(points, nodes):
    return [0, 0, 0, 0, 0, 0, 1, 1, 1, 1] * (points * nodes)


def _derived_pack(tmp_path, tables, *, joints=None, nodes=('Neck', 'Rod_L', 'f1_neck_yaw'), derived='derived.json',
                  extra=None):
    import json as _json
    document = {'asset': {'version': '2.0'}, 'nodes': [{'name': name} for name in nodes]}
    scene = {'derived': derived}
    if joints:
        scene['joints'] = joints
    if extra:
        scene.update(extra)
    pack = make_pack(tmp_path / 'p', pack={'name': 'chicken', 'version': '1.0', 'created': '2026-10-22', 'scene_glb': scene})
    (pack / 'scene.glb').write_bytes(_glb(_json.dumps(document).encode()))
    (pack / 'derived.json').write_text(_json.dumps({'version': 1, 'tables': tables}), encoding='utf-8')
    return pack


def _table(inputs=('c1', 'c2'), n=(3, 2), nodes=('Neck', 'Rod_L'), channels='trs', values=None):
    width = 10 if channels == 'trs' else 4
    points = 1
    for count in n:
        points *= count
    if values is None:
        values = _identity_trs(points, len(nodes)) if channels == 'trs' else [0, 0, 0, 1] * (points * len(nodes))
    return {'inputs': list(inputs), 'grid': [{'min': -0.5, 'max': 0.5, 'n': count} for count in n],
            'nodes': list(nodes), 'channels': channels, 'values_b64': _b64(values)}


def test_scene_glb_derived_table_passes_and_turns_the_blender_view_on(tmp_path):
    pack = _derived_pack(tmp_path, [_table(), _table(inputs=('c3',), n=(4,), nodes=('f1_neck_yaw',), channels='r')])
    report = robot_pack.inspect_pack(pack)
    assert report.errors == []
    assert not any('scene_glb' in w for w in report.warnings), report.warnings
    assert robot_pack.scene_glb_derived_path(pack) == pack / 'derived.json'


def test_scene_glb_derived_rejects_bad_tables(tmp_path):
    cases = [
        (_table(values=[0.0] * 5), '값 개수 5 · 필요 120 (격자 6 × 노드 2 × 채널 10)'),
        (_table(inputs=('c1', 'c2', 'c3', 'c4'), n=(2, 2, 2, 2)), 'inputs 는 조인트 이름 1~3개'),
        (_table(inputs=('c1', 'c1')), 'inputs 중복'),
        (_table(n=(1, 2)), 'n 은 2 이상 정수'),
        (_table(channels='xyz'), 'channels 는 "trs" 또는 "r"'),
        (_table(nodes=('Nope',)), "노드 'Nope' 가 scene.glb 에 없습니다"),
        (_table(values=[0, 0, 0, 0, 0, 0, 0, 1, 1, 1] * 12), '길이 0 인 쿼터니언'),
        (_table(values=[float('nan')] + [0] * 119), 'NaN · Inf'),
    ]
    for index, (table, message) in enumerate(cases):
        pack = _derived_pack(tmp_path / str(index), [table])
        errors = '\n'.join(robot_pack.validate_pack_dir(pack))
        assert message in errors, (message, errors)


def test_scene_glb_derived_node_belongs_to_one_place_only(tmp_path):
    pack = _derived_pack(tmp_path / 'a', [_table(), _table(inputs=('c3',), n=(2,), nodes=('Neck',))])
    assert "노드 'Neck' 가 tables[0] 에도 있음" in '\n'.join(robot_pack.validate_pack_dir(pack))
    pack = _derived_pack(tmp_path / 'b', [_table()], joints={'c9': {'node': 'Neck', 'axis': [1, 0, 0]}})
    assert "노드 'Neck' 가 scene_glb.joints 에도 있음" in '\n'.join(robot_pack.validate_pack_dir(pack))


def test_scene_glb_derived_path_must_stay_inside_the_pack(tmp_path):
    for index, path in enumerate(('../derived.json', '/abs/derived.json', 'C:/x.json', 'missing.json')):
        pack = _derived_pack(tmp_path / str(index), [_table()], derived=path)
        errors = '\n'.join(robot_pack.validate_pack_dir(pack))
        assert 'scene_glb.derived' in errors, (path, errors)
        assert robot_pack.scene_glb_derived_path(pack) is None


def test_scene_glb_derived_size_limit(tmp_path, monkeypatch):
    pack = _derived_pack(tmp_path, [_table()])
    monkeypatch.setattr(robot_pack, 'DERIVED_MAX_BYTES', 10)
    assert '크기 초과' in '\n'.join(robot_pack.validate_pack_dir(pack))


def test_scene_glb_old_animations_key_is_ignored_with_a_warning(tmp_path):
    pack = _derived_pack(tmp_path, [_table()], extra={'animations': ['floating_narration_all']})
    report = robot_pack.inspect_pack(pack)
    assert report.errors == []
    assert any('scene_glb.animations 는 더 이상 쓰지 않습니다' in w for w in report.warnings)
    assert not hasattr(robot_pack, 'scene_glb_animations')

