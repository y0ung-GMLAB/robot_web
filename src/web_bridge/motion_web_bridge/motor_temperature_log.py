"""직렬 서보 온도 기록 · 1분 요약 CSV · 7일 보관 · 한계 가까움 경고 · 수정 목록 191

발열을 보려고 재생 중에도 남긴다 · 값은 motion_state 의 `motors[].temperature_c`
(motor_manager 가 매 주기 읽음 · 감시 노드가 10 Hz 로 실음) · 서보 한계는 `temperature_limit_c`
(서보에 설정된 값 · 부팅 때 한 번 읽음).

    파일   log/motor_temperature/YYYY-MM-DD.csv (그 PC 의 날짜 · 하루 하나)
    한 줄  1분 · 서보 하나 · time,motor,joint,kind,min_c,max_c,last_c,limit_c
    보관   7일 · 날이 바뀔 때와 시작 때 지난 파일을 지운다
    경고   한계 - 10 °C 이상 → 1건 · 한계 - 12 °C 아래로 내려가야 다음 경고 (오르내림에 여러 번 안 적음)

온도가 없는 축(AC · 통신 끊김)은 적지 않는다 · 1분 동안 값이 하나도 없으면 그 줄이 없다.
디스크 일은 1분에 한 번 · 몇 줄 붙이기라 상태 콜백 안에서 한다.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from motion_common.values import optional_int

HEADER = 'time,motor,joint,kind,min_c,max_c,last_c,limit_c\n'
RETENTION_DAYS = 7
INTERVAL_SEC = 60
WARN_MARGIN_C = 10.0
CLEAR_MARGIN_C = 12.0
_DAY_FILE = re.compile(r'^(\d{4}-\d{2}-\d{2})\.csv$')


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None   # NaN 제외


def _text(value: Optional[float]) -> str:
    if value is None:
        return ''
    return str(int(value)) if float(value).is_integer() else f'{value:.1f}'


def _csv_field(value: str) -> str:
    value = str(value or '')
    if any(ch in value for ch in ',"\n'):
        return '"' + value.replace('"', '""') + '"'
    return value


class MotorTemperatureLog:
    def __init__(
        self,
        log_dir: Path,
        *,
        retention_days: int = RETENTION_DAYS,
        interval_sec: float = INTERVAL_SEC,
        clock: Callable[[], float] = time.time,
        on_warning: Optional[Callable[[Dict[str, Any]], None]] = None,
        logger: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.retention_days = int(retention_days)
        self.interval_sec = float(interval_sec)
        self.clock = clock
        self.on_warning = on_warning
        self.logger = logger
        self._lock = threading.Lock()
        #: 지금 모으는 분의 시작 시각(초) · None = 아직 없음
        self._bucket_start: Optional[float] = None
        #: 축 → {min, max, last, limit, kind, joint}
        self._bucket: Dict[int, Dict[str, Any]] = {}
        #: 경고 중인 축
        self._warned: Dict[int, bool] = {}
        self._pruned_day = ''

    # ------------------------------------------------------------------ #
    def observe(self, payload: Dict[str, Any], joint_names: Optional[Callable[[], Dict[int, str]]] = None) -> None:
        """motion_state 한 번 · 분이 바뀌면 지난 분을 적는다."""
        motors = payload.get('motors') if isinstance(payload, dict) else None
        if not isinstance(motors, list):
            return
        now = float(self.clock())
        start = now - (now % self.interval_sec)
        warnings: List[Dict[str, Any]] = []
        flush: Optional[tuple] = None
        with self._lock:
            if self._bucket_start is not None and start != self._bucket_start and self._bucket:
                flush = (self._bucket_start, self._bucket)
                self._bucket = {}
            self._bucket_start = start
            for motor in motors:
                if not isinstance(motor, dict):
                    continue
                axis = optional_int(motor.get('controller_index'), None)
                temp = _number(motor.get('temperature_c'))
                if axis is None or temp is None:
                    continue
                limit = _number(motor.get('temperature_limit_c'))
                row = self._bucket.get(axis)
                if row is None:
                    row = self._bucket[axis] = {
                        'min': temp, 'max': temp, 'last': temp,
                        'kind': str(motor.get('motor_type') or ''),
                        'joint': str(motor.get('motion_id') or '').strip(),
                    }
                row['min'] = min(row['min'], temp)
                row['max'] = max(row['max'], temp)
                row['last'] = temp
                row['limit'] = limit
                warning = self._warning_change(axis, temp, limit, motor)
                if warning:
                    warnings.append(warning)
        if flush:
            self._write(flush[0], flush[1], joint_names)
        if warnings and self.on_warning:
            names = self._names(joint_names) if joint_names else {}
            for warning in warnings:
                warning['joint'] = names.get(warning['axis']) or warning['joint']
                self.on_warning(warning)

    def _warning_change(self, axis: int, temp: float, limit: Optional[float], motor: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if limit is None or limit <= 0:
            return None
        warned = self._warned.get(axis, False)
        if not warned and temp >= limit - WARN_MARGIN_C:
            self._warned[axis] = True
            return {
                'axis': axis, 'temperature_c': temp, 'limit_c': limit,
                'joint': str(motor.get('motion_id') or '').strip(),
                'name': str(motor.get('display_name') or f'{axis}번 모터'),
            }
        if warned and temp < limit - CLEAR_MARGIN_C:
            self._warned[axis] = False
        return None

    # ------------------------------------------------------------------ #
    def _names(self, joint_names: Optional[Callable[[], Dict[int, str]]]) -> Dict[int, str]:
        if joint_names is None:
            return {}
        try:
            return dict(joint_names() or {})
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            return {}

    def _write(self, start: float, bucket: Dict[int, Dict[str, Any]], joint_names) -> None:
        moment = datetime.fromtimestamp(start).astimezone()
        day = moment.strftime('%Y-%m-%d')
        stamp = moment.strftime('%Y-%m-%d %H:%M')
        names = self._names(joint_names)
        lines = []
        for axis in sorted(bucket):
            row = bucket[axis]
            joint = names.get(axis) or row.get('joint') or ''
            lines.append(','.join([
                stamp, str(axis), _csv_field(joint), _csv_field(row.get('kind', '')),
                _text(row['min']), _text(row['max']), _text(row['last']), _text(row.get('limit')),
            ]) + '\n')
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / f'{day}.csv'
            new = not path.exists()
            with path.open('a', encoding='utf-8', newline='') as handle:
                if new:
                    handle.write(HEADER)
                handle.writelines(lines)
        except OSError as exc:
            self._warn(f'[모터 온도 기록] 쓰기 실패 · {exc}')
            return
        if day != self._pruned_day:
            self._pruned_day = day
            self.prune(moment)

    def _warn(self, text: str) -> None:
        try:
            if self.logger:
                self.logger().warning(text)
        except Exception:   # 기록 실패가 상태 콜백을 멈추지 않게
            pass

    # ------------------------------------------------------------------ #
    def prune(self, now: Optional[datetime] = None) -> List[str]:
        """보관 기간(오늘 포함 7일)보다 오래된 날 파일을 지운다 · 지운 이름."""
        now = now or datetime.fromtimestamp(float(self.clock())).astimezone()
        oldest = (now - timedelta(days=self.retention_days - 1)).strftime('%Y-%m-%d')
        removed = []
        for path in self._day_files():
            if _DAY_FILE.match(path.name).group(1) < oldest:
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError:
                    pass
        return removed

    def _day_files(self) -> List[Path]:
        if not self.log_dir.is_dir():
            return []
        return sorted(p for p in self.log_dir.iterdir() if p.is_file() and not p.is_symlink() and _DAY_FILE.match(p.name))

    def days(self) -> Dict[str, Any]:
        """내려받기 목록 · 최신 날이 위."""
        items = []
        for path in reversed(self._day_files()):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            items.append({'date': _DAY_FILE.match(path.name).group(1), 'file': path.name, 'size_bytes': size})
        return {'success': True, 'retention_days': self.retention_days, 'interval_sec': self.interval_sec, 'days': items}

    def file_path(self, date: str) -> Path:
        """그 날 파일 · 이름 검사 · 없으면 ValueError (라우트가 400)."""
        name = f'{str(date or "").strip()}.csv'
        if not _DAY_FILE.match(name):
            raise ValueError('날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)')
        path = self.log_dir / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'{date} 온도 기록이 없습니다')
        return path
