"""모션 표 파서 단일 구현.

표시용(web_bridge 검증)과 실행용(motion_runtime 재생)이 각각 파서를 들고 있으면
화면에 보이는 값과 실제 모터 목표값이 갈라진다. 두 경로 모두 이 모듈을 경유해
동일한 행 집합·동일한 레코드를 얻는다.

레코드 형식 · ``{'frame': int, 'time_sec': float, 'motion_id': str, 'value': float}``
"""

from __future__ import annotations

import ast
import json
import math
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import values

REQUIRED_COLUMNS: Tuple[str, ...] = ('frame', 'time', 'motion_id', 'value')

DATA_KEYS: Tuple[str, ...] = (
    'data',
    'rows',
    'records',
    'motion_data',
    'motions',
    'frames',
    'values',
)

HEADER_KEYS: Tuple[str, ...] = ('header', 'headers', 'columns')

MISSING_HEADER_MESSAGE = 'required header not found: frame, time(sec), motion Id, value'


# --------------------------------------------------------------------------- #
# 각도 단위 · 수정 목록 6-2 (2026-10-06)
# --------------------------------------------------------------------------- #
#
# 애니메이션 파일은 헤더의 `rotation_unit` 으로 단위를 말한다 · Blender 내보내기는
# 이제 `rad` 를 쓴다(사용자 결정 2026-10-06) · 옛 파일은 `deg` 이거나 칸이 없다.
#
# 전에는 이 칸을 **아무도 읽지 않았다** · rad 파일이 deg 로 읽혀 약 1/57 로만
# 움직였다. 이제 파서가 모두 이 함수들을 거쳐 **내부 단위**로 바꿔 넘긴다.
#
# 내부 단위는 rad 다(6-3 · 2026-10-06) · 재생·조인트 매핑·웹 검사 모두 이 단위로 받는다 ·
# 화면은 받은 뒤 deg 로 바꿔 보여 준다.

INTERNAL_ROTATION_UNIT = 'rad'

_UNIT_NAMES = {
    'deg': 'deg', 'degree': 'deg', 'degrees': 'deg',
    'rad': 'rad', 'radian': 'rad', 'radians': 'rad',
}

#: 칸이 없는 옛 파일 · 그동안 deg 로 읽혀 왔고 그렇게 만들어졌다
LEGACY_ROTATION_UNIT = 'deg'


def normalize_rotation_unit(value: Any) -> str:
    """빈 값 = 옛 파일(deg) · 아는 이름 = deg/rad · 모르는 이름은 거절."""
    text = str(value or '').strip().lower()
    if not text:
        return LEGACY_ROTATION_UNIT
    unit = _UNIT_NAMES.get(text)
    if unit is None:
        raise ValueError(f'지원하지 않는 각도 단위입니다: {value} (deg 또는 rad)')
    return unit


def rotation_unit_scale(unit: Any, target: str = '') -> float:
    """`unit` 값에 곱하면 `target`(기본 = 내부 단위) 값이 된다."""
    source = normalize_rotation_unit(unit)
    goal = normalize_rotation_unit(target or INTERNAL_ROTATION_UNIT)
    if source == goal:
        return 1.0
    return math.degrees(1.0) if source == 'rad' else math.radians(1.0)


def header_rotation_unit(header: Any) -> str:
    """헤더 객체(또는 통짜 JSON 객체)의 단위 · 객체가 아니면 옛 파일."""
    if isinstance(header, dict):
        return normalize_rotation_unit(header.get('rotation_unit'))
    return LEGACY_ROTATION_UNIT


def rotation_unit_from_content(content: str) -> str:
    """파일 본문의 단위 · JSON Lines 는 첫 줄 헤더 · 통짜 JSON 은 최상위 객체."""
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        return header_rotation_unit(payload)
    if payload is not None:
        return LEGACY_ROTATION_UNIT
    for line in str(content).splitlines():
        text = line.strip().strip('﻿')
        if not text or text.startswith('#'):
            continue
        if text.startswith('{'):
            return header_rotation_unit(_literal_object(text))
        return LEGACY_ROTATION_UNIT
    return LEGACY_ROTATION_UNIT


