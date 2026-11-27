"""애니메이션 파일 각도 단위 · 수정 목록 6-2 (2026-10-06)

헤더 `rotation_unit` 을 아무도 읽지 않아 rad 파일이 deg 로 읽혔다 (약 1/57).
"""

import json
import math

import pytest

from motion_common import motion_table


def test_unit_names_and_legacy_files():
    assert motion_table.normalize_rotation_unit('rad') == 'rad'
    assert motion_table.normalize_rotation_unit('Radians') == 'rad'
    assert motion_table.normalize_rotation_unit('deg') == 'deg'
    # 칸이 없는 옛 파일은 그동안 deg 로 만들어졌다
    assert motion_table.normalize_rotation_unit('') == 'deg'
    assert motion_table.normalize_rotation_unit(None) == 'deg'
    with pytest.raises(ValueError, match='각도 단위'):
        motion_table.normalize_rotation_unit('grad')


def test_scale_goes_to_the_internal_unit():
    # 내부 단위는 rad · 수정 목록 6-3 (2026-10-06)
    assert motion_table.INTERNAL_ROTATION_UNIT == 'rad'
    assert motion_table.rotation_unit_scale('rad') == 1.0
    assert motion_table.rotation_unit_scale('deg') == pytest.approx(math.pi / 180.0)
    assert motion_table.rotation_unit_scale('rad', 'deg') == pytest.approx(180.0 / math.pi)
    assert motion_table.rotation_unit_scale('deg', 'rad') == pytest.approx(math.pi / 180.0)
    assert motion_table.rotation_unit_scale('rad', 'rad') == 1.0


def test_unit_is_read_from_the_header_line_or_the_whole_object():
    jsonl = '{"type":"motion_header","rotation_unit":"rad","fields":["frame","time_sec","id","value"]}\n[1,0.0,"a",0.1]\n'
    assert motion_table.rotation_unit_from_content(jsonl) == 'rad'
    assert motion_table.rotation_unit_from_content('{"type":"motion_header"}\n[1,0,"a",1]\n') == 'deg'
    assert motion_table.rotation_unit_from_content('frame,time,motion_id,value\n1,0,a,1\n') == 'deg'
    whole = json.dumps({'rotation_unit': 'rad', 'data': [[1, 0.0, 'a', 0.5]]})
    assert motion_table.rotation_unit_from_content(whole) == 'rad'
    assert motion_table.rotation_unit_from_content('[[1, 0.0, "a", 0.5]]') == 'deg'


def test_records_are_scaled_in_place():
    records = [{'value': 90.0}, {'value': -180.0}]
    motion_table.scale_record_values(records, 'deg')
    assert [round(r['value'], 9) for r in records] == [round(math.pi / 2, 9), round(-math.pi, 9)]
    same = [{'value': 0.125}]
    motion_table.scale_record_values(same, 'rad')
    assert same == [{'value': 0.125}]


def _converter():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / 'scripts' / 'convert_motion_unit.py'
    spec = importlib.util.spec_from_file_location('convert_motion_unit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_converter_rewrites_header_and_values_and_keeps_ids():
    converter = _converter()
    content = (
        '{"type":"motion_header","rotation_unit":"deg","fields":["frame","time_sec","id","value"]}\n'
        '[1,0.02,"1-1",90.0,"1-2",-45.0]\n'
    )
    converted, source = converter.convert_text(content, 'rad')
    header, row = [json.loads(line) for line in converted.splitlines()]

    assert source == 'deg'
    assert header['rotation_unit'] == 'rad'
    assert row[:3] == [1, 0.02, '1-1'] and row[4] == '1-2'
    assert row[3] == pytest.approx(math.pi / 2) and row[5] == pytest.approx(-math.pi / 4)
    assert converter.convert_text(converted, 'rad') == (converted, 'rad')
    with pytest.raises(ValueError, match='motion_header'):
        converter.convert_text('[1,0,"a",1]\n', 'rad')
