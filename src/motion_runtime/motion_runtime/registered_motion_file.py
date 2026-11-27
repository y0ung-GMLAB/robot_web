"""재생 등록 칸만 따로 읽고 쓴다 · §6-160

조인트 매칭 파일 하나에 **주인이 셋**이다.

    mappings        조인트 매핑 화면
    midi_banks      MIDI 입력 설정 화면
    motion_file_id  모션 실행 화면 (재생 등록)

MIDI 는 오래전에 제 길을 얻었다 (`midi_bank_store`) · 재생 등록만 남아서
「설정 전체 저장」 길로 다녔다 · 그래서 모션 파일 하나 바꾸려는 사람이
조인트 매핑을 통째로 덮어쓰게 됐고, 편집 중이면 그마저 막혔다.

여기서는 **그 한 칸만** 건드린다 · 나머지 글자는 손대지 않는다 · 편집 중인
조인트 매핑이 있어도 그 위를 지나가지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from motion_common import store as common_store

from motion_runtime.midi_bank_store import _top_level_key_span, atomic_write_with_backup


#: 재생 목록 최대 길이 · 실수로 수천 개가 들어가 시작 때 계획 생성이 멈추지 않게
MAX_PLAYLIST_LENGTH = 50


def load_registered_motion_file(mapping_file: Path) -> str:
    root = yaml.safe_load(mapping_file.read_text(encoding='utf-8')) or {}
    if not isinstance(root, dict):
        raise ValueError('motion-axis mapping YAML root must be an object')
    return str(root.get('motion_file_id') or '').strip()


def playlist_from_mapping(root: Any) -> list:
    """재생 목록 · 2026-10-06 · 수정 목록 35

    `motion_playlist: [A, B, C]` 가 있으면 그것 · 없으면 옛 파일처럼
    `motion_file_id` 하나를 목록으로 · 둘 다 없으면 빈 목록.
    `motion_file_id` 는 늘 목록 첫 항목이라 옛 읽는 곳은 그대로 첫 애니를 본다.
    """
    if not isinstance(root, dict):
        return []
    raw = root.get('motion_playlist')
    if isinstance(raw, list):
        items = [str(item or '').strip() for item in raw]
        items = [item for item in items if item]
        if items:
            return items
    single = str(root.get('motion_file_id') or '').strip()
    return [single] if single else []


def normalize_playlist(playlist: Any) -> list:
    """화면이 보낸 목록 · 빈 칸 버림 · 같은 파일 여러 번은 허용(순서대로 두 번 재생)."""
    if playlist is None:
        return []
    if not isinstance(playlist, (list, tuple)):
        raise ValueError('motion_playlist must be a list')
    items = [str(item or '').strip() for item in playlist]
    items = [item for item in items if item]
    if len(items) > MAX_PLAYLIST_LENGTH:
        raise ValueError(f'재생 목록은 {MAX_PLAYLIST_LENGTH}개까지입니다')
    for item in items:
        if '/' in item or '\\' in item or not item.lower().endswith('.json'):
            raise ValueError(f'재생 목록 항목이 올바르지 않습니다: {item}')
    return items


def load_registered_playlist(mapping_file: Path) -> list:
    root = yaml.safe_load(mapping_file.read_text(encoding='utf-8')) or {}
    if not isinstance(root, dict):
        raise ValueError('motion-axis mapping YAML root must be an object')
    return playlist_from_mapping(root)


def _remove_top_level_key(existing: str, key: str) -> str:
    span = _top_level_key_span(existing, key)
    if span is None:
        return existing
    start, end = span
    # 줄 끝 개행까지 함께 지운다
    if end < len(existing) and existing[end] == '\n':
        end += 1
    return existing[:start] + existing[end:]


def render_with_playlist(existing: str, playlist: Any) -> str:
    """`motion_file_id` = 첫 항목 · 두 개 이상이면 `motion_playlist` 칸도 둔다.

    하나 이하면 `motion_playlist` 칸을 지워 옛 파일 모양 그대로 둔다 ·
    그래야 플레이리스트를 안 쓰는 현장 파일이 바뀌지 않는다.
    """
    items = normalize_playlist(playlist)
    updated = render_with_registered_motion_file(existing, items[0] if items else '')
    updated = _remove_top_level_key(updated, 'motion_playlist')
    if len(items) <= 1:
        return updated.rstrip() + '\n'
    block = yaml.safe_dump(
        {'motion_playlist': items}, sort_keys=False, allow_unicode=True,
    ).rstrip()
    span = _top_level_key_span(updated, 'motion_file_id')
    if span is None:
        return f'{block}\n{updated.lstrip()}'
    return f'{updated[:span[1]]}\n{block}{updated[span[1]:]}'.rstrip() + '\n'


def save_registered_playlist(
    mapping_file: Path,
    playlist: Any,
    backup_dir: Optional[Path] = None,
) -> Optional[Path]:
    """재생 목록 저장 · 재생 등록과 같은 락 · 같은 좁은 길 (§6-160 · §6-24)."""
    with common_store.locked_update(mapping_file):
        existing = mapping_file.read_text(encoding='utf-8')
        updated = render_with_playlist(existing, playlist)
        if updated == existing:
            return None
        return atomic_write_with_backup(mapping_file, updated, backup_dir)


def render_with_registered_motion_file(existing: str, motion_file_id: Any) -> str:
    """`motion_file_id:` 줄 하나만 갈아 끼운 본문을 돌려준다."""
    root = yaml.safe_load(existing) or {}
    if not isinstance(root, dict):
        raise ValueError('motion-axis mapping YAML root must be an object')

    value = str(motion_file_id or '').strip()
    line = yaml.safe_dump(
        {'motion_file_id': value},
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()

    if 'motion_file_id' in root:
        span = _top_level_key_span(existing, 'motion_file_id')
        if span is None:
            raise ValueError('failed to locate existing motion_file_id')
        start, end = span
        return f'{existing[:start]}{line}{existing[end:]}'.rstrip() + '\n'

    # 칸이 없던 파일 · 이름 뒤가 제자리다 · 없으면 맨 앞에 둔다
    span = _top_level_key_span(existing, 'name')
    if span is None:
        return f'{line}\n{existing.lstrip()}'
    return f'{existing[:span[1]]}\n{line}{existing[span[1]:]}'.rstrip() + '\n'


def save_registered_motion_file(
    mapping_file: Path,
    motion_file_id: Any,
    backup_dir: Optional[Path] = None,
) -> Optional[Path]:
    """다른 쓰는 쪽과 같은 락 안에서 바꾼다 · §6-24

    조인트 매핑 저장과 MIDI 뱅크 저장도 같은 파일을 쓴다 · 읽고-고치고-쓰는
    구간을 통째로 감싸야 서로의 수정을 지우지 않는다.
    """
    with common_store.locked_update(mapping_file):
        existing = mapping_file.read_text(encoding='utf-8')
        updated = render_with_registered_motion_file(existing, motion_file_id)
        if updated == existing:
            return None
        return atomic_write_with_backup(mapping_file, updated, backup_dir)
