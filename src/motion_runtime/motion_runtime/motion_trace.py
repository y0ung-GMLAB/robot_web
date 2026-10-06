"""회차별 모션 기록 · 목표 위치와 실제 위치를 CSV 로 남긴다.

재생 루프가 하는 일은 **리스트에 한 줄 붙이기**뿐이다 · 실제 위치 해석,
모션 각도 환산, 오차 계산, 파일 쓰기는 전용 쓰기 스레드가 한다 · 루프 안에서
디스크를 만지면 20ms 박자가 흔들린다.

실제 위치는 `motion_state`(10Hz)가 아니라 모터 노드의 `motor_status`(1kHz)
에서 받는다 · 10Hz 로는 20ms 샘플 다섯 개에 한 번만 바뀌어 계단이 된다. 구독은
직렬화된 바이트(`raw=True`)만 받아 두고, 해석은 쓰기 스레드에서 한다.

저장 · `<프로젝트>/logs/motion_trace/<YYYY-MM-DD>/`

    HHMMSS_c0001_<모션파일>.csv    회차 하나 · time_sec 과 축마다 target/actual/error
    index.jsonl                    회차마다 한 줄 · 파일 이름, 결과, 축별 최대·RMS 오차

값은 **조인트 deg** · 모터 실제 위치를 조인트 매핑의 변환식으로 되돌린 값이다 ·
사람이 열어 보는 파일이라 칸 이름(`_deg`)대로 deg 로 쓴다 · 재생 안쪽 값은 rad 라
쓰기 직전에만 바꾼다(수정 목록 6).
오차는 같은 줄의 목표와 실제의 차이 · 명령 한 틱 지연이 포함된다.
"""

from __future__ import annotations

import json
import math
import queue
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from motion_common import joint_mapping, store, units
from motion_common.values import finite_float

TRACE_DIRNAME = 'motion_trace'
INDEX_FILENAME = 'index.jsonl'
#: 정리(`prune`)는 **새 회차 기록이 쓰일 때만** 돈다 (쓰기 스레드 · 60초 간격) ·
#: 재생이 없는 동안은 지우지 않는다 · 상한 안이라 유지 · 수정 목록 21-4
DEFAULT_RETENTION_DAYS = 14
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
#: 실제 위치가 이보다 오래되면 비워 둔다 · 모터 노드가 멈춘 것이다
DEFAULT_STALE_SEC = 0.2
PRUNE_INTERVAL_SEC = 60.0

Decoder = Callable[[Any], Dict[int, float]]


def joint_from_motor(row: Mapping[str, Any], motor_rad: float) -> Optional[float]:
    """motion_run_rules._motor_target 의 역 · 모터 rad → 조인트 rad · 식은 `joint_mapping` 하나."""
    return joint_mapping.joint_from_motor(row, motor_rad, units.RAD)


def _safe_stem(value: Any) -> str:
    text = re.sub(r'[^0-9A-Za-z가-힣._-]+', '_', Path(str(value or 'motion')).stem).strip('._-')
    return text[:60] or 'motion'


@dataclass
class TraceAxis:
    motion_id: str
    motor_axis: int
    row: Dict[str, Any]


@dataclass
class CycleTrace:
    """한 회차 · 재생 루프는 `add` 만 부른다."""

    directory: Path
    meta: Dict[str, Any]
    axes: List[TraceAxis]
    status_source: Callable[[], Tuple[Any, float]]
    rows: List[tuple] = field(default_factory=list)
    #: 재생 루프 마감 초과 · 늦은 프레임 · 최대 지연 · 건너뜀 · 수정 목록 12-2
    timing: Dict[str, Any] = field(default_factory=dict)

    def add(self, sample: Mapping[str, Any]) -> None:
        raw, raw_at = self.status_source()
        self.rows.append((
            float(sample.get('time_sec') or 0.0),
            sample.get('positions') or {},
            sample.get('motion_values') or {},
            raw,
            raw_at,
            time.monotonic(),
        ))


