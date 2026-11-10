"""직렬 서보 온도 기록 · 1분 요약 CSV · 7일 · 한계 가까움 경고 · 수정 목록 191"""

from datetime import datetime

import pytest

from motion_web_bridge.motor_temperature_log import HEADER, MotorTemperatureLog


class Clock:
    def __init__(self, text):
        self.now = datetime.fromisoformat(text).astimezone().timestamp()

    def __call__(self):
        return self.now


def _motor(axis, temp, limit=70.0, kind='feetech', joint='head_yaw'):
    return {'controller_index': axis, 'temperature_c': temp, 'temperature_limit_c': limit,
            'motor_type': kind, 'motion_id': joint}


def test_one_row_per_motor_per_minute_with_min_max_last(tmp_path):
    clock = Clock('2026-11-10 14:00:05')
    log = MotorTemperatureLog(tmp_path, clock=clock)
    for temp in (47.0, 49.0, 48.0):
        log.observe({'motors': [_motor(4, temp), _motor(1, 41.0, 80.0, 'dynamixel', 'crank_f')]})
        clock.now += 10
    # AC 축 · 통신 끊김(온도 None)은 적지 않는다
    log.observe({'motors': [{'controller_index': 0, 'temperature_c': None}]})
    assert not (tmp_path / '2026-11-10.csv').exists()   # 분이 끝나야 적는다

    clock.now += 30   # 14:01
    log.observe({'motors': [_motor(4, 50.0)]})
    text = (tmp_path / '2026-11-10.csv').read_text(encoding='utf-8')
    assert text == HEADER + (
        '2026-11-10 14:00,1,crank_f,dynamixel,41,41,41,80\n'
        '2026-11-10 14:00,4,head_yaw,feetech,47,49,48,70\n'
    )


def test_joint_name_from_mapping_wins(tmp_path):
    clock = Clock('2026-11-10 14:00:00')
    log = MotorTemperatureLog(tmp_path, clock=clock)
    log.observe({'motors': [_motor(4, 47.5, joint='')]}, lambda: {4: 'head_yaw'})
    clock.now += 60
    log.observe({'motors': []}, lambda: {4: 'head_yaw'})
    assert '2026-11-10 14:00,4,head_yaw,feetech,47.5,47.5,47.5,70\n' in (tmp_path / '2026-11-10.csv').read_text()


def test_keeps_seven_days(tmp_path):
    for day in ('2026-11-02', '2026-11-03', '2026-11-04', '2026-11-09'):
        (tmp_path / f'{day}.csv').write_text(HEADER)
    (tmp_path / 'note.txt').write_text('x')
    clock = Clock('2026-11-10 00:00:10')
    log = MotorTemperatureLog(tmp_path, clock=clock)
    log.observe({'motors': [_motor(4, 40.0)]})
    clock.now += 60
    log.observe({'motors': [_motor(4, 40.0)]})
    names = sorted(p.name for p in tmp_path.iterdir())
    # 오늘(11-10) 포함 7일 = 11-04 부터
    assert names == ['2026-11-04.csv', '2026-11-09.csv', '2026-11-10.csv', 'note.txt']
    assert [d['date'] for d in log.days()['days']] == ['2026-11-10', '2026-11-09', '2026-11-04']


def test_warning_once_near_limit_until_it_cools_down(tmp_path):
    clock = Clock('2026-11-10 14:00:00')
    warnings = []
    log = MotorTemperatureLog(tmp_path, clock=clock, on_warning=warnings.append)
    for temp in (59.0, 60.0, 61.0, 59.0, 58.5, 60.0):   # 한계 70 · 60 에서 1건 · 58 아래 전엔 다시 안 적음
        log.observe({'motors': [_motor(4, temp)]}, lambda: {4: 'head_yaw'})
    assert [(w['axis'], w['temperature_c'], w['limit_c'], w['joint']) for w in warnings] == [(4, 60.0, 70.0, 'head_yaw')]
    log.observe({'motors': [_motor(4, 57.0)]})
    log.observe({'motors': [_motor(4, 60.0)]})
    assert len(warnings) == 2
    # 한계를 모르면 경고 없음
    log.observe({'motors': [_motor(5, 99.0, limit=None)]})
    assert len(warnings) == 2


def test_download_path_checks_the_name(tmp_path):
    log = MotorTemperatureLog(tmp_path)
    (tmp_path / '2026-11-10.csv').write_text(HEADER)
    assert log.file_path('2026-11-10') == tmp_path / '2026-11-10.csv'
    for bad in ('../x', '2026-11-1', '2026-11-11'):
        with pytest.raises(ValueError):
            log.file_path(bad)
