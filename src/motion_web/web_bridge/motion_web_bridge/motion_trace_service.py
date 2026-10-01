"""회차별 모션 기록 조회 · motion_runtime 이 쓴 파일을 읽어 웹에 넘긴다.

쓰는 쪽은 `motion_runtime.motion_trace` 하나다 · 여기서는 읽기만 한다 (지우기 제외).

    <프로젝트>/logs/motion_trace/<YYYY-MM-DD>/index.jsonl   회차 요약
    <프로젝트>/logs/motion_trace/<YYYY-MM-DD>/*.csv         회차 기록

두 프로세스가 같은 PC 의 같은 디스크를 보므로 ROS 를 거치지 않는다.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from motion_common.paths import NO_PROJECT_SELECTED

TRACE_DIRNAME = 'motion_trace'
INDEX_FILENAME = 'index.jsonl'
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_FILE = re.compile(r'^[0-9A-Za-z가-힣._-]+\.csv$')
#: 그래프에 보낼 최대 점 수 · 넘으면 고르게 솎는다 (CSV 내려받기는 원본 그대로)
MAX_CHART_POINTS = 3000


class MotionTraceService:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    # ------------------------------------------------------------------ #

    def _root(self) -> Tuple[str, Optional[Path]]:
        project_id = str(self.repository.selected_project_id() or '')
        if not project_id:
            return '', None
        return project_id, Path(self.repository.project_logs_dir(project_id)) / TRACE_DIRNAME

    def _day_dir(self, root: Path, date: Any) -> Path:
        text = str(date or '').strip()
        if not _DATE.match(text):
            raise ValueError('날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)')
        day = root / text
        if day.is_symlink() or not day.is_dir():
            raise ValueError(f'그 날짜의 기록이 없습니다: {text}')
        return day

    def file_path(self, date: Any, file_name: Any) -> Path:
        _project_id, root = self._root()
        if root is None:
            raise ValueError(NO_PROJECT_SELECTED)
        day = self._day_dir(root, date)
        name = str(file_name or '').strip()
        if not _FILE.match(name) or name != Path(name).name:
            raise ValueError('기록 파일 이름이 올바르지 않습니다')
        path = day / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'기록 파일이 없습니다: {name}')
        return path

    @staticmethod
    def _records(day: Path) -> List[Dict[str, Any]]:
        index = day / INDEX_FILENAME
        records = []
        try:
            lines = index.read_text(encoding='utf-8').splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                record['file_exists'] = (day / str(record.get('file') or '')).is_file()
                records.append(record)
        return records

    # ------------------------------------------------------------------ #

    def days(self) -> Dict[str, Any]:
        project_id, root = self._root()
        if root is None:
            return {'success': True, 'message': NO_PROJECT_SELECTED, 'project_id': '', 'days': []}
        days = []
        if root.is_dir():
            for day in sorted((p for p in root.iterdir() if p.is_dir() and _DATE.match(p.name)), reverse=True):
                files = [p for p in day.glob('*.csv') if p.is_file()]
                days.append({
                    'date': day.name,
                    'cycle_count': len(self._records(day)),
                    'file_count': len(files),
                    'bytes': sum(p.stat().st_size for p in files),
                })
        return {
            'success': True,
            'project_id': project_id,
            'directory': str(root),
            'days': days,
            'total_bytes': sum(day['bytes'] for day in days),
        }

    def runs(self, date: Any) -> Dict[str, Any]:
        project_id, root = self._root()
        if root is None:
            return {'success': True, 'message': NO_PROJECT_SELECTED, 'project_id': '', 'runs': []}
        try:
            day = self._day_dir(root, date)
        except ValueError as exc:
            return {'success': True, 'message': str(exc), 'project_id': project_id, 'date': str(date), 'runs': []}
        records = sorted(self._records(day), key=lambda r: float(r.get('started_at') or 0.0), reverse=True)
        return {'success': True, 'project_id': project_id, 'date': day.name, 'runs': records}

    def trace(self, date: Any, file_name: Any) -> Dict[str, Any]:
        """그래프용 · 축마다 target/actual 열 · 많으면 솎아 낸다."""
        path = self.file_path(date, file_name)
        with path.open(encoding='utf-8', newline='') as handle:
            rows = list(csv.reader(handle))
        if not rows:
            raise ValueError('빈 기록 파일입니다')
        header, data = rows[0], rows[1:]
        step = max(1, -(-len(data) // MAX_CHART_POINTS))

        def number(text: str) -> Optional[float]:
            try:
                return float(text) if text != '' else None
            except ValueError:
                return None

        picked = data[::step]
        if data and picked[-1] is not data[-1]:
            picked.append(data[-1])
        columns = {name: [number(row[i]) if i < len(row) else None for row in picked] for i, name in enumerate(header)}
        axes = []
        for name in header:
            if name.endswith('_target_deg'):
                motion_id = name[: -len('_target_deg')]
                axes.append({
                    'motion_id': motion_id,
                    'target': columns.get(f'{motion_id}_target_deg', []),
                    'actual': columns.get(f'{motion_id}_actual_deg', []),
                    'error': columns.get(f'{motion_id}_error_deg', []),
                })
        record = next(
            (r for r in self._records(path.parent) if r.get('file') == path.name),
            None,
        )
        return {
            'success': True,
            'date': path.parent.name,
            'file': path.name,
            'sample_count': len(data),
            'decimation': step,
            'time': columns.get('time_sec', []),
            'axes': axes,
            'record': record,
        }

    def delete_day(self, date: Any) -> Dict[str, Any]:
        project_id, root = self._root()
        if root is None:
            raise ValueError(NO_PROJECT_SELECTED)
        day = self._day_dir(root, date)
        shutil.rmtree(day)
        return {'success': True, 'message': f'{day.name} 모션 기록을 삭제했습니다', **self.days()}
