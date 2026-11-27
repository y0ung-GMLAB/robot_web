"""시간표 재생 · 연동 노드에 줄 이 PC 의 칸 · 수정 목록 186 (2026-11-09)

연동 노드는 로컬 상태(50 ms)에 아래를 받아 시간표에 쓴다 · 2 s 에 한 번만 파일을 본다(상태 조회는 가볍게).

- `schedule_items` · 이 PC 스케줄 항목 · 마스터가 묶음에 실어 모든 PC 에 준다(운영시간 입력은 마스터 한 곳)
- `motion_playlist` · 재생 등록된 애니메이션 목록 · 스피커 음원 · 표시
- `cycle_need_sec` · 재생 목록 항목마다 (애니메이션 + 그 앞 초기 이동) 중 가장 긴 것 · 마스터가 모든 PC 값으로 자동
  회차 간격을 정한다 · 초기 이동은 재생 관리자와 같은 규칙(`motion_common.timed_cycle.planned_initial_move_sec`) ·
  기준점(기본) · 직접 지정 방식이고 첫 프레임이 초기 위치와 다르면 같은 시간으로 두 번(13-1) · 206 뒤처리
- `initial_move_sec` · 이 PC 조인트 매핑의 초기 이동 시간(가장 긴 것) · 시간표 초기 이동 예약 · 스스로 잇기 ·
  매핑에 없으면 칸을 빼고 보낸다(짐작한 값을 「알려 준 값」 으로 보내지 않는다 · 받는 쪽이 가장 긴 선택지) · 수정 목록 205
- `timezone` · 이 PC 시간대 이름(IANA · 예 America/New_York) · 마스터와 다르면 표시(재생은 그대로)

애니메이션 길이 · 파일 끝 줄(JSONL `[frame, time_sec, …]`)만 읽는다 · 25 MB 파일도 끝 64 KB · 첫 프레임 값은 앞 몇 줄
(기준점 · 직접 지정 줄이 있을 때만) · 파일이 바뀌지 않으면 다시 읽지 않는다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from motion_common import local_clock, motion_table, timed_cycle
from motion_common.timing import initial_move_sec

#: 다시 보는 간격
REFRESH_SEC = 2.0
#: 끝 줄을 찾으려고 읽는 양
TAIL_BYTES = 65536
#: 첫 프레임 값을 찾으며 읽는 행(펼친 조인트 행) 한도 · Blender · 웹 녹화 JSONL 은 첫 줄에 모든 조인트가 있다
FIRST_VALUES_MAX_ROWS = 5000


def local_timezone_name(etc: Path = Path('/etc')) -> str:
    """이 PC 시간대 · /etc/localtime 링크 → /etc/timezone → 약어(%Z) 순 · 운영시간은 이 시간대로 읽는다

    읽는 규칙은 `local_clock.zone_from_etc` 하나 · 화면 시간대와 운영시간 계산이 갈리지 않게 · 수정 목록 221
    """
    return local_clock.zone_from_etc(etc) or time.strftime('%Z')


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


def first_frame_values(path: Path, wanted: Any = None) -> Optional[Dict[str, float]]:
    """조인트마다 첫 프레임 값(관절 rad · 헤더 `rotation_unit` 대로) · 앞부분만 읽는다 · 못 읽으면 None(모름)

    재생 관리자처럼 조인트마다 가장 이른 시각의 값 · 머리 줄 있는 JSON Lines(Blender 내보내기 · 웹 녹화)만 ·
    첫 시각 줄을 지나 `wanted` 를 다 찾았거나 `FIRST_VALUES_MAX_ROWS` 를 넘으면 멈춘다(25 MB 파일도 첫 몇 줄) ·
    그 밖의 모양(CSV · 통짜 JSON)은 None · 쓰는 쪽(`timed_cycle.blends_to_first_frame`)이 길게 잡는다.
    """
    try:
        header = motion_table.jsonl_motion_header(path)
        if header is None:
            return None
        first, headers = header
        scale = motion_table.rotation_unit_scale(motion_table.header_rotation_unit(first))
        want = {str(item) for item in wanted} if wanted is not None else None
        earliest: Dict[str, tuple] = {}
        first_time: Optional[float] = None
        for count, (row, _bad) in enumerate(motion_table.iter_jsonl_rows(path, headers)):
            if count >= FIRST_VALUES_MAX_ROWS:
                break
            if row is None:
                continue
            record, _error = motion_table.parse_row(row, headers)
            if record is None:
                continue
            time_sec = float(record['time_sec'])
            if first_time is None:
                first_time = time_sec
            elif time_sec > first_time and want is not None and want <= set(earliest):
                break
            current = earliest.get(record['motion_id'])
            if current is None or time_sec < current[0]:
                earliest[record['motion_id']] = (time_sec, float(record['value']) * scale)
    except (OSError, ValueError, TypeError):
        return None
    return {motion_id: value for motion_id, (_time, value) in earliest.items()}


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
    """조인트 매핑 줄의 초기 이동 시간 중 가장 긴 것 · 없으면 0(모름)

    전에는 없으면 5 s(`DEFAULT_INITIAL_MOVE_SEC`)를 「이 PC 값」 으로 보냈다 · 연동 노드는 모를 때 10 s 로 짐작해 같은
    「모름」 이 곳마다 달랐다 · 이제 모르면 0 · 쓰는 쪽이 `motion_common.timing.initial_move_sec`(가장 긴 선택지) · 수정 목록 205
    """
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
    return max(values) if values else 0.0


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
        if initial > 0.0:
            fields['initial_move_sec'] = initial
        rows = mapping.get('mappings') if isinstance(mapping, dict) else None
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        # 첫 프레임 값이 필요한 조인트 · 기준점(기본) · 직접 지정 줄만 · 모두 첫 프레임 방식이면(NY) 파일 앞부분도 안 읽는다
        wanted = sorted({
            str(row.get('motion_id') or '').strip() for row in rows
            if row.get('enabled') is not False and str(row.get('motion_id') or '').strip()
            and str(row.get('initial_mode') or timed_cycle.DEFAULT_INITIAL_MODE) in {'reference', 'manual'}
        })
        # 매핑에 초기 이동 시간이 없으면 가장 긴 선택지로 · 자동 회차 간격은 길게 잡는 쪽이 안전 · 수정 목록 205
        move = initial_move_sec(initial)
        need = 0.0
        for name in playlist:
            try:
                path = Path(repository.export_path(project_id, 'motions', name))
                stamp = path.stat().st_mtime_ns
            except (OSError, ValueError):
                continue
            cached = self._durations.get(str(path))
            if cached is None or cached[0] != stamp:
                cached = (stamp, motion_duration_sec(path), {})
                self._durations[str(path)] = cached
            duration, firsts = cached[1], cached[2]
            if duration <= 0.0:
                continue
            key = tuple(wanted)
            if wanted and key not in firsts:
                firsts[key] = first_frame_values(path, wanted)
            # 회차 하나 = 그 클립 앞 초기 이동 + 클립 · 초기 이동은 재생 관리자와 같은 규칙(`timed_cycle`) · 기준점(기본)이고
            # 첫 프레임이 0 이 아니면 같은 시간으로 두 번(13-1) · 전에는 한 번만 세어 자동 간격이 모자랐다 · 206 뒤처리
            blends = bool(wanted) and timed_cycle.blends_to_first_frame(rows, firsts.get(key))
            need = max(need, duration + timed_cycle.planned_initial_move_sec(move, blends))
        if need > 0.0:
            fields['cycle_need_sec'] = need
        return fields
