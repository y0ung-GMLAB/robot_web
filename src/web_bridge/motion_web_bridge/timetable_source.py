"""시간표 재생 · 연동 노드에 줄 이 PC 의 칸 · 수정 목록 186 (2026-11-09)

연동 노드는 로컬 상태(50 ms)에 아래를 받아 시간표에 쓴다 · 2 s 에 한 번만 파일을 본다(상태 조회는 가볍게).

- `schedule_items` · 이 PC 스케줄 항목 · 마스터가 묶음에 실어 모든 PC 에 준다(운영시간 입력은 마스터 한 곳)
- `motion_playlist` · 재생 등록된 애니메이션 목록 · 스피커 음원 · 표시
- `cycle_need_sec` · (가장 긴 애니메이션 + 초기 이동 시간) · 마스터가 모든 PC 값으로 자동 회차 간격을 정한다
- `initial_move_sec` · 이 PC 조인트 매핑의 초기 이동 시간(가장 긴 것) · 시간표 초기 이동 예약
- `timezone` · 이 PC 시간대 이름(IANA · 예 America/New_York) · 마스터와 다르면 표시(재생은 그대로)

애니메이션 길이 · 파일 끝 줄(JSONL `[frame, time_sec, …]`)만 읽는다 · 25 MB 파일도 끝 64 KB · 파일이 바뀌지 않으면
다시 읽지 않는다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

#: 다시 보는 간격
REFRESH_SEC = 2.0
#: 끝 줄을 찾으려고 읽는 양
TAIL_BYTES = 65536
#: 조인트 매핑에 초기 이동 시간이 없을 때 · 런타임 기본(5 s)
DEFAULT_INITIAL_MOVE_SEC = 5.0


def local_timezone_name(etc: Path = Path('/etc')) -> str:
    """이 PC 시간대 · /etc/timezone → /etc/localtime 링크 → 약어(%Z) 순 · 운영시간은 이 시간대로 읽는다"""
    try:
        name = (etc / 'timezone').read_text(encoding='utf-8').strip()
        if name:
            return name
    except OSError:
        pass
    link = os.path.realpath(str(etc / 'localtime'))
    if 'zoneinfo/' in link:
        return link.split('zoneinfo/', 1)[1]
    return time.strftime('%Z')


def motion_duration_sec(path: Path) -> float:
    """애니메이션 파일 길이(초) · 끝 줄의 time_sec · 못 읽으면 0"""
    try:
        with open(path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - TAIL_BYTES, 0))
            tail = handle.read().decode('utf-8', errors='ignore')
    except OSError:
        return 0.0
    for line in reversed(tail.splitlines()):
        line = line.strip().rstrip(',')
        if not line.startswith('['):
            continue
        try:
            row = json.loads(line)
            return max(float(row[1]), 0.0)
        except (ValueError, TypeError, IndexError):
            continue
    return 0.0


def playlist_of(mapping: Any) -> List[str]:
    """재생 목록 · `motion_runtime.registered_motion_file.playlist_from_mapping` 과 같은 규칙"""
    if not isinstance(mapping, dict):
        return []
    raw = mapping.get('motion_playlist')
    if isinstance(raw, list):
        items = [str(item or '').strip() for item in raw]
        items = [item for item in items if item]
        if items:
            return items
    single = str(mapping.get('motion_file_id') or '').strip()
    return [single] if single else []


def initial_move_of(mapping: Any) -> float:
    """조인트 매핑 줄의 초기 이동 시간 중 가장 긴 것 · 없으면 런타임 기본"""
    values: List[float] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'initial_move_time_sec':
                    try:
                        values.append(float(item))
                    except (TypeError, ValueError):
                        pass
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(mapping)
    values = [value for value in values if value > 0.0]
    return max(values) if values else DEFAULT_INITIAL_MOVE_SEC


class TimetableSource:
    """브리지 하나에 하나 · `fields()` 를 로컬 상태에 섞는다"""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._cache: Optional[tuple] = None
        self._durations: Dict[str, tuple] = {}
        # 한 번에 하나만 다시 읽는다 · 읽는 동안 다른 요청은 지난 값 · 수정 목록 188
        self._refresh_lock = threading.Lock()

    def fields(self) -> Dict[str, Any]:
        """로컬 상태(50 ms · 제한 300 ms)에 섞는다 · 이 함수는 기다리지 않는다 · 수정 목록 188

        전에는 2 s 마다 부른 요청이 그 자리에서 다 읽었다(get_project · 약 0.5 s) · 웹 일꾼 2개가
        같이 읽어 2 s 마다 시간 초과 2번 · 디스크가 느린 순간 4번이 되어 1.5 s 판정을 넘고
        PC 가 그룹에서 빠졌다(NY 2026-11-09 00:48:26 floating1 · 00:50:12 floating3).
        """
        cache = self._cache
        if cache is not None and time.monotonic() - cache[0] < REFRESH_SEC:
            return cache[1]
        if not self._refresh_lock.acquire(blocking=False):
            return cache[1] if cache is not None else {}
        try:
            try:
                value = self._read()
            except Exception:  # noqa: BLE001 · 못 읽으면 칸을 빼고 보낸다 · 연동 노드는 지난 값을 쓴다
                value = {}
            self._cache = (time.monotonic(), value)
            return value
        finally:
            self._refresh_lock.release()

    def _read(self) -> Dict[str, Any]:
        bridge = self._bridge
        repository = getattr(bridge, 'project_repository', None)
        workspace = Path(getattr(bridge, 'workspace_root', None) or Path.cwd())
        project_id = repository.selected_project_id() if repository is not None else ''
        fields: Dict[str, Any] = {'timezone': local_timezone_name()}
        if not project_id:
            return fields
        from motion_common.schedule_store import ScheduleStore
        store = ScheduleStore(projects_dir=str(workspace / 'motion_projects'), current_project_id=project_id)
        fields['schedule_items'] = [item.to_dict() for item in store.list_schedules()]
        # 등록된 매핑 이름만 · get_project 는 화면용(트리 · 파일 해시 · YAML)이라 0.5 s · 수정 목록 188
        mapping_id = str(repository.active_file_name(project_id, 'motion_axis_matching') or '').strip()
        if not mapping_id:
            return fields
        mapping_path = repository.export_path(project_id, 'motion_axis_matching', mapping_id)
        mapping = yaml.safe_load(Path(mapping_path).read_text(encoding='utf-8')) or {}
        playlist = playlist_of(mapping)
        fields['motion_playlist'] = playlist
        initial = initial_move_of(mapping)
        fields['initial_move_sec'] = initial
        longest = 0.0
        for name in playlist:
            try:
                path = Path(repository.export_path(project_id, 'motions', name))
                stamp = path.stat().st_mtime_ns
            except (OSError, ValueError):
                continue
            cached = self._durations.get(str(path))
            if cached is None or cached[0] != stamp:
                cached = (stamp, motion_duration_sec(path))
                self._durations[str(path)] = cached
            longest = max(longest, cached[1])
        if longest > 0.0:
            fields['cycle_need_sec'] = longest + initial
        return fields
