"""올리기 검사 = 재생 파서 · 수정 목록 31 (2026-10-06)

같은 파일을 올리기 검사와 재생이 따로 판정하면 「올라가는데 안 돈다」 가 생긴다.
"""

import json

import pytest

from motion_common import motion_table
from motion_web_bridge.project_repository import ProjectRepository

HEADER = {'type': 'motion_header', 'rotation_unit': 'deg', 'fields': ['frame', 'time_sec', 'id', 'value']}

READABLE = {
    'blender_jsonl': '\n'.join([json.dumps(HEADER), '[1,0.0,"a",1.0,"b",2.0]', '[2,0.02,"a",1.5,"b",2.5]']),
    'jsonl_without_fields': '{"type":"motion_header"}\n[1,0.0,"a",1.0]\n',
    'json_array_with_header': json.dumps([['frame', 'time', 'motion_id', 'value'], [1, 0.0, 'a', 1.0]]),
    'json_object_rows': json.dumps({'data': [[1, 0.0, 'a', 1.0]]}),
    'json_records': json.dumps({'records': [{'frame': 1, 'time': 0.0, 'motion_id': 'a', 'value': 1.0}]}),
    'csv_text': 'frame,time(sec),motion Id,value(deg)\n1,0.0,a,1.0\n',
    'rad_header': '\n'.join([json.dumps({**HEADER, 'rotation_unit': 'rad'}), '[1,0.0,"a",0.1]']),
}

UNREADABLE = {
    'empty': '   ',
    'no_rows': json.dumps(HEADER) + '\n',
    'bad_values': '\n'.join([json.dumps(HEADER), '[1,0.0,"a","x"]']),
    'unknown_unit': '\n'.join([json.dumps({**HEADER, 'rotation_unit': 'grad'}), '[1,0.0,"a",1.0]']),
    'object_without_rows': json.dumps({'title': 'nothing'}),
}


@pytest.mark.parametrize('name', sorted(READABLE))
def test_what_playback_reads_can_be_uploaded(name):
    content = READABLE[name]
    rows, headers, _source, _warning = motion_table.extract_rows_from_content(content)
    assert motion_table.parse_rows(rows, headers), name     # 재생 파서가 읽는다
    ProjectRepository._validate_content('motions', f'{name}.json', content)


@pytest.mark.parametrize('name', sorted(UNREADABLE))
def test_what_playback_cannot_read_is_refused_with_the_parsers_reason(name):
    with pytest.raises(ValueError) as error:
        ProjectRepository._validate_content('motions', f'{name}.json', UNREADABLE[name])
    assert str(error.value)
