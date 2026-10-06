"""프로젝트 백업·복원·휴지통 · 수정 목록 33 (2026-10-06)

전에는 삭제가 영구였고 백업 수단이 없었다 · PC 디스크가 고장 나면 매장 설정
(모터·조인트 매핑·애니메이션·스케줄)을 전부 잃었다.

    내려받기   프로젝트 폴더 → zip 하나 (기록·휴지통·계산 캐시 제외)
    올려 복원  zip → 프로젝트 · 로봇 팩 올리기와 같은 검사(`..`·절대 경로·링크·크기)
               같은 ID 가 있으면 확인 뒤 덮어쓰기 · 덮이는 쪽은 휴지통으로
    휴지통     삭제 = `.trash/projects/<ID>-<시각>/` 로 옮김 · 7일 뒤 자동 삭제 · 되살리기
"""

from __future__ import annotations

import io
import json
import os
import shutil
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .robot_pack_service import unpack_zip

TRASH_DIR = Path('.trash') / 'projects'
TRASH_KEEP_SEC = 7 * 24 * 3600

#: 프로젝트 안에서 백업하지 않는 것 · 기록·휴지통은 크고 다시 생긴다
SKIP_TOP_DIRS = {'logs', 'trash'}
#: `runtime/` 은 실행 중 상태라 대부분 뺀다 · 사람이 정한 설정과 이력만
RUNTIME_KEEP = ('motion_automation.json', 'history')


def _included(relative: Path) -> bool:
    parts = relative.parts
    if not parts or parts[0] in SKIP_TOP_DIRS:
        return False
    if parts[0] == 'runtime':
        return len(parts) > 1 and parts[1] in RUNTIME_KEEP
    return True


def export_project_zip(project_dir: Path) -> bytes:
    """폴더 → zip · 맨 위 폴더 이름 = 프로젝트 ID · 링크는 따라가지 않는다."""
    project_dir = Path(project_dir)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(project_dir.rglob('*')):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(project_dir)
            if not _included(relative):
                continue
            archive.write(path, (Path(project_dir.name) / relative).as_posix())
    return buffer.getvalue()


def _manifest(project_dir: Path) -> Dict[str, Any]:
    try:
        payload = json.loads((project_dir / 'project.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('zip 안에 project.json 이 없거나 읽을 수 없습니다') from exc
    if not isinstance(payload, dict) or not str(payload.get('project_id') or '').strip():
        raise ValueError('project.json 에 project_id 가 없습니다')
    return payload


def _valid_id(project_id: str) -> str:
    name = str(project_id or '').strip()
    if not name or name != Path(name).name or name.startswith('.'):
        raise ValueError(f'올바르지 않은 프로젝트 ID 입니다: {project_id}')
    return name


def peek_project_id(data: bytes) -> str:
    """풀기 전에 zip 의 project.json 에서 프로젝트 ID 만 읽는다 · 못 읽으면 빈 글자"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = sorted(
                (name for name in archive.namelist() if name.rstrip('/').endswith('project.json')),
                key=lambda name: name.count('/'),
            )
            if not names:
                return ''
            payload = json.loads(archive.read(names[0]).decode('utf-8'))
    except (zipfile.BadZipFile, KeyError, ValueError, UnicodeDecodeError):
        return ''
    return str(payload.get('project_id') or '').strip() if isinstance(payload, dict) else ''


def move_to_trash(root: Path, project_dir: Path, *, now: Optional[float] = None) -> Path:
    stamp = datetime.fromtimestamp(time.time() if now is None else now).strftime('%Y%m%d-%H%M%S')
    target = Path(root) / TRASH_DIR / f'{project_dir.name}-{stamp}'
    counter = 2
    while target.exists():
        target = target.with_name(f'{project_dir.name}-{stamp}-{counter}')
        counter += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    project_dir.rename(target)
    # 옮긴 시각 = 지운 시각 · 폴더 이름 바꾸기는 제 수정 시각을 안 바꾼다 ·
    # 안 그러면 오래 안 고친 프로젝트가 휴지통에 들어가자마자 정리된다
    stamp_at = time.time() if now is None else now
    os.utime(target, (stamp_at, stamp_at))
    return target


def import_project_zip(root: Path, data: bytes, *, overwrite: bool = False) -> Dict[str, Any]:
    """zip → 프로젝트 · 덮어쓸 때는 지금 것을 휴지통으로 · {'project_id', 'replaced_to'}"""
    root = Path(root)
    incoming = root / f'.importing-{uuid.uuid4().hex}'
    try:
        problems = unpack_zip(data, incoming)
        if problems:
            raise ValueError('zip 검사 실패 · ' + ' / '.join(problems))
        manifest = _manifest(incoming)
        project_id = _valid_id(manifest['project_id'])
        destination = root / project_id
        replaced_to = None
        if destination.exists() or destination.is_symlink():
            if not overwrite:
                raise FileExistsError(project_id)
            if destination.is_symlink():
                raise ValueError('같은 이름의 프로젝트 폴더가 링크라 덮어쓸 수 없습니다')
            replaced_to = move_to_trash(root, destination)
        incoming.rename(destination)
        return {'project_id': project_id, 'replaced_to': str(replaced_to) if replaced_to else ''}
    finally:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)


def list_trash(root: Path) -> List[Dict[str, Any]]:
    folder = Path(root) / TRASH_DIR
    if not folder.is_dir() or folder.is_symlink():
        return []
    entries = []
    for path in sorted(folder.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            manifest = json.loads((path / 'project.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            manifest = {}
        manifest = manifest if isinstance(manifest, dict) else {}
        entries.append({
            'entry': path.name,
            'project_id': str(manifest.get('project_id') or ''),
            'name': str(manifest.get('name') or manifest.get('project_id') or path.name),
            'deleted_at': path.stat().st_mtime,
        })
    return entries


def restore_from_trash(root: Path, entry: str) -> str:
    root = Path(root)
    name = _valid_id(entry)
    source = root / TRASH_DIR / name
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f'휴지통에 없습니다: {entry}')
    project_id = _valid_id(_manifest(source)['project_id'])
    destination = root / project_id
    if destination.exists():
        raise ValueError(f'같은 ID 의 프로젝트가 이미 있습니다: {project_id} · 그것을 지우거나 이름을 바꾼 뒤 되살리세요')
    source.rename(destination)
    return project_id


def prune_trash(root: Path, *, keep_sec: float = TRASH_KEEP_SEC, now: Optional[float] = None,
                remove: Callable[[Path], None] = shutil.rmtree) -> List[str]:
    """7일 지난 휴지통 항목을 지운다 · 지운 항목 이름 목록"""
    folder = Path(root) / TRASH_DIR
    if not folder.is_dir() or folder.is_symlink():
        return []
    current = time.time() if now is None else now
    removed = []
    for path in folder.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        if current - path.stat().st_mtime > keep_sec:
            remove(path)
            removed.append(path.name)
    return removed
