"""로봇 팩 업로드 · 검사 · 교체 · 되돌리기 · 순수 모듈 (노드 비의존)

PC 1대 = 로봇 1대 · 팩은 프로젝트가 아니라 PC 전역 `<workspace>/robot_pack/`.
이전 팩 1개는 `robot_pack.prev/` 로 남겨 되돌릴 수 있다.

    zip 받기 → 크기·경로 검사 → robot_pack.incoming/ 에 풀기
    → 형식 검사 (motion_common.robot_pack) → 실행기 로드 검사 (sim_run.py --check)
    → 전부 통과해야 교체 (prev 삭제 · current → prev · incoming → current)

하나라도 실패하면 **교체하지 않는다** · 이유 목록을 그대로 돌려준다.
모터 설정·조인트 매핑은 건드리지 않는다 (PC 에서 직접 작성 · 차이는 표시만).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional

import yaml

from motion_common import robot_pack
from motion_common.store import atomic_write_json

PREV_DIRNAME = robot_pack.PACK_DIRNAME + '.prev'
INCOMING_DIRNAME = robot_pack.PACK_DIRNAME + '.incoming'

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_FILES = 2000
CHECK_TIMEOUT_S = 180.0          # 처음 한 번은 uv 가 mujoco 를 받는다
#: macOS 압축기가 끼워 넣는 찌꺼기 · 팩 내용이 아니다
_IGNORED_PREFIXES = ('__MACOSX/',)

_LOCK = threading.Lock()

Checker = Callable[[Path, Path], List[str]]


# --------------------------------------------------------------------------- #
# 상태
# --------------------------------------------------------------------------- #

def _describe(pack_dir: Path) -> Optional[Dict[str, Any]]:
    if not pack_dir.is_dir():
        return None
    entry: Dict[str, Any] = dict(robot_pack.read_pack_info(pack_dir))
    installed = robot_pack.read_installed(pack_dir)
    for key in ('uploaded_at', 'fingerprint', 'warnings'):
        if key in installed:
            entry[key] = installed[key]
    return entry


def pack_status(workspace_root: Path) -> Dict[str, Any]:
    """화면용 · 지금 팩과 이전 팩 (없으면 None)."""
    workspace_root = Path(workspace_root)
    return {
        'success': True,
        'current': _describe(robot_pack.pack_root(workspace_root)),
        'previous': _describe(workspace_root / PREV_DIRNAME),
        'limits': {'max_zip_bytes': MAX_ZIP_BYTES},
    }


# --------------------------------------------------------------------------- #
# zip
# --------------------------------------------------------------------------- #

def _member_problem(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if '\\' in name:
        return f'경로에 \\ 포함: {name}'
    if name.startswith('/') or (len(name) > 1 and name[1] == ':'):
        return f'절대 경로: {name}'
    if any(part == '..' for part in PurePosixPath(name).parts):
        return f'상위 폴더(..) 경로: {name}'
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        return f'링크 파일: {name}'
    if info.flag_bits & 0x1:
        return f'암호 걸린 항목: {name}'
    return ''


def _members(archive: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    return [
        info for info in archive.infolist()
        if not info.is_dir() and not info.filename.startswith(_IGNORED_PREFIXES)
    ]


def _common_root(names: List[str]) -> str:
    """모든 항목이 폴더 하나 아래면 그 폴더 · 아니면 ''."""
    tops = {PurePosixPath(name).parts[0] for name in names}
    if len(tops) == 1 and all(len(PurePosixPath(n).parts) > 1 for n in names):
        return tops.pop() + '/'
    return ''


def unpack_zip(data: bytes, destination: Path) -> List[str]:
    """검사 후 풀기 · 문제 목록 (비면 성공) · 문제가 있으면 아무것도 쓰지 않는다."""
    if len(data) > MAX_ZIP_BYTES:
        return [f'zip 크기 초과: {len(data) / 1e6:.1f} MB > {MAX_ZIP_BYTES / 1e6:.0f} MB']
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return ['zip 파일이 아님']
    with archive:
        members = _members(archive)
        if not members:
            return ['zip 이 비어 있음']
        problems = [p for p in (_member_problem(info) for info in archive.infolist()) if p]
        if len(members) > MAX_FILES:
            problems.append(f'파일 수 초과: {len(members)} > {MAX_FILES}')
        total = sum(info.file_size for info in members)
        if total > MAX_UNPACKED_BYTES:
            problems.append(f'풀린 크기 초과: {total / 1e6:.1f} MB > {MAX_UNPACKED_BYTES / 1e6:.0f} MB')
        if problems:
            return problems
        root = _common_root([info.filename for info in members])
        destination.mkdir(parents=True)
        written = 0
        for info in members:
            relative = info.filename[len(root):]
            target = destination.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, 'wb') as sink:
                while True:
                    chunk = source.read(1 << 20)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UNPACKED_BYTES:   # 머리말을 속인 zip
                        return [f'풀린 크기 초과: > {MAX_UNPACKED_BYTES / 1e6:.0f} MB']
                    sink.write(chunk)
    return []


# --------------------------------------------------------------------------- #
# 실행기 로드 검사
# --------------------------------------------------------------------------- #

def _uv() -> Optional[str]:
    found = shutil.which('uv')
    if found:
        return found
    fallback = Path.home() / '.local' / 'bin' / ('uv.exe' if os.name == 'nt' else 'uv')
    return str(fallback) if fallback.is_file() else None


def run_checker(workspace_root: Path, pack_dir: Path) -> List[str]:
    """`scripts/sim/sim_run.py --check` · model.xml 로드 + 축 이름 대조."""
    script = Path(workspace_root) / 'scripts' / 'sim' / 'sim_run.py'
    if not script.is_file():
        return [f'실행기 없음: {script}']
    uv = _uv()
    if uv is None:
        return [
            '실행기 로드 검사 불가: uv 없음 (~/.local/bin/uv)',
            '설치: 터미널에서 bash scripts/install.sh 다시 실행 · 또는 curl -LsSf https://astral.sh/uv/install.sh | sh',
        ]
    args = [
        uv, 'run', '--no-project', '--with=mujoco', '--with=numpy', '--with=pyyaml',
        'python', str(script), '--check', str(pack_dir),
    ]
    try:
        done = subprocess.run(
            args, cwd=str(script.parent), capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=CHECK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return [f'실행기 로드 검사 시간 초과 ({CHECK_TIMEOUT_S:.0f} s)']
    except OSError as exc:
        return [f'실행기 로드 검사 실행 실패: {exc}']
    if done.returncode == 0:
        return []
    lines = [line.strip() for line in (done.stdout or '').splitlines() if line.strip()]
    if not lines:
        tail = [line.strip() for line in (done.stderr or '').splitlines() if line.strip()]
        lines = tail[-3:] or [f'실행기 로드 검사 실패 (코드 {done.returncode})']
    return lines


# --------------------------------------------------------------------------- #
# 교체 · 되돌리기
# --------------------------------------------------------------------------- #

def _remove(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def install_pack(
    workspace_root: Path,
    data: bytes,
    *,
    checker: Optional[Checker] = None,
    now: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    """zip 하나로 팩 교체 · 실패하면 지금 팩 그대로."""
    workspace_root = Path(workspace_root)
    checker = checker or run_checker
    current = robot_pack.pack_root(workspace_root)
    previous = workspace_root / PREV_DIRNAME
    incoming = workspace_root / INCOMING_DIRNAME
    if not _LOCK.acquire(blocking=False):
        return {'success': False, 'message': '다른 팩 업로드가 진행 중입니다', 'errors': []}
    try:
        _remove(incoming)
        errors = unpack_zip(data, incoming)
        report = robot_pack.PackReport()
        if not errors:
            report = robot_pack.inspect_pack(incoming)
            errors = list(report.errors)
        if not errors:
            errors = checker(workspace_root, incoming)
        if errors:
            _remove(incoming)
            return {
                'success': False,
                'message': '로봇 팩 거부 · 지금 팩 유지',
                'errors': errors,
            }
        info = robot_pack.read_pack_info(incoming)
        atomic_write_json(incoming / robot_pack.INSTALLED_NAME, {
            **info,
            'uploaded_at': datetime.fromtimestamp(now()).astimezone().isoformat(timespec='seconds'),
            'fingerprint': robot_pack.pack_fingerprint(incoming),
            'warnings': report.warnings,
        })
        _remove(previous)
        if current.exists():
            current.rename(previous)
        incoming.rename(current)
    finally:
        _LOCK.release()
    status = pack_status(workspace_root)
    label = ' '.join(filter(None, (info.get('name'), info.get('version'))))
    return {
        **status,
        'success': True,
        'message': f'로봇 팩 교체: {label} · 기존 MuJoCo 결과는 다시 계산 필요',
        'errors': [],
        'warnings': report.warnings,
    }


def rollback_pack(workspace_root: Path) -> Dict[str, Any]:
    """지금 팩 ↔ 이전 팩 맞바꾸기."""
    workspace_root = Path(workspace_root)
    current = robot_pack.pack_root(workspace_root)
    previous = workspace_root / PREV_DIRNAME
    swap = workspace_root / (robot_pack.PACK_DIRNAME + '.swap')
    if not previous.is_dir():
        return {'success': False, 'message': '되돌릴 이전 팩이 없습니다'}
    if not _LOCK.acquire(blocking=False):
        return {'success': False, 'message': '다른 팩 작업이 진행 중입니다'}
    try:
        _remove(swap)
        if current.exists():
            current.rename(swap)
        previous.rename(current)
        if swap.exists():
            swap.rename(previous)
    finally:
        _LOCK.release()
    status = pack_status(workspace_root)
    label = ' '.join(filter(None, ((status['current'] or {}).get(k) for k in ('name', 'version'))))
    return {**status, 'success': True, 'message': f'이전 로봇 팩으로 되돌림: {label}'}


# --------------------------------------------------------------------------- #
# 조인트 매핑과의 차이 (표시만)
# --------------------------------------------------------------------------- #

def _close(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


def mapping_diff(workspace_root: Path, mapping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """팩 robot.yaml ↔ PC 조인트 매핑 · motion_id · 감속·기어비 · 범위 · 적용하지 않는다."""
    try:
        robot = robot_pack.load_robot(robot_pack.pack_root(workspace_root))
    except ValueError:
        return {'success': True, 'available': False, 'message': '검사를 통과한 로봇 팩이 없습니다', 'rows': []}
    rows_in = (mapping or {}).get('mappings') or (mapping or {}).get('axes') or []
    by_id = {str(row.get('motion_id')): row for row in rows_in if isinstance(row, dict)}
    rows = []
    for axis in robot.axes:
        row = by_id.pop(axis.motion_id, None)
        entry: Dict[str, Any] = {
            'joint': axis.joint,
            'motion_id': axis.motion_id,
            'pack_ratio': axis.ratio,
            'pack_range': list(axis.range_deg),
            'differences': [],
        }
        if row is None:
            entry['differences'].append('조인트 매핑에 motion_id 없음')
        else:
            ratio = row.get('gear_ratio', 1.0)
            span = [row.get('motion_lower_deg', -180.0), row.get('motion_upper_deg', 180.0)]
            entry.update(mapping_ratio=ratio, mapping_range=span)
            if not _close(ratio, axis.ratio):
                entry['differences'].append('감속·기어비')
            if not (_close(span[0], axis.range_deg[0]) and _close(span[1], axis.range_deg[1])):
                entry['differences'].append('범위')
        rows.append(entry)
    for motion_id, row in by_id.items():
        rows.append({
            'joint': '',
            'motion_id': motion_id,
            'mapping_ratio': row.get('gear_ratio', 1.0),
            'mapping_range': [row.get('motion_lower_deg', -180.0), row.get('motion_upper_deg', 180.0)],
            'differences': ['팩에 motion_id 없음'],
        })
    return {'success': True, 'available': True, 'rows': rows}


def active_mapping_diff(workspace_root: Path, repository) -> Dict[str, Any]:
    """선택된 프로젝트의 **등록된** 조인트 매핑과 비교 · 없으면 그 사실만."""
    project_id = repository.selected_project_id()
    name = repository.active_file_name(project_id, 'motion_axis_matching') if project_id else ''
    if not name:
        result = mapping_diff(workspace_root, None)
        result['mapping_file'] = ''
        return result
    try:
        content = repository.read_file(project_id, 'motion_axis_matching', name)['content']
        mapping = yaml.safe_load(content)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return {'success': False, 'message': f'조인트 매핑 읽기 실패: {exc}', 'rows': []}
    result = mapping_diff(workspace_root, mapping if isinstance(mapping, dict) else None)
    result['mapping_file'] = name
    return result
