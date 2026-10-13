"""부팅 시 적용값 · 지금 도는 모터 프로그램이 쓴 값 vs 지금 설정이면 쓸 값 · 수정 목록 116 (실물 2026-10-13)

motor_manager 는 켜질 때마다 세션 파일(`runtime/sessions/motor-<sha>.yaml`)의 드라이버 `param_file` 을
읽어 SDO 로 쓴다 · 세션은 마지막 「적용」 때 고정된다 · 그래서 **업데이트 + 서비스 재시작만으로는
새 공통 설정(`config/minas_base.yaml`)이 안 들어갔다** (floating4 · 세션의 `param_file` 이 아직 플랫폼
`param/minas.yaml` · Pr5.12 50 · Pr4.37 0) · 그런데 화면 「부팅 시 적용값」 은 지금 설정으로 계산한 새 값을
보여 줘 드라이브가 그 값인 줄 알았다.

    지금 도는 값(running)   모터 프로그램이 켜질 때 남긴 기록(`<세션>.boot.json` · `service_entrypoint.motor_main`) ·
                            기록이 없으면(옛 버전이 켠 것) 세션이 가리키는 param 파일을 지금 읽은 값
    적용하면 쓸 값(expected) 지금 모터 설정 + 공통 설정으로 만든 부팅 목록(`minas_params.boot_values`)
    다르면                  「설정 적용 필요 · 지금 드라이브는 옛 부팅 값」 · 「장비에 적용」 이 param 파일을
                            다시 만들고(`MotorConfigService.apply`) 모터 프로그램을 다시 켠다

자동으로 세션을 다시 만들지 않는 이유 · 세션을 새로 만들려면 모터 설정 파일을 registry 로 다시 저장해야
하고(param 경로가 설정 파일 안에 있다), 그것은 운전 한계 · 프로파일까지 다시 쓰는 「적용」 과 같은 일이다 ·
사람이 없는 부팅 때 확인 없이 드라이브 값을 바꾸지 않는다 · 대신 알리고 버튼 하나로 고친다.

param 경로 규칙은 motor_manager 와 같다(`motor_manager.cpp` · 절대경로 그대로 · 상대경로는 설정 파일
폴더 기준 · 확장자가 .yaml/.yml 이 아니면 `<경로>/<driver type>.yaml`).

순수 계산 + 파일 읽기만 · rclpy 없음 · 시험은 이것을 본다.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from motion_common.values import optional_int

from motion_web_bridge import drive_params, minas_params

Key = Tuple[int, int]
Values = Dict[Key, int]

#: 객체 → 매뉴얼 번호(Pr4.37 · 0x607F) · 고급 표와 같은 이름
LABELS: Dict[Key, str] = {(row[3], row[4]): row[2] for row in drive_params.CATALOG}


def expected_for(workspace_root: Path, motors: Any) -> Callable[[List[int]], Dict[int, Values]]:
    """registry 모터 목록 → `expected(축 목록)` · 적용하면 쓸 값(플랫폼 → 공통 설정 → 모터 칸)"""
    by_axis = {
        optional_int(motor.get('axis')): motor
        for motor in motors or []
        if isinstance(motor, dict) and optional_int(motor.get('axis')) is not None
    }

    def build(axes: List[int]) -> Dict[int, Values]:
        return {
            axis: minas_params.boot_values(Path(workspace_root), minas_params.param_overrides(by_axis[axis]))
            for axis in axes
            if axis in by_axis
        }

    return build

#: 세션 파일 옆에 남기는 기록 · `motor-<sha>.yaml` → `motor-<sha>.boot.json`
SNAPSHOT_SUFFIX = '.boot.json'
STALE_MESSAGE = '설정 적용 필요 · 지금 드라이브는 옛 부팅 값'


def snapshot_path(config_file: Path) -> Path:
    path = Path(config_file)
    return path.with_name(path.stem + SNAPSHOT_SUFFIX)


def resolve_param_path(config_file: Path, param_file: Any, driver_type: str) -> Path:
    """motor_manager 와 같은 규칙으로 param 파일 위치"""
    path = Path(str(param_file or ''))
    if not path.is_absolute():
        path = Path(config_file).parent / path
    if path.suffix not in ('.yaml', '.yml'):
        path = path / f'{driver_type}.yaml'
    return path


def document_values(document: Any) -> Values:
    """param 문서의 items → (index, subindex) → 값"""
    values: Values = {}
    items = document.get('items') if isinstance(document, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or 'index' not in item:
            continue
        value = optional_int(item.get('value'))
        if value is None:
            continue
        values[(int(item.get('index') or 0), int(item.get('subindex') or 0))] = value
    return values


def session_values(config_file: Path) -> Dict[int, Dict[str, Any]]:
    """설정 파일(세션 · 프로젝트 모터 설정 둘 다)의 MINAS 축마다 · param 파일을 지금 읽은 값

    축 → {driver_id · param_file · values(못 읽으면 None) · error}
    """
    config_file = Path(config_file)
    payload = yaml.safe_load(config_file.read_text(encoding='utf-8')) or {}
    drivers = {
        optional_int(driver.get('id')): driver
        for driver in payload.get('drivers') or []
        if isinstance(driver, dict)
    }
    axes: Dict[int, Dict[str, Any]] = {}
    for master in payload.get('masters') or []:
        if not isinstance(master, dict):
            continue
        for slave in master.get('slaves') or []:
            if not isinstance(slave, dict):
                continue
            axis = optional_int(slave.get('controller_index'))
            driver = drivers.get(optional_int(slave.get('driver_id')))
            if axis is None or driver is None or str(driver.get('type') or '') != 'minas':
                continue
            param_path = resolve_param_path(config_file, driver.get('param_file'), 'minas')
            entry: Dict[str, Any] = {
                'driver_id': optional_int(driver.get('id')),
                'param_file': str(param_path),
                'values': None,
                'error': '',
            }
            try:
                entry['values'] = document_values(yaml.safe_load(param_path.read_text(encoding='utf-8')))
            except (OSError, yaml.YAMLError) as exc:
                entry['error'] = str(exc)
            axes[axis] = entry
    return axes


def _key_text(key: Key) -> str:
    return f'0x{key[0]:04X}:{key[1]}'


def _parse_key(text: str) -> Key:
    index, _, sub = str(text).partition(':')
    return int(index, 0), int(sub or '0', 0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_snapshot(config_file: Path, *, now: Optional[float] = None) -> Path:
    """모터 프로그램이 켜지는 순간 · 이번에 드라이브에 쓸 값을 세션 옆에 남긴다 · `motor_main` 이 부른다"""
    config_file = Path(config_file)
    axes = session_values(config_file)
    payload = {
        'version': 1,
        'config_file': str(config_file),
        'config_sha256': _sha256(config_file),
        'started_at': time.time() if now is None else float(now),
        'axes': {
            str(axis): {
                'driver_id': entry['driver_id'],
                'param_file': entry['param_file'],
                'error': entry['error'],
                'values': None if entry['values'] is None else {
                    _key_text(key): value for key, value in sorted(entry['values'].items())
                },
            }
            for axis, entry in sorted(axes.items())
        },
    }
    target = snapshot_path(config_file)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    temporary.replace(target)
    return target


def read_snapshot(config_file: Path) -> Optional[Dict[str, Any]]:
    """이 세션 내용으로 켰을 때의 기록 · 없거나 다른 세션 것이면 None"""
    config_file = Path(config_file)
    try:
        payload = json.loads(snapshot_path(config_file).read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or payload.get('version') != 1:
            return None
        if payload.get('config_sha256') != _sha256(config_file):
            return None
        axes = {}
        for axis_text, entry in (payload.get('axes') or {}).items():
            values = entry.get('values') if isinstance(entry, dict) else None
            axes[int(axis_text)] = {
                **(entry if isinstance(entry, dict) else {}),
                'values': None if values is None else {
                    _parse_key(key): int(value) for key, value in values.items()
                },
            }
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return None
    return {'started_at': payload.get('started_at'), 'axes': axes}


def running_values(config_file: Path) -> Dict[str, Any]:
    """지금 도는 세션이 드라이브에 쓴 값 · 기록 우선 · 없으면 param 파일을 지금 읽은 값"""
    snapshot = read_snapshot(config_file)
    if snapshot is not None:
        return {'source': 'snapshot', 'started_at': snapshot['started_at'], 'axes': snapshot['axes']}
    return {'source': 'file', 'started_at': None, 'axes': session_values(config_file)}


def differences(
    running: Dict[int, Dict[str, Any]],
    expected: Dict[int, Values],
    labels: Optional[Dict[Key, str]] = None,
) -> List[Dict[str, Any]]:
    """축 · 객체마다 지금 값 ≠ 적용하면 쓸 값 · 지금 값을 못 읽은 축은 통째로 다름"""
    labels = labels or {}
    rows: List[Dict[str, Any]] = []
    for axis in sorted(set(running) | set(expected)):
        want = expected.get(axis)
        if want is None:
            continue   # 이 축은 모터 설정에 MINAS 로 없다 · 판정할 기준이 없다
        entry = running.get(axis) or {}
        have = entry.get('values')
        if have is None:
            rows.append({'axis': axis, 'object': '', 'label': '부팅 목록', 'running': None, 'expected': None,
                         'error': str(entry.get('error') or '지금 도는 설정에 이 모터의 부팅 목록이 없습니다')})
            continue
        for key in sorted(set(have) | set(want)):
            if have.get(key) == want.get(key):
                continue
            rows.append({'axis': axis, 'object': _key_text(key), 'label': labels.get(key, _key_text(key)),
                         'running': have.get(key), 'expected': want.get(key), 'error': ''})
    return rows


def config_differences(
    config_file: Path,
    expected: Callable[[List[int]], Dict[int, Values]],
) -> List[Dict[str, Any]]:
    """모터 설정 파일(프로젝트 것)이 가리키는 param 파일이 지금 설정과 다른가 · 「적용」 이 다시 만들지 정한다"""
    axes = session_values(Path(config_file))
    return differences(axes, expected(sorted(axes)), LABELS)


def describe(rows: List[Dict[str, Any]], limit: int = 4) -> str:
    """사람이 읽을 한 줄 · 「1번 Pr4.37 0 → 150 · …」"""
    parts = []
    for row in rows[:limit]:
        if row['object']:
            have = '없음' if row['running'] is None else row['running']
            want = '없음' if row['expected'] is None else row['expected']
            parts.append(f"{row['axis']}번 {row['label']} {have} → {want}")
        else:
            parts.append(f"{row['axis']}번 {row['error']}")
    more = len(rows) - limit
    return ' · '.join(parts) + (f' 외 {more}개' if more > 0 else '')


def _unknown(exc: BaseException) -> Dict[str, Any]:
    return {'state': 'unknown', 'message': f'부팅 값을 확인하지 못했습니다 · {exc}', 'differences': [],
            'source': '', 'started_at': None, 'running': {}}


def status(
    config_file: Optional[Path],
    expected: Callable[[List[int]], Dict[int, Values]],
    labels: Optional[Dict[Key, str]] = None,
) -> Dict[str, Any]:
    """화면 · 상태 한 장 · state = none(적용된 세션 없음) · ok · stale · unknown(읽기 실패)

    `expected(축 목록)` → 축마다 적용하면 쓸 값 · MINAS 가 아니거나 모르는 축은 빼고 준다
    """
    if config_file is None:
        return {'state': 'none', 'message': '', 'differences': [], 'source': '', 'started_at': None, 'running': {}}
    try:
        running = running_values(Path(config_file))
        rows = differences(running['axes'], expected(sorted(running['axes'])), labels)
    except Exception as exc:  # noqa: BLE001 - 파일 · yaml · 설정 읽기 · 무엇이든 「모름」 으로 · 상태 한 칸이 화면을 막지 않게
        return _unknown(exc)
    return {
        'state': 'stale' if rows else 'ok',
        'message': STALE_MESSAGE if rows else '',
        'detail': describe(rows) if rows else '',
        'differences': rows,
        'source': running['source'],
        'started_at': running['started_at'],
        # 축 → (index, subindex) → 값 · 화면 표(「부팅 시 적용값」)가 쓴다 · JSON 으로 나가지 않는다
        'running': {axis: entry.get('values') for axis, entry in running['axes'].items()},
    }


class BootParamsWatch:
    """브리지가 상태를 낼 때마다 파일을 읽지 않게 · 몇 초 동안 같은 답 · 「적용」 뒤엔 바로 다시 본다"""

    def __init__(
        self,
        *,
        config_file: Callable[[], Optional[Path]],
        expected: Callable[[List[int]], Dict[int, Values]],
        labels: Optional[Dict[Key, str]] = None,
        ttl_sec: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config_file = config_file
        self._expected = expected
        self._labels = labels or {}
        self._ttl = float(ttl_sec)
        self._clock = clock
        self._cached: Optional[Dict[str, Any]] = None
        self._cached_at = 0.0
        self._cached_key: Any = None

    def invalidate(self) -> None:
        self._cached = None

    def _key(self, config_file: Optional[Path]) -> Any:
        if config_file is None:
            return None
        try:
            return str(config_file), snapshot_path(config_file).stat().st_mtime_ns
        except OSError:
            return str(config_file), None

    def status(self) -> Dict[str, Any]:
        try:
            config_file = self._config_file()
        except Exception as exc:  # noqa: BLE001 - 상태 한 칸이 화면 전체를 막지 않게
            return _unknown(exc)
        now = self._clock()
        key = self._key(config_file)
        if self._cached is not None and key == self._cached_key and now - self._cached_at < self._ttl:
            return self._cached
        result = status(None if config_file is None else Path(config_file), self._expected, self._labels)
        self._cached, self._cached_at, self._cached_key = result, now, key
        return result

    def public_status(self) -> Dict[str, Any]:
        """웹 상태에 싣는 몫 · 표용 값은 뺀다"""
        result = dict(self.status())
        result.pop('running', None)
        return result

    def running_for_axis(self, axis: int) -> Optional[Values]:
        """이 축의 「부팅 시 적용값」 · 지금 도는 세션 기준 · 모르면 None"""
        return (self.status().get('running') or {}).get(int(axis))
