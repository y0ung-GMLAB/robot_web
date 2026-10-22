"""직렬 서보 모델 목록 · Dynamixel 제어표 · 시리즈 값 · Feetech STS · 수정 목록 158"""

from pathlib import Path

from motion_common import serial_servo_models as models

WORKSPACE = Path(__file__).resolve().parents[3]


def test_dynamixel_table_is_read_from_the_motion_system_model_list():
    table = models.dynamixel_model_table(WORKSPACE)
    assert table[1120] == 'xm540_w270.model' and table[1130] == 'xm540_w150.model'
    assert table[2000] == 'ph42_020_s300.model'
    assert len(table) > 50


def test_scan_names_keep_the_old_four_and_canonical_names_match_motor_identity():
    # 옛 검색기 표(1120 · 1130 · 1100 · 1110)와 같은 이름
    assert models.dynamixel_scan_name(1120, WORKSPACE) == 'XM540-W270'
    assert models.dynamixel_scan_name(1130, WORKSPACE) == 'XM540-W150'
    assert models.dynamixel_scan_name(1100, WORKSPACE) == 'XH540-W270'
    assert models.dynamixel_scan_name(1110, WORKSPACE) == 'XH540-W150'
    # 정식 이름 · `motor_identity.canonical_dynamixel_model` 결과와 같음
    assert models.dynamixel_model_name(1120, WORKSPACE) == 'XM540-W270-R'
    assert models.dynamixel_model_name(1130, WORKSPACE) == 'XM540-W150'
    assert models.dynamixel_scan_name(1020, WORKSPACE) == 'XM430-W350'
    assert models.dynamixel_scan_name(None, WORKSPACE) == ''
    assert models.dynamixel_scan_name(99999, WORKSPACE) == ''


def test_series_values():
    xm = models.dynamixel_model(WORKSPACE, model_number=1120)
    assert xm['series'] == 'x' and xm['supported'] and xm['has_current']
    assert xm['unit_effort'] == 0.00269 and xm['acceleration_unit'] == 21.4577
    assert xm['position_raw_limit'] == 1048575 and xm['pulse_per_revolution'] == 4096
    assert Path(xm['model_file']).name == 'xm540_w270.model' and Path(xm['model_file']).is_absolute()

    by_name = models.dynamixel_model(WORKSPACE, model_name='XM540-W270-R')
    assert by_name['model_file'] == xm['model_file'] and by_name['model_number'] == 1120

    xl330 = models.dynamixel_model(WORKSPACE, model_number=1200)
    assert xl330['series'] == 'x330' and xl330['unit_effort'] == 0.001

    xl430 = models.dynamixel_model(WORKSPACE, model_name='XL430-W250')
    assert xl430['series'] == 'x' and xl430['has_current'] is False and xl430['unit_effort'] is None

    mx64 = models.dynamixel_model(WORKSPACE, model_number=311)
    assert mx64['series'] == 'mx' and mx64['unit_effort'] == 0.00336
    assert models.dynamixel_model(WORKSPACE, model_number=30)['has_current'] is False   # MX-28

    ph = models.dynamixel_model(WORKSPACE, model_number=2000)
    assert ph['series'] == 'p' and ph['acceleration_unit'] == 0.1
    assert ph['position_raw_limit'] == 2147483647 and ph['template'] == 'dynamixel_p'
    assert ph['pulse_per_revolution'] == 607500


def test_unsupported_models_have_a_reason():
    for number in (350, 4000, 35074, 51201, 43289):   # XL320 · Y · RH-P12-RN · PRO H · PRO M
        info = models.dynamixel_model(WORKSPACE, model_number=number)
        assert info['supported'] is False and info['reason'], number
    proto1 = models.dynamixel_model(WORKSPACE, model_number=12)
    assert proto1['supported'] is False and 'Protocol 1.0' in proto1['reason'] and proto1['model_name'] == 'AX-12A'
    unknown = models.dynamixel_model(WORKSPACE, model_number=65000)
    assert unknown['supported'] is False and unknown['confirm'] is True


def test_feetech_sts_models():
    sts = models.feetech_model(WORKSPACE, model_number=777)
    assert sts['model_name'] == 'STS3215' and sts['confirm'] is False
    assert sts['acceleration_unit'] == 8.7890625 and sts['unit_effort'] == 0.0065
    assert (sts['position_raw_min'], sts['position_raw_max']) == (0, 4095)
    assert sts['model_file'].replace('\\', '/').endswith('hardware/feetech/control_table/sts.model')
    assert models.feetech_model(WORKSPACE, model_number=2825)['model_name'] == 'STS3250'
    other = models.feetech_model(WORKSPACE, model_number=1234)
    assert other['model_name'] == 'Feetech (버전 1234)' and other['confirm'] is True and other['supported'] is True
    assert models.feetech_model(WORKSPACE, model_name='STS3215')['model_number'] == 777
    assert models.feetech_model_name(None) == ''
    assert models.serial_model(WORKSPACE, 'ac_servo') == {}