def scale_record_values(records: List[Dict[str, Any]], unit: Any) -> List[Dict[str, Any]]:
    """레코드 `value` 를 내부 단위로 · 같은 단위면 손대지 않는다."""
    scale = rotation_unit_scale(unit)
    if scale != 1.0:
        for record in records:
            record['value'] = float(record['value']) * scale
    return records


# --------------------------------------------------------------------------- #
# 값 변환
# --------------------------------------------------------------------------- #

# 값 변환은 values.py가 단일 구현 · 기존 호출부 호환을 위해 이름을 유지한다
finite_float = values.finite_float


def motion_id_text(value: Any) -> str:
    """조인트 이름을 문자열로 정규화한다.

    숫자 3.0과 문자열 '3'이 서로 다른 그룹으로 갈리지 않도록 정수형 실수는
    소수점을 떼고 표기한다.
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value).strip()
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        number = float(value)
        return str(int(number)) if math.isclose(number, round(number)) else str(number)
    return str(value).strip()


# --------------------------------------------------------------------------- #
# 컬럼 해석
# --------------------------------------------------------------------------- #

def column_key(label: Any) -> str:
    """컬럼 표기를 정규 키로 환산한다."""
    compact = ''.join(char for char in str(label).lower() if char.isalnum())
    if compact in ('frame', 'frameid', 'frameindex'):
        return 'frame'
    if compact in ('time', 'times', 'timesec', 'seconds', 'sec', 'timestamp'):
        return 'time'
    if compact in ('motionid', 'motion', 'id', 'jointid', 'channelid'):
        return 'motion_id'
    if compact in ('value', 'angle', 'angledeg', 'deg', 'position', 'positiondeg'):
        return 'value'
    return compact


def column_value(row: Dict[str, Any], target: str) -> Any:
    """dict 행에서 정규 키에 해당하는 값을 찾는다."""
    for key, value in row.items():
        if column_key(key) == target:
            return value
    return None


def header_map(headers: Any) -> Dict[str, int]:
    """헤더 목록을 ``{정규키: 인덱스}``로 환산한다.

    필수 4개 컬럼이 모두 잡히지 않으면 빈 dict를 돌려준다.
    """
    if not isinstance(headers, (list, tuple)):
        return {}
    mapping: Dict[str, int] = {}
    for index, header in enumerate(headers):
        key = column_key(header)
        if key in REQUIRED_COLUMNS and key not in mapping:
            mapping[key] = index
    return mapping if all(key in mapping for key in REQUIRED_COLUMNS) else {}


#: 바로 앞에 쓴 헤더와 그 결과 · 수정 목록 88 (2026-10-09)
#:
#: `parse_row` 는 기록마다 불린다 · 9분 나레이션은 55만 번 · 그때마다 헤더 정리(`column_key`)를
#: 다시 해서 읽는 시간의 60 % 가 여기 갔다 · 한 파일 안에서 헤더는 같으니 앞 결과를 쓴다 ·
#: 내용으로 비교한다(같은 자리의 다른 목록이어도 틀리지 않게).
_LAST_HEADER_MAP: Tuple[Any, Dict[str, int]] = (None, {})


def _row_header_map(headers: Any) -> Dict[str, int]:
    if not isinstance(headers, (list, tuple)):
        return {}
    snapshot, mapping = _LAST_HEADER_MAP
    # 같은 종류끼리 `==` · 파이썬 안쪽(C)에서 비교해 빠르다
    if snapshot is not None and type(snapshot) is type(headers) and snapshot == headers:
        return mapping
    mapping = header_map(headers)
    globals()['_LAST_HEADER_MAP'] = (type(headers)(headers), mapping)
    return mapping


def header_has_required(headers: Any) -> bool:
    """헤더가 필수 4개 컬럼을 모두 담고 있는지 판정한다."""
    return bool(header_map(headers))


# --------------------------------------------------------------------------- #
# 텍스트 행 파싱
# --------------------------------------------------------------------------- #

def _literal_list(text: str) -> Optional[List[Any]]:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = None
    return parsed if isinstance(parsed, list) else None


def _literal_object(text: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def parse_text_row(line: str) -> Optional[List[Any]]:
    """한 줄을 값 목록으로 파싱한다.

    대괄호 리터럴 행과 쉼표/탭 구분 행을 모두 받는다. 두 형식 중 하나만 받으면
    한쪽 파서는 통과하고 다른 쪽은 행을 통째로 버리는 불일치가 생긴다.
    """
    text = str(line).strip().rstrip(',').strip()
    if not text or text in ('[', ']'):
        return None
    if text.startswith('[') and text.endswith(']'):
        parsed = _literal_list(text)
        if parsed is not None:
            return parsed
        text = text[1:-1]
    if ',' in text:
        return [part.strip().strip('"\'') for part in text.split(',')]
    if '\t' in text:
        return [part.strip().strip('"\'') for part in text.split('\t')]
    return None


def parse_header_line(line: str) -> List[str]:
    """헤더 줄을 컬럼 목록으로 파싱한다.

    ``{"fields": [...]}`` 형태의 모션 헤더 객체, 대괄호 리터럴, 쉼표/탭 구분을
    모두 받는다. 어느 쪽으로도 읽히지 않으면 빈 목록을 돌려주며, 호출자는 이를
    '헤더 없음'으로 처리해야 한다.
    """
    text = str(line).strip().strip('\ufeff').rstrip(',').strip()
    if not text:
        return []
    if text.startswith('{') and text.endswith('}'):
        fields = _literal_object(text).get('fields')
        if isinstance(fields, list):
            return [str(item).strip() for item in fields]
        return []
    parsed = parse_text_row(text)
    if parsed is not None:
        return [str(item).strip() for item in parsed]
    lowered = text.lower()
    if all(token in lowered for token in ('frame', 'time', 'motion', 'value')):
        return ['frame', 'time(sec)', 'motion Id', 'value']
    return []


# --------------------------------------------------------------------------- #
# 행 확장
# --------------------------------------------------------------------------- #

def expand_pair_rows(rows: List[Any], headers: Any = None) -> List[Any]:
    """``[frame, time, id1, v1, id2, v2, ...]`` 행을 4열 행으로 펼친다.

    헤더가 없으면 위치 기준(0,1,2,3)으로 간주해 펼친다. 헤더가 있으면서 순서가
    ``frame, time, motion_id, value``가 아니면 확장 규칙이 성립하지 않으므로
    원본을 그대로 돌려준다.
    """
    mapping = header_map(headers)
    if mapping and (
        mapping.get('frame') != 0
        or mapping.get('time') != 1
        or mapping.get('motion_id') != 2
        or mapping.get('value') != 3
    ):
        return rows

    expanded: List[Any] = []
    changed = False
    for row in rows:
        if not isinstance(row, list) or len(row) <= 4:
            expanded.append(row)
            continue
        if (len(row) - 2) % 2 != 0:
            expanded.append(row)
            continue
        frame = row[0]
        time_sec = row[1]
        for index in range(2, len(row), 2):
            expanded.append([frame, time_sec, row[index], row[index + 1]])
        changed = True
    return expanded if changed else rows


def pair_rows_expandable(headers: Any = None) -> bool:
    """`expand_pair_rows` 가 짝 줄을 펼치는 헤더인가 · 헤더 없음 또는 frame, time, id, value 순서"""
    mapping = header_map(headers)
    return not mapping or (
        mapping.get('frame') == 0
        and mapping.get('time') == 1
        and mapping.get('motion_id') == 2
        and mapping.get('value') == 3
    )


def keep_pairs(row: Any, keep: Any, memo: Optional[Dict[Any, bool]] = None) -> Tuple[Any, int]:
    """펼치기 전 짝 줄에서 `keep` 에 없는 조인트 쌍을 뺀다 · (줄, 뺀 쌍 수) · 수정 목록 164

    한 파일에 여러 로봇의 조인트가 들어 있어도(4대 × 5 = 20) 이 PC 는 제 매핑의 조인트만 쓴다(N16) ·
    펼치고 레코드를 만든 뒤 버리던 것을 펼치기 전에 뺀다 · 남는 레코드는 그대로 같다.
    짝 줄(`[frame, time, id1, v1, ...]` · 4칸 초과 · 짝 맞음)이 아니면 손대지 않는다(뒤에서 거른다).
    `memo` · 글자 조인트 이름 → 남길지 · 줄마다 같은 이름이 되풀이되므로.
    """
    if not isinstance(row, list) or len(row) <= 4 or (len(row) - 2) % 2 != 0:
        return row, 0
    kept = row[:2]
    dropped = 0
    for index in range(2, len(row), 2):
        raw = row[index]
        keep_it = memo.get(raw) if memo is not None and isinstance(raw, str) else None
        if keep_it is None:
            keep_it = motion_id_text(raw) in keep
            if memo is not None and isinstance(raw, str):
                memo[raw] = keep_it
        if keep_it:
            kept.append(raw)
            kept.append(row[index + 1])
        else:
            dropped += 1
    return kept, dropped


# --------------------------------------------------------------------------- #
# 행 추출
# --------------------------------------------------------------------------- #

def _payload_headers(payload: Dict[str, Any]) -> List[str]:
    for key in HEADER_KEYS:
        headers = payload.get(key)
        if isinstance(headers, list):
            return [str(item) for item in headers]
    return []


def extract_rows(payload: Any) -> Tuple[List[Any], List[str], str]:
    """디코딩된 JSON 페이로드에서 ``(행, 헤더, 출처)``를 뽑는다."""
    if isinstance(payload, list):
        if payload and isinstance(payload[0], list):
            possible_header = [str(item) for item in payload[0]]
            if header_has_required(possible_header):
                return (
                    expand_pair_rows(payload[1:], possible_header),
                    possible_header,
                    'array_with_header',
                )
        return expand_pair_rows(payload), [], 'array'

    if isinstance(payload, dict):
        headers = _payload_headers(payload)
        for key in DATA_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                if value and isinstance(value[0], list):
                    possible_header = [str(item) for item in value[0]]
                    if header_has_required(possible_header):
                        return (
                            expand_pair_rows(value[1:], possible_header),
                            possible_header,
                            f'{key}_with_header',
                        )
                return expand_pair_rows(value, headers), headers, key
        if all(column_value(payload, name) is not None for name in REQUIRED_COLUMNS):
            return [payload], headers, 'object'
    return [], [], 'unknown'


def extract_rows_from_text(content: str) -> Tuple[List[Any], List[str], str, str]:
    """헤더+행 텍스트 형식에서 ``(행, 헤더, 출처, 경고문)``을 뽑는다.

    첫 줄이 유효한 헤더로 읽히면 헤더로 쓰고 나머지를 데이터로 본다. 헤더로
    읽히지 않으면 첫 줄도 데이터로 본다 — 헤더 없는 파일의 첫 행을 잃지 않는다.
    """
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]
    if not lines:
        return [], [], 'text', 'text format requires at least one data row'

    candidate = parse_header_line(lines[0])
    if header_has_required(candidate):
        headers = candidate
        data_lines = lines[1:]
    else:
        headers = []
        data_lines = lines

    rows: List[Any] = []
    skipped = 0
    for line in data_lines:
        row = parse_text_row(line)
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    if not rows:
        return [], headers, 'text_header_list_rows', 'bracket data rows not found'
    rows = expand_pair_rows(rows, headers)
    warning = f'skipped non-data lines: {skipped}' if skipped else ''
    return rows, headers, 'text_header_list_rows', warning


def extract_rows_from_content(content: str) -> Tuple[List[Any], List[str], str, str]:
    """파일 본문에서 ``(행, 헤더, 출처, 경고문)``을 뽑는다.

    엄격한 JSON을 먼저 시도하고, 실패하면 헤더+행 텍스트 형식으로 해석한다.
    """
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return extract_rows_from_text(content)
    rows, headers, source = extract_rows(payload)
    return rows, headers, source, ''


# --------------------------------------------------------------------------- #
# 레코드 파싱
# --------------------------------------------------------------------------- #

def parse_row(row: Any, headers: Any = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """한 행을 레코드로 환산한다. 실패하면 ``(None, 사유)``."""
    if isinstance(row, dict):
        frame = column_value(row, 'frame')
        time_sec = column_value(row, 'time')
        motion_id = column_value(row, 'motion_id')
        value = column_value(row, 'value')
    elif isinstance(row, list):
        mapping = _row_header_map(headers)
        if not mapping and len(row) >= 4:
            mapping = {'frame': 0, 'time': 1, 'motion_id': 2, 'value': 3}
        try:
            frame = row[mapping['frame']]
            time_sec = row[mapping['time']]
            motion_id = row[mapping['motion_id']]
            value = row[mapping['value']]
        except (KeyError, IndexError):
            return None, 'required columns not found'
    else:
        return None, 'record must be an object or array'

    frame_value = finite_float(frame)
    time_value = finite_float(time_sec)
    value_number = finite_float(value)
    motion_text = motion_id_text(motion_id)

    if frame_value is None:
        return None, 'frame must be numeric'
    if time_value is None:
        return None, 'time(sec) must be numeric'
    if time_value < 0:
        return None, 'time(sec) must be greater than or equal to 0'
    if not motion_text:
        return None, 'motion Id is required'
    if value_number is None:
        return None, 'value must be numeric'

    return {
        'frame': int(round(frame_value)),
        'time_sec': float(time_value),
        'motion_id': motion_text,
        'value': float(value_number),
    }, ''


def parse_rows(rows: List[Any], headers: Any = None) -> List[Dict[str, Any]]:
    """행 목록을 레코드 목록으로 환산한다. 실패한 행은 건너뛰고 ``row_index``를 붙인다."""
    records: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        record, error = parse_row(row, headers)
        if error:
            continue
        record['row_index'] = index
        records.append(record)
    return records


# --------------------------------------------------------------------------- #
# 올리기 검사 · 수정 목록 31 (2026-10-06)
# --------------------------------------------------------------------------- #

def validate_motion_content(content: str) -> int:
    """재생 파서가 읽을 수 있는 파일인가 · 읽은 행 수 · 못 읽으면 사유와 함께 ValueError.

    올리기 검사와 재생이 **같은 파서**를 쓴다 · 재생이 읽으면 올라가고, 올라간
    것은 재생이 읽는다. 각도 단위도 같은 자리에서 본다(6-2).
    """
    text = str(content or '')
    if not text.strip():
        raise ValueError('빈 파일입니다')
    normalize_rotation_unit(rotation_unit_from_content(text))
    try:
        json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # 헤더+행 글(JSON Lines 등) · 행을 목록으로 모으지 않고 한 줄씩 · 920 s × 20 조인트면
        # 펼친 행 92만 개를 들 뻔했다 · 행 · 경고는 `extract_rows_from_text` 와 같다 · 수정 목록 170
        headers, rows, warning = _lazy_text_rows(text)
    else:
        rows, headers, _source, warning = extract_rows_from_content(text)
    first_error = ''
    count = 0
    seen = False
    for row in rows:
        seen = True
        record, error = parse_row(row, headers)
        if record is None:
            first_error = first_error or error
            continue
        count += 1
    if not seen:
        raise ValueError(f'애니메이션 행을 찾지 못했습니다{f" · {warning}" if warning else ""}')
    if count == 0:
        raise ValueError(f'재생할 수 있는 행이 없습니다 · {first_error or "형식 확인"}')
    return count


def _lazy_text_rows(content: str) -> Tuple[List[str], Iterator[Any], str]:
    """`extract_rows_from_text` 의 행을 하나씩 · (헤더, 행 반복자, 행이 없을 때 경고)"""
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]
    if not lines:
        return [], iter(()), 'text format requires at least one data row'
    candidate = parse_header_line(lines[0])
    if header_has_required(candidate):
        headers, data_lines = candidate, lines[1:]
    else:
        headers, data_lines = [], lines

    def rows() -> Iterator[Any]:
        for line in data_lines:
            row = parse_text_row(line)
            if row is not None:
                yield from expand_pair_rows([row], headers)

    return headers, rows(), 'bracket data rows not found'



# --------------------------------------------------------------------------- #
# JSON Lines 파일을 한 줄씩 · 수정 목록 170 (2026-11-03)
# --------------------------------------------------------------------------- #
#
# 920 s × 20 조인트 파일(25 MB)을 글 통째로 읽고 행 92만 개를 목록으로 들면 웹 브리지가 한 번에
# 600 MB 를 썼다(파이썬 사전·목록) · 메모리 4.7 GB PC 에서 스왑으로 넘어갔다. 머리 줄이 있는
# JSON Lines(Blender 내보내기 · 웹 녹화)는 아래 둘로 한 줄씩 읽는다 · 같은 행이 나온다
# (`extract_rows_from_text` 와 같은 거르기 · 펼치기). 다른 모양은 부르는 쪽이 옛 길로 간다.
#
# 읽기 버퍼는 1 MB · 기본(8 KB)이면 0.4 ms 마다 읽기 시스템 호출로 GIL 을 놓았다 다시 잡는다 ·
# 파이썬 3.10 GIL 은 기다리는 스레드가 5 ms 동안 「바뀜」 을 못 봐야 양보를 요청하므로 그동안 이벤트
# 루프 · 실행기 스레드가 **1 초 넘게** 굶었다(WSL 측정 · 920 s 파일 · 옛 런타임 줄 읽기도 같았다).
READ_BUFFER_BYTES = 1 << 20


def open_text(path: Any, **kwargs: Any):
    """큰 덩어리로 읽는 UTF-8 글 · 줄 단위로 오래 읽는 곳은 이것으로

    `buffering` 만 키우면 소용이 없다 · 글 래퍼가 `read1(8192)` 로 묻고 버퍼가 비면 그만큼만 읽는다 ·
    래퍼의 덩어리 크기(`_CHUNK_SIZE` · 공개 속성)를 같이 키운다.
    """
    handle = open(path, 'r', encoding='utf-8', buffering=READ_BUFFER_BYTES, **kwargs)
    try:
        handle._CHUNK_SIZE = READ_BUFFER_BYTES
    except (AttributeError, ValueError):
        pass
    return handle


def jsonl_motion_header(path: Any) -> Optional[Tuple[Dict[str, Any], List[str]]]:
    """첫 줄(빈 줄 · # 줄 빼고)이 `{"type": "motion_header", fields…}` 이면 (머리 객체, 칸 이름) · 아니면 None

    BOM 이 붙은 파일 · 필수 칸이 없는 머리는 None(옛 길) · 파일을 못 읽으면 OSError.
    """
    with open_text(path) as handle:
        for raw_line in handle:
            text = raw_line.strip()
            if not text or text.startswith('#'):
                continue
            if text.startswith('\ufeff'):
                return None
            try:
                first = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return None
            if not isinstance(first, dict) or str(first.get('type') or '') != 'motion_header':
                return None
            headers = parse_header_line(text)
            if not header_has_required(headers):
                return None
            return first, headers
    return None


def iter_jsonl_rows(path: Any, headers: Any) -> Iterator[Tuple[Optional[List[Any]], int]]:
    """머리 줄 뒤 데이터 줄을 한 줄씩 · (펼친 행, 0) 또는 못 읽은 줄이면 (None, 1)

    행은 `extract_rows_from_text` 가 내는 것과 같다(`parse_text_row` · `expand_pair_rows(…, headers)`).
    """
    with open_text(path) as handle:
        header_seen = False
        for raw_line in handle:
            text = raw_line.strip()
            if not text or text.startswith('#'):
                continue
            if not header_seen:
                header_seen = True
                continue
            row = parse_text_row(text)
            if row is None:
                yield None, 1
                continue
            for expanded in expand_pair_rows([row], headers):
                yield expanded, 0
