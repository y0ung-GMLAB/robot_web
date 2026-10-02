"""조인트 매핑 저장 → 모터 설정 파일 lower/upper · 저장 경로 전부 (2026-10-02).

사용자 보고 · 조인트 매핑 편집에서 최소·최대를 바꿔도 모터 설정(드라이브
soft limit)에 안 갔다 · 이제 매핑이 원본이고 모터 설정 저장(모터 목록 ·
원본 텍스트)과 매핑 저장 둘 다 매핑 환산값으로 맞춘다.
"""

import yaml

from motion_web_bridge import motor_config_rules
from motion_web_bridge.bridge_node import MotionWebBridge
from motion_web_bridge.project_repository import ProjectRepository

from test_project_repository import _motor_config_of

CONFIG = yaml.safe_load(
    'period: 1000000\nmasters:\n- id: 0\n  type: ethercat\n  ethercat_master_index: 0\n  slaves:\n'
    '  - controller_index: 0\n    driver_id: 0\n    alias: 101\n    position: 0\n'
    '    ring_position: 0\n    vendor_id: 1647\n    product_id: 1614282756\n'
    'web_axis_identities:\n- controller_index: 0\n  eeprom_alias: 101\n'
    '  slave_position: 0\n  vendor_id: 1647\n  product_id: 1614282756\n'
    '  revision_number: 65536\n  serial_number: 123456\n'
    '  identity_source: physical_sii\n'
    'web_axis_profiles:\n- controller_index: 0\n  driver_model: MADLN05BE\n'
    '  model_confirmed: true\n  model_source: user_nameplate\n'
    'drivers:\n- id: 0\n  type: minas\n  driver_model: MADLN05BE\n'
    '  lower: -36000.0\n  upper: 36000.0\n'
    '  profile_velocity: 18000\n  profile_acceleration: 180000\n'
    '  profile_deceleration: 180000\n'
)

MAPPING = {
    'name': 'neck',
    'mappings': [{
        'motion_id': 'Neck_Pitch', 'enabled': True,
        'motor_ref': 'ac_servo:master:0:alias:101', 'motor_axis': 0,
        'reference_enabled': True, 'reference_position_deg': 0.0,
        'motion_lower_deg': -10.0, 'motion_upper_deg': 13.0,
        'invert': False, 'offset_deg': 0.0, 'scale': 1.0, 'gear_ratio': 150.0,
    }],
}


def _bridge(tmp_path):
    repository = ProjectRepository(tmp_path / 'projects')
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.project_repository = repository
    bridge.workspace_root = tmp_path
    return bridge, repository


def _new_project(repository, name):
    project_id = repository.create_project(name)['project']['project_id']
    repository.select_project(project_id)
    return project_id


def _save_registry(bridge, registry=None):
    service = _motor_config_of(bridge)
    loaded = service.load()
    result = service.save({
        'registry': registry or motor_config_rules.registry_from_motor_config(CONFIG),
        'file_name': 'motor_axes.yaml',
        'base_revision': loaded.get('config_revision', ''),
    })
    assert result['success'] is True, result
    return result


def _driver_limits(tmp_path, project_id):
    path = tmp_path / 'projects' / project_id / 'motor_axes' / 'motor_axes.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    slave = config['masters'][0]['slaves'][0]
    driver = next(d for d in config['drivers'] if d['id'] == slave['driver_id'])
    return driver['lower'], driver['upper']


def _save_mapping(repository, project_id, mapping=MAPPING):
    repository.import_text(
        project_id, 'motion_axis_matching', 'neck.yaml',
        yaml.safe_dump(mapping, allow_unicode=True),
    )
    repository.set_active(project_id, 'motion_axis_matching', 'neck.yaml')


def test_mapping_save_rewrites_motor_limits(tmp_path):
    bridge, repository = _bridge(tmp_path)
    project_id = _new_project(repository, 'limits')
    _save_registry(bridge)
    assert _driver_limits(tmp_path, project_id) == (-36000.0, 36000.0)

    _save_mapping(repository, project_id)
    synced = _motor_config_of(bridge).sync_limits_from_mapping()

    assert synced['success'] is True
    assert [item['controller_index'] for item in synced['changed']] == [0]
    assert _driver_limits(tmp_path, project_id) == (-1500.0, 1950.0)
    # 다시 해도 바뀐 것이 없으면 파일을 안 쓴다
    assert _motor_config_of(bridge).sync_limits_from_mapping()['changed'] == []


def test_motor_config_save_keeps_mapping_limits(tmp_path):
    """모터 목록 저장에 옛 lower/upper 가 실려 와도 매핑 값이 이긴다."""
    bridge, repository = _bridge(tmp_path)
    project_id = _new_project(repository, 'registry path')
    _save_mapping(repository, project_id)
    registry = motor_config_rules.registry_from_motor_config(CONFIG)
    registry['motors'][0].setdefault('config', {}).update(lower=-5.0, upper=5.0)
    _save_registry(bridge, registry)
    assert _driver_limits(tmp_path, project_id) == (-1500.0, 1950.0)


def test_raw_text_save_keeps_mapping_limits(tmp_path):
    bridge, repository = _bridge(tmp_path)
    project_id = _new_project(repository, 'raw path')
    _save_registry(bridge)
    _save_mapping(repository, project_id)
    service = _motor_config_of(bridge)
    loaded = service.load()
    edited = yaml.safe_load(loaded['content'])
    edited['drivers'][0]['lower'] = -1.0
    result = service.save({
        'content': yaml.safe_dump(edited, allow_unicode=True),
        'file_name': 'motor_axes.yaml',
        'base_revision': loaded['config_revision'],
    })
    assert result['success'] is True, result
    assert _driver_limits(tmp_path, project_id) == (-1500.0, 1950.0)


def test_other_project_motor_config_is_untouched(tmp_path):
    """프로젝트 격리 · A 의 매핑이 B 의 모터 설정을 바꾸지 않는다."""
    bridge, repository = _bridge(tmp_path)
    project_b = _new_project(repository, 'B')
    _save_registry(bridge)
    project_a = _new_project(repository, 'A')
    _motor_config_of(bridge).clear_selection()
    _save_registry(bridge)
    _save_mapping(repository, project_a)
    _motor_config_of(bridge).sync_limits_from_mapping()

    assert _driver_limits(tmp_path, project_a) == (-1500.0, 1950.0)
    assert _driver_limits(tmp_path, project_b) == (-36000.0, 36000.0)
