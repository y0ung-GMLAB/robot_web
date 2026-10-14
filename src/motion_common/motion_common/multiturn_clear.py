"""다회전 클리어 뒤 기준점 보호 · PC 단위 표시 하나 · 수정 목록 140 ③ (사용자 결정 2026-10-14)

왜 (실물 S 3회차 · 2026-10-14 floating4)
    다회전 클리어는 엔코더 회전 수를 0 으로 버린다 · 몸은 그대로인데 위치 값이 모터 한 바퀴(360°)
    단위로 바뀐다 · 감속 1:20 축이면 조인트 18° · 기준점(모터 deg)은 프로젝트마다 조인트 매핑에 있으므로
    클리어 전에 잡은 기준점은 **모든 프로젝트에서** 틀린 값이 된다 · 그런데 다른 프로젝트를 고르면
    아무 알림 없이 재생할 수 있었다(드라이브 소프트 리밋도 같이 밀려 못 막음).

표시 (작업 폴더 `runtime/multiturn_clear.json` · git 밖 · 프로젝트 밖 · 프로젝트를 바꾸거나 zip 으로
되돌려도 그대로)
    축마다 `cleared_at`(마지막 클리어 시각 · 벽시계) · `serial`(드라이브 시리얼 · 못 읽으면 None) ·
    `pending`(아직 아무 프로젝트에서도 기준점을 다시 지정하지 않음).

막는 것 · 판정은 여기 하나(재생 계획 · 웹 브리지 · 스케줄 · 그룹 하트비트가 같은 글을 쓴다)
    ① `pending` 인 축이 있으면 · 어느 프로젝트든 · 재생 · 초기 위치 이동 · 스케줄 · 그룹 참가 막음
       (수동 조그는 허용 · 몸을 정면·수평에 맞추려면 움직여야 한다)
    ② 지금 쓰는 조인트 매핑에서 그 축 줄의 `reference_set_at`(기준점을 지정한 시각)이 `cleared_at` 보다
       앞이거나 없으면 막음 · 다른 프로젝트에서 다시 지정해 ① 이 풀렸어도, 이 프로젝트의 기준점은
       여전히 클리어 전 값이라서다 · 칸이 없는 옛 파일 = 「앞」 으로 본다(안전한 쪽).

풀림
    조인트 매핑 저장 때 그 축 줄의 기준점 값이 바뀌었거나(숫자 입력 · 캡처) 화면 캡처가
    `reference_captured` 를 보냈으면 저장한 시각을 `reference_set_at` 에 적는다(조인트 매핑 노드) ·
    웹 브리지가 저장 결과를 보고 `cleared_at` 뒤에 지정된 축의 `pending` 을 끈다 ·
    그 프로젝트의 ② 도 같은 칸으로 풀린다 · 다른 프로젝트는 그 프로젝트에서 다시 지정할 때까지 ② 로 막힘.

남는 위험 · PC 시계가 크게 뒤로 가면(벽시계 비교) 판정이 틀릴 수 있다 · 감속 없는 축도 똑같이 막는다
(한 바퀴 = 조인트 360° 라 값은 같아 보이지만 판단을 단순하게).
표준 라이브러리 + `motion_common.store` 만 쓴다.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from motion_common import store

FILE_NAME = 'multiturn_clear.json'
VERSION = 1
#: 조인트 매핑 줄 · 기준점을 지정한 시각(벽시계 초) · 조인트 매핑 노드가 저장 때 적는다
REFERENCE_SET_AT_FIELD = 'reference_set_at'
#: 화면 캡처(「기준점 지정」)가 그 줄에 붙여 보내는 표시 · 값이 그대로여도 지정한 것으로 · 파일엔 안 남음
REFERENCE_CAPTURED_FIELD = 'reference_captured'
#: 사람이 읽는 글 · 끝말 · 「N번 모터 다회전 클리어 뒤 기준점 다시 지정 필요」
BLOCK_SUFFIX = '모터 다회전 클리어 뒤 기준점 다시 지정 필요'
#: 기준점 지정 화면 · 축 표시
NOT_ALIGNED_LABEL = '클리어 뒤 아직 안 맞춤'

PathLike = Union[str, Path]


def marker_path(workspace_root: PathLike) -> Path:
    """작업 폴더 `runtime/` · 이어서 하기(134) 기록과 같은 자리 · PC 하나에 하나"""
    return Path(workspace_root) / 'runtime' / FILE_NAME


def marker_path_for_projects(projects_dir: PathLike) -> Path:
    """`motion_projects/` 를 아는 쪽(재생 노드) · 그 위가 작업 폴더"""
    return marker_path(Path(projects_dir).parent)


def _empty() -> Dict[str, Any]:
    return {'version': VERSION, 'axes': {}}


def _clean(state: Any) -> Dict[str, Any]:
    """읽은 값 정리 · 엉뚱한 칸은 버린다 · 축 번호는 글자 키"""
    if not isinstance(state, dict) or not isinstance(state.get('axes'), dict):
        return _empty()
    axes: Dict[str, Dict[str, Any]] = {}
    for key, entry in state['axes'].items():
        if not isinstance(entry, dict):
            continue
        try:
            axis = int(entry.get('axis', key))
            cleared_at = float(entry.get('cleared_at'))
        except (TypeError, ValueError):
            continue
        axes[str(axis)] = {**entry, 'axis': axis, 'cleared_at': cleared_at, 'pending': bool(entry.get('pending'))}
    return {'version': VERSION, 'axes': axes}


def load(path: PathLike) -> Dict[str, Any]:
    """없거나 못 읽으면 빈 표시 · 읽기 실패로 막지는 않는다(파일이 없는 것과 같다)"""
    return _clean(store.read_json(path, None))


def record_clear(
    path: PathLike, drives: Iterable[Mapping[str, Any]], *, now: Optional[float] = None,
) -> List[int]:
    """클리어할(한) 드라이브 · 축이 있는 것만 · 돌려주는 값 = 적은 축

    클리어 명령을 **보내기 전에** 부른다 · 중간에 끊겨도 표시가 남는 쪽(안전) · 축이 없는(미등록) 드라이브는
    재생에 안 쓰이므로 적지 않는다 · 나중에 등록하면 그때 기준점을 잡는다.
    """
    stamp = time.time() if now is None else float(now)
    entries = []
    for drive in drives:
        try:
            axis = int(drive.get('axis'))
        except (TypeError, ValueError):
            continue
        entries.append({
            'axis': axis,
            'serial': drive.get('serial'),
            'master_index': drive.get('master_index'),
            'slave_position': drive.get('slave_position'),
            'source': str(drive.get('source') or ''),
            'cleared_at': stamp,
            'pending': True,
        })
    if not entries:
        return []

    def mutate(current: Any) -> Dict[str, Any]:
        state = _clean(current)
        for entry in entries:
            state['axes'][str(entry['axis'])] = entry
        return state

    store.update_json(path, mutate, default=None)
    return [entry['axis'] for entry in entries]


def mark_reference_saved(path: PathLike, rows: Iterable[Any]) -> List[int]:
    """조인트 매핑 저장 결과 · 클리어 뒤에 기준점을 지정한 축의 `pending` 을 끈다 · 끈 축을 돌려준다"""
    set_at = reference_times(rows)
    if not set_at:
        return []
    released: List[int] = []

    def mutate(current: Any) -> Dict[str, Any]:
        state = _clean(current)
        for key, entry in state['axes'].items():
            when = set_at.get(int(entry['axis']))
            if entry.get('pending') and when is not None and when > float(entry['cleared_at']):
                entry['pending'] = False
                entry['reference_set_at'] = when
                released.append(int(entry['axis']))
        return state

    if not Path(path).is_file():
        return []
    store.update_json(path, mutate, default=None)
    return sorted(released)


def reference_times(rows: Iterable[Any]) -> Dict[int, float]:
    """줄 → {축: 기준점 지정 시각} · 같은 축 줄이 여럿이면 가장 이른 것(하나라도 옛 값이면 옛 값)"""
    out: Dict[int, float] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        axis = _axis(row)
        if axis is None:
            continue
        when = _float(row.get(REFERENCE_SET_AT_FIELD))
        when = 0.0 if when is None else when
        out[axis] = min(out.get(axis, when), when)
    return out


def pending_axes(state: Mapping[str, Any]) -> List[int]:
    return sorted(int(entry['axis']) for entry in _clean(state)['axes'].values() if entry.get('pending'))


def stale_axes(state: Mapping[str, Any], rows: Iterable[Any]) -> List[int]:
    """지금 매핑에서 · 클리어한 적 있는 축인데 기준점이 그 전에 지정된(또는 시각 없는) 줄 · 「사용」 줄만"""
    cleared = {int(entry['axis']): float(entry['cleared_at']) for entry in _clean(state)['axes'].values()}
    if not cleared:
        return []
    found = set()
    for row in rows or ():
        if not isinstance(row, Mapping) or row.get('enabled') is False:
            continue
        axis = _axis(row)
        if axis is None or axis not in cleared:
            continue
        when = _float(row.get(REFERENCE_SET_AT_FIELD))
        if when is None or when <= cleared[axis]:
            found.add(axis)
    return sorted(found)


def blocked_axes(state: Mapping[str, Any], rows: Optional[Iterable[Any]] = None) -> List[int]:
    return sorted(set(pending_axes(state)) | set(stale_axes(state, rows or ())))


def message_for(axes: Iterable[int]) -> str:
    axes = sorted(set(int(axis) for axis in axes))
    if not axes:
        return ''
    return f'{" · ".join(f"{axis}번" for axis in axes)} {BLOCK_SUFFIX}'


def block_reason(state: Mapping[str, Any], rows: Optional[Iterable[Any]] = None) -> str:
    """막을 이유 · 막지 않으면 빈 글 · 재생 계획 · 웹 브리지 · 화면이 같은 글"""
    return message_for(blocked_axes(state, rows))


def summary(state: Mapping[str, Any], rows: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """웹 상태 · 「확인할 일」 · 기준점 화면"""
    clean = _clean(state)
    pending = pending_axes(clean)
    stale = stale_axes(clean, rows or ())
    return {
        'pending_axes': pending,
        'stale_axes': stale,
        'blocked_axes': sorted(set(pending) | set(stale)),
        'message': message_for(set(pending) | set(stale)),
        'entries': [dict(entry) for _key, entry in sorted(clean['axes'].items(), key=lambda item: int(item[0]))],
    }


def _axis(row: Mapping[str, Any]) -> Optional[int]:
    value = row.get('motor_axis')
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None
