"""애니메이션 json 의 조인트 값 · 시각을 고르게 맞춰서 · 웹 3D 「Blender 뷰」 용 · 수정 목록 98

재생과 **같은 파서**(motion_table · 헤더 `rotation_unit` 대로 rad 로 · 6-2)로 읽어
조인트마다 같은 시각표(기본 25 fps)에 선형 보간 · 화면은 시각으로 두 점 사이만 보간한다.
9분 나레이션(조인트 20)이면 25 fps 로 약 28만 값 · 파일이 바뀌지 않으면 다시 읽지 않는다.
"""

from __future__ import annotations

import bisect
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

from motion_common import motion_table

DEFAULT_FPS = 25.0
_CACHE: Dict[Tuple[str, int, int, float], Dict[str, Any]] = {}
_LOCK = threading.Lock()
_CACHE_LIMIT = 6


def _interp(times: List[float], values: List[float], at: float) -> float:
    if at <= times[0]:
        return values[0]
    if at >= times[-1]:
        return values[-1]
    index = bisect.bisect_right(times, at)
    t0, t1 = times[index - 1], times[index]
    v0, v1 = values[index - 1], values[index]
    if t1 <= t0:
        return v1
    return v0 + (v1 - v0) * (at - t0) / (t1 - t0)


def joint_values_from_content(content: str, fps: float = DEFAULT_FPS) -> Dict[str, Any]:
    """json 글 → {success, unit:'rad', fps, start_sec, duration_sec, joints:{id:[rad…]}} · 못 읽으면 success False"""
    text = str(content or '')
    try:
        unit = motion_table.normalize_rotation_unit(motion_table.rotation_unit_from_content(text))
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}
    rows, headers, _source, warning = motion_table.extract_rows_from_content(text)
    records = []
    for row in rows:
        record, _error = motion_table.parse_row(row, headers)
        if record is not None:
            records.append(record)
    if not records:
        return {'success': False, 'message': f'애니메이션 행을 찾지 못했습니다{f" · {warning}" if warning else ""}'}
    motion_table.scale_record_values(records, unit)
    groups: Dict[str, List[Tuple[float, float]]] = {}
    for record in records:
        groups.setdefault(str(record['motion_id']), []).append((float(record['time_sec']), float(record['value'])))
    for points in groups.values():
        points.sort()
    start = min(points[0][0] for points in groups.values())
    end = max(points[-1][0] for points in groups.values())
    step = 1.0 / max(1.0, float(fps))
    count = int(round((end - start) / step)) + 1 if end > start else 1
    joints: Dict[str, List[float]] = {}
    for motion_id, points in groups.items():
        times = [p[0] for p in points]
        values = [p[1] for p in points]
        joints[motion_id] = [round(_interp(times, values, start + i * step), 6) for i in range(count)]
    return {
        'success': True,
        'unit': 'rad',
        'fps': float(fps),
        'start_sec': round(start, 6),
        'duration_sec': round(end - start, 6),
        'sample_count': count,
        'joints': joints,
    }


def joint_values_payload(path: Path, fps: float = DEFAULT_FPS) -> Dict[str, Any]:
    """파일 하나 · 이름·크기·수정 시각이 같으면 캐시"""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {'success': False, 'message': f'애니메이션 파일이 없습니다: {path.name}'}
    key = (str(path), stat.st_mtime_ns, stat.st_size, float(fps))
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        content = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        return {'success': False, 'message': f'읽기 실패: {exc}'}
    payload = {**joint_values_from_content(content, fps), 'file_id': path.name}
    if payload.get('success'):
        with _LOCK:
            if len(_CACHE) >= _CACHE_LIMIT:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = payload
    return payload