class MotionTraceRecorder:
    def __init__(
        self,
        *,
        decode: Decoder,
        logger: Any = None,
        enabled: bool = True,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        stale_sec: float = DEFAULT_STALE_SEC,
    ) -> None:
        self.enabled = bool(enabled)
        self.decode = decode
        self.logger = logger
        self.retention_days = max(int(retention_days), 1)
        self.max_bytes = max(int(max_bytes), 1024 * 1024)
        self.stale_sec = float(stale_sec)
        # 튜플 한 번 바꿔 끼우기는 원자적이다 · 1kHz 콜백에 락을 두지 않는다
        self._latest: Tuple[Any, float] = (None, 0.0)
        self._queue: 'queue.Queue[Optional[Tuple[CycleTrace, str, str]]]' = queue.Queue()
        self._last_prune: Dict[Path, float] = {}
        self._thread = threading.Thread(target=self._writer_loop, name='motion_trace_writer', daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ #
    # 재생 쪽 · 가벼워야 한다

    def on_motor_status(self, raw: Any) -> None:
        self._latest = (raw, time.monotonic())

    def latest(self) -> Tuple[Any, float]:
        return self._latest

    def begin(self, plan: Mapping[str, Any], cycle_number: int, project_dir: Path) -> Optional[CycleTrace]:
        if not self.enabled:
            return None
        if str(plan.get('request_source') or '') == 'motion_studio':
            return None   # 스튜디오 미리보기·녹화는 운영 기록이 아니다
        axes = [
            TraceAxis(str(axis['motion_id']), int(axis['motor_axis']), dict(axis.get('row') or {}))
            for axis in plan.get('axes') or []
        ]
        if not axes:
            return None
        started_at = time.time()
        stamp = datetime.fromtimestamp(started_at).astimezone()
        directory = Path(project_dir) / 'logs' / TRACE_DIRNAME / stamp.strftime('%Y-%m-%d')
        meta = {
            'started_at': started_at,
            'started_text': stamp.isoformat(timespec='seconds'),
            'cycle': int(cycle_number),
            'project_id': str(plan.get('project_id') or ''),
            'motion_file_id': str(plan.get('motion_file_id') or ''),
            'mapping_file_id': str(plan.get('mapping_file_id') or ''),
            'request_source': str(plan.get('request_source') or ''),
            'run_mode': str(plan.get('run_mode') or ''),
            'repeat_mode': str(plan.get('repeat_mode') or ''),
            'automation_run': bool(plan.get('automation_run')),
            'group_execution': bool(plan.get('group_execution')),
            'execution_id': str(plan.get('execution_id') or ''),
            'period_sec': float((plan.get('summary') or {}).get('period_sec') or 0.02),
            'planned_duration_sec': float((plan.get('summary') or {}).get('duration_sec') or 0.0),
        }
        return CycleTrace(directory, meta, axes, self.latest)

    def finish(self, trace: Optional[CycleTrace], result: str, message: str = '') -> None:
        if trace is None or not self.enabled:
            return
        trace.meta['finished_at'] = time.time()
        self._queue.put((trace, str(result), str(message or '')))

    def close(self, timeout_sec: float = 5.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout_sec)

    # ------------------------------------------------------------------ #
    # 쓰기 스레드

    def _log(self, level: str, text: str) -> None:
        if self.logger is not None:
            getattr(self.logger, level, self.logger.info)(text)

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            trace, result, message = item
            try:
                self.write(trace, result, message)
                self.prune(trace.directory.parent)
            except Exception as exc:  # noqa: BLE001 · 기록 실패가 쓰기 스레드를 죽이면 다음 회차부터 안 남는다
                self._log('warning', f'motion trace write failed: {exc}')

    def _actual(self, raw: Any, raw_at: float, now: float, cache: Dict[int, Dict[int, float]]) -> Dict[int, float]:
        if raw is None or now - raw_at > self.stale_sec:
            return {}
        key = id(raw)
        if key not in cache:
            try:
                cache[key] = self.decode(raw)
            except Exception:  # noqa: BLE001 · 깨진 상태 한 개는 그 줄의 실제값만 비운다
                cache[key] = {}
        return cache[key]

    def build(self, trace: CycleTrace) -> Tuple[List[str], List[List[str]], List[Dict[str, Any]], int]:
        """(헤더, 행, 축 요약, 실제값 없는 행 수)."""
        header = ['time_sec']
        for axis in trace.axes:
            header += [f'{axis.motion_id}_target_deg', f'{axis.motion_id}_actual_deg', f'{axis.motion_id}_error_deg']
        stats = {axis.motion_id: {'max': 0.0, 'max_at': 0.0, 'sq': 0.0, 'n': 0} for axis in trace.axes}
        cache: Dict[int, Dict[int, float]] = {}
        rows: List[List[str]] = []
        missing = 0
        for time_sec, positions, motion_values, raw, raw_at, now in trace.rows:
            actual_motor = self._actual(raw, raw_at, now, cache)
            if not actual_motor:
                missing += 1
            line = [f'{time_sec:.3f}']
            for axis in trace.axes:
                target = finite_float(motion_values.get(axis.motion_id))
                if target is None and axis.motor_axis in positions:
                    target = joint_from_motor(axis.row, positions[axis.motor_axis])
                actual = (
                    joint_from_motor(axis.row, actual_motor[axis.motor_axis])
                    if axis.motor_axis in actual_motor else None
                )
                # 파일은 deg · 여기서만 바꾼다
                target = None if target is None else units.rad_to_deg(target)
                actual = None if actual is None else units.rad_to_deg(actual)
                error = actual - target if actual is not None and target is not None else None
                if error is not None:
                    s = stats[axis.motion_id]
                    if abs(error) > s['max']:
                        s['max'], s['max_at'] = abs(error), time_sec
                    s['sq'] += error * error
                    s['n'] += 1
                line += [
                    '' if target is None else f'{target:.4f}',
                    '' if actual is None else f'{actual:.4f}',
                    '' if error is None else f'{error:.4f}',
                ]
            rows.append(line)
        summary = []
        for axis in trace.axes:
            s = stats[axis.motion_id]
            summary.append({
                'motion_id': axis.motion_id,
                'motor_axis': axis.motor_axis,
                'gear_ratio': finite_float(axis.row.get('gear_ratio')) or 1.0,
                'invert': bool(axis.row.get('invert')),
                'max_abs_error_deg': round(s['max'], 4) if s['n'] else None,
                'max_abs_error_at_sec': round(s['max_at'], 3) if s['n'] else None,
                'rms_error_deg': round(math.sqrt(s['sq'] / s['n']), 4) if s['n'] else None,
            })
        return header, rows, summary, missing

    def write(self, trace: CycleTrace, result: str, message: str = '') -> Path:
        header, rows, summary, missing = self.build(trace)
        meta = trace.meta
        stamp = datetime.fromtimestamp(meta['started_at']).astimezone()
        name = f"{stamp.strftime('%H%M%S')}_c{meta['cycle']:04d}_{_safe_stem(meta['motion_file_id'])}.csv"
        path = trace.directory / name
        suffix = 1
        while path.exists():
            suffix += 1
            path = trace.directory / name.replace('.csv', f'_{suffix}.csv')
        content = '\n'.join(','.join(line) for line in [header] + rows) + '\n'
        store.atomic_write_text(path, content, fsync=False)

        record = {
            **meta,
            'file': path.name,
            'result': result,
            'message': message,
            'sample_count': len(rows),
            'duration_sec': round(float(rows[-1][0]) if rows else 0.0, 3),
            'actual_missing_samples': missing,
            'timing': dict(trace.timing),
            'axes': summary,
        }
        index = trace.directory / INDEX_FILENAME
        with store.locked_update(index):
            with index.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        return path

    def prune(self, root: Path, *, force: bool = False) -> None:
        """보존 기간이 지난 날짜를 지우고, 전체가 상한을 넘으면 오래된 CSV 부터 지운다."""
        now = time.monotonic()
        if not force and now - self._last_prune.get(root, -PRUNE_INTERVAL_SEC) < PRUNE_INTERVAL_SEC:
            return
        self._last_prune[root] = now
        if not root.is_dir():
            return
        cutoff = (datetime.now().astimezone() - timedelta(days=self.retention_days)).strftime('%Y-%m-%d')
        days = sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name))
        for day in days:
            if day.name < cutoff:
                shutil.rmtree(day, ignore_errors=True)
        files = sorted(
            (p for p in root.glob('*/*.csv') if p.is_file() and not p.is_symlink()),
            key=lambda p: (p.parent.name, p.name),
        )
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= self.max_bytes:
                break
            total -= path.stat().st_size
            path.unlink(missing_ok=True)
