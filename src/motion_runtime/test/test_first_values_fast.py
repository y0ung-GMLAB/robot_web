"""조인트 첫 프레임 값 · 정렬 대신 한 번 훑기 + 파일이 그대로면 앞 결과 · 수정 목록 88 (2026-10-09)

옛 길(전체 정렬 뒤 첫 값)을 아래에 그대로 두고 같은 답을 내는지 본다 · 시각이 뒤섞인 파일 ·
같은 시각에 같은 조인트가 두 번 · 시각 없는 줄까지.
"""

import os
import random

from motion_common import motion_table, units
from motion_runtime.motion_mapping_manager import MotionMappingManager


def _manager(tmp_path):
    manager = MotionMappingManager.__new__(MotionMappingManager)
    manager.motion_files_dir = tmp_path
    return manager


def _legacy(manager, path):
    """2026-10-08 까지의 `_motion_file_first_values` 본문 그대로"""
    content = path.read_text(encoding='utf-8')
    rows = manager._motion_rows_from_content(content)
    unit_scale = motion_table.rotation_unit_scale(motion_table.rotation_unit_from_content(content), units.RAD)
    records = []
    for row_index, row in enumerate(rows):
        for motion_id, value, time_sec in manager._motion_records_from_row(row):
            if motion_id is None:
                continue
            value_number = manager._finite_float(value)
            if value_number is None:
                continue
            time_number = manager._finite_float(time_sec)
            records.append({
                'motion_id': str(motion_id), 'value': value_number * unit_scale,
                'time_sec': time_number if time_number is not None else float(row_index), 'row_index': row_index,
            })
    first = {}
    for record in sorted(records, key=lambda item: (item['time_sec'], item['row_index'])):
        first.setdefault(record['motion_id'], record['value'])
    return first


def _write(path, rows, unit='rad'):
    header = f'{{"type":"motion_header","rotation_unit":"{unit}","fields":["frame","time_sec","id","value"]}}'
    path.write_text('\n'.join([header] + rows) + '\n', encoding='utf-8')


def test_same_answer_as_the_old_sort_on_shuffled_rows(tmp_path):
    rng = random.Random(3)
    rows = []
    for frame in range(1, 400):
        t = round((frame - 1) * 0.02, 4)
        rows.append(f'[{frame},{t},"a",{rng.uniform(-1, 1)},"b",{rng.uniform(-1, 1)}]')
    rows.append('[0,0.0,"a",9.5,"a",8.5]')              # 같은 시각 · 같은 조인트 두 번 · 먼저 나온 것
    rng.shuffle(rows)
    for unit in ('rad', 'deg'):
        path = tmp_path / f'm_{unit}.json'
        _write(path, rows, unit)
        manager = _manager(tmp_path)
        values, error = manager._motion_file_first_values(path.name)
        assert error == ''
        assert values == _legacy(manager, path)


def test_an_unchanged_file_is_read_once_and_a_changed_one_again(tmp_path, monkeypatch):
    path = tmp_path / 'm.json'
    _write(path, ['[1,0.0,"a",1.0]', '[2,0.02,"a",2.0]'])
    manager = _manager(tmp_path)
    reads = []
    real = manager._read_motion_file_first_values
    monkeypatch.setattr(manager, '_read_motion_file_first_values', lambda p: reads.append(p) or real(p))
    first, _ = manager._motion_file_first_values('m.json')
    first['a'] = 'changed by caller'
    again, _ = manager._motion_file_first_values('m.json')
    assert len(reads) == 1 and again == {'a': 1.0}

    _write(path, ['[1,0.0,"a",5.0]'])
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert manager._motion_file_first_values('m.json')[0] == {'a': 5.0}
    assert len(reads) == 2
