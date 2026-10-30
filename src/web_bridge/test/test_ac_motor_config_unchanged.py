"""AC 서보 전용 로봇 · 모터 설정 파일 변화 없음 · 수정 목록 158 회귀

직렬 서보(Dynamixel 여러 모델 · Feetech) 를 넣기 **전** 코드(main aa21f9f6)의
`motor_config_from_registry` 출력을 `fixtures/ac_motor_config_head.json` 에 떠 두었다 ·
AC 전용 레지스트리는 바이트 단위로 같아야 한다 (MINAS param 파일 내용 포함).

섞인 레지스트리(AC + XM540) · AC 쪽 드라이버·마스터는 같아야 한다 ·
다이나믹셀 드라이버의 `param_file` 만 새 생성 파일(`config/serial_params/`)로 바뀐다 ·
운전 값(속도·가속)은 0 = 서보 최대로 바뀐다 (수정 목록 163).

다시 뜨기 (변경 전 코드에서만) · `python3 test_ac_motor_config_unchanged.py <출력.json>`
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'ac_motor_config_head.json'


def _ac(axis, *, model='MADLN05BE', master=0, alias=0, position=None, **config):
    return {
        'id': f'ac-{axis}',
        'enabled': True,
        'axis': axis,
        'name': f'모터 {axis}',
        'motor_type': 'ac_servo',
        'driver_family': 'minas',
        'transport': 'ethercat',
        'identity': {
            'ethercat_master_index': master,
            'ethercat_alias': alias,
            'slave_position': axis if position is None else position,
            'vendor_id': 0x066F,
            'product_code': 0x60380004,
            'revision_number': 0x00010000,
            'serial_number': 0x21000000 + axis,
            'identity_source': 'sii',
            'sii_order_number': model,
        },
        'profile': {'driver_model': model, 'model_confirmed': True},
        'config': {'controller_index': axis, **config},
    }


def _dxl(axis, model, bus_id, port='/dev/serial/by-id/usb-FTDI_U2D2-if00-port0'):
    return {
        'id': f'dxl-{axis}',
        'enabled': True,
        'axis': axis,
        'name': f'모터 {axis}',
        'motor_type': 'dynamixel',
        'driver_family': 'dynamixel',
        'transport': 'serial',
        'identity': {
            'serial_port': port,
            'serial_baudrate': 1000000,
            'bus_id': bus_id,
            'model_number': 1130 if 'W150' in model else 1120,
        },
        'profile': {'driver_model': model, 'model_confirmed': True},
        'config': {'controller_index': axis},
    }


def _cases(default_config):
    """(이름, 레지스트리, 현재 설정) · AC 전용 4개 + 섞인 1개."""
    with_old_serial = copy.deepcopy(default_config)
    with_old_serial['masters'].append({
        'id': 1, 'type': 'serial', 'serial_port': '/dev/ttyUSB0', 'serial_baudrate': 1000000,
        'number_of_slaves': 1, 'slaves': [{'controller_index': 9, 'name': 'old', 'driver_id': 1, 'bus_id': 1}],
    })
    with_old_serial['drivers'].append({
        'id': 1, 'type': 'dynamixel', 'driver_model': 'XM540-W270-R',
        'param_file': 'config/dynamixel_xm540_w270.yaml', 'profile_position_value': 3,
    })
    tuned = copy.deepcopy(default_config)
    tuned['drivers'][0]['driver_model'] = 'MADLN05BE'
    tuned['drivers'][0]['speed'] = 123456.0
    tuned['drivers'][0]['rated_power_w'] = 50
    tuned['drivers'].append(dict(tuned['drivers'][0], id=5, driver_model='MCDLN35BE', speed=3000.0))
    return [
        ('ac_three_same_model', {'motors': [_ac(0), _ac(1), _ac(2)]}, None),
        ('ac_overrides_alias_two_masters', {'motors': [
            _ac(0, alias=103, profile_velocity=9000.0, profile_acceleration=40000.0,
                max_speed_rpm=2000, brake_delay_stop_ms=150, brake_delay_run_ms=0, overload_monitor=1),
            _ac(1, alias=403, position=1, acceleration=90000.0),
            _ac(2, master=1, model='MCDLN35BE', position=0, max_speed_rpm=99999),
            dict(_ac(3), enabled=False),
            dict(_ac(4), deleted=True),
        ]}, None),
        ('ac_existing_tuned_drivers', {'motors': [
            _ac(0, driver_id=0), _ac(1, driver_id=0), _ac(2, model='MCDLN35BE', driver_id=5),
        ]}, tuned),
        ('ac_prunes_old_serial', {'motors': [_ac(0), _ac(1, model='MCDLN35BE')]}, with_old_serial),
        ('mixed_ac_xm540', {'motors': [
            _ac(0), _dxl(1, 'XM540-W150', 1), _dxl(2, 'XM540-W270-R', 2), _ac(3, model='MCDLN35BE'),
        ]}, None),
    ]


def build_outputs(workspace: Path, params_dir: Path) -> dict:
    """모든 경우의 출력 · 경로는 자리표시로 바꾼다 · 생성된 MINAS param 파일 내용도 같이."""
    from motion_web_bridge import minas_params
    from motion_web_bridge.motor_config_build import default_motor_config, motor_config_from_registry

    # 기반·현장 값은 저장소 그대로 · 쓰는 폴더만 임시로 (절대경로면 `config/` 뒤에 붙지 않는다)
    original_dir = minas_params.OUTPUT_DIR
    minas_params.OUTPUT_DIR = str(params_dir / 'minas_params')
    try:
        from motion_web_bridge import serial_params
    except ImportError:   # 변경 전 코드 · 다이나믹셀은 정적 파일
        serial_params = None
    if serial_params is not None:
        original_root = serial_params.output_root
        serial_params.output_root = lambda _root: params_dir / 'serial_params'
    try:
        outputs = {}
        for name, registry, current in _cases(default_motor_config(workspace)):
            for path in params_dir.glob('*/*.yaml'):
                path.unlink()
            config = motor_config_from_registry(
                workspace, copy.deepcopy(registry),
                copy.deepcopy(current) if current is not None else default_motor_config(workspace),
            )
            text = json.dumps(config, ensure_ascii=False, sort_keys=True)
            text = text.replace(str(params_dir), '<PARAMS>').replace(str(workspace), '<WS>')
            params = {
                path.name: path.read_text(encoding='utf-8')
                for path in sorted(params_dir.glob('minas_params/*.yaml'))
            }
            outputs[name] = {'config': json.loads(text), 'minas_params': params}
        return outputs
    finally:
        minas_params.OUTPUT_DIR = original_dir
        if serial_params is not None:
            serial_params.output_root = original_root


#: 다이나믹셀 운전 값 · 옛 기본(396 · 222 · 703104.5) → 0 = 서보 최대 · 수정 목록 163 · 떠 둔 파일은 그대로 두고 견줄 때만 뺀다
_DYNAMIXEL_PROFILE_FIELDS = (
    'speed', 'acceleration', 'deceleration',
    'profile_velocity', 'profile_acceleration', 'profile_deceleration',
)


def _without_dynamixel_param_files(config: dict) -> dict:
    result = copy.deepcopy(config)
    for driver in result.get('drivers', []):
        if driver.get('type') == 'dynamixel':
            driver.pop('param_file', None)
            for field in _DYNAMIXEL_PROFILE_FIELDS:
                driver.pop(field, None)
    return result


def test_ac_only_registries_build_byte_identical_configs(tmp_path):
    expected = json.loads(FIXTURE.read_text(encoding='utf-8'))
    actual = build_outputs(WORKSPACE, tmp_path)
    for name, value in expected.items():
        if not name.startswith('ac_'):
            continue
        assert json.dumps(actual[name], ensure_ascii=False, sort_keys=True) == json.dumps(
            value, ensure_ascii=False, sort_keys=True
        ), name


def test_mixed_registry_keeps_ac_part_and_only_moves_dynamixel_param_file(tmp_path):
    expected = json.loads(FIXTURE.read_text(encoding='utf-8'))['mixed_ac_xm540']
    actual = build_outputs(WORKSPACE, tmp_path)['mixed_ac_xm540']
    assert actual['minas_params'] == expected['minas_params']
    assert _without_dynamixel_param_files(actual['config']) == _without_dynamixel_param_files(
        expected['config']
    )
    for driver in actual['config']['drivers']:
        if driver.get('type') == 'dynamixel':
            assert driver['param_file'] == f'<PARAMS>/serial_params/driver_{driver["id"]}.yaml'
            assert all(driver[field] == 0.0 for field in _DYNAMIXEL_PROFILE_FIELDS)


def test_generated_xm540_param_files_equal_the_old_static_files(tmp_path, monkeypatch):
    """XM540-W150 · W270 · 생성 파일 = 지금 `config/dynamixel_xm540_*.yaml` (model_file 만 절대경로)."""
    from motion_web_bridge import serial_params

    monkeypatch.setattr(serial_params, 'output_root', lambda _root: tmp_path)
    for model, static in (
        ('XM540-W150', 'dynamixel_xm540_w150.yaml'),
        ('XM540-W270-R', 'dynamixel_xm540_w270.yaml'),
    ):
        path = serial_params.write_param_file(WORKSPACE, 7, 'dynamixel', model)
        generated = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
        old = yaml.safe_load((WORKSPACE / 'config' / static).read_text(encoding='utf-8'))
        old_model = (WORKSPACE / 'config' / old.pop('model_file')).resolve()
        new_model = Path(generated.pop('model_file'))
        assert new_model.is_absolute()
        assert new_model.resolve() == old_model
        assert generated == old, model


if __name__ == '__main__':
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        data = build_outputs(WORKSPACE, Path(tmp))
    Path(sys.argv[1]).write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8'
    )
