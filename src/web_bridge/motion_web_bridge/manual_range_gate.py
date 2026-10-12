"""수동 조작 · 조인트 범위를 사람이 확인한 뒤에만 · 수정 목록 97 (사용자 결정 2026-10-12)

재생·초기 이동은 재생 계획(`plan_builder`)이 막는다 · 수동 조작은 계획을 안 거쳐
여기서 막는다 · 대상은 사람이 모터를 움직이는 명령 전부(조그 · 다이얼 · 절대 이동 ·
범위 복구 · 페이더) · 정지·서보 켜고 끄기·알람 해제·기준점 캡처(위치만 읽음)는 아니다.

**최대한 보수적으로** (사용자 2026-10-12 「가급적이면 최대한 안전하고 보수적으로」)

    PC 전체   저장된 매핑 · 적용된 매핑 어느 쪽이든 「사용」 줄 하나라도 범위 미확인 → 전부 거절
    축 하나   「사용」 매핑 줄에 연결 안 된 모터 → 거절 (범위를 모르는 모터)
    모름      프로젝트 없음 · 매핑 없음 · 매핑을 못 읽음 → 거절

판정 규칙 자체는 `motion_common.joint_mapping` 하나 · 재생 계획·상단 칸과 같다.
그래서 설치 순서는 · 범위(스펙·CAD 값)를 넣고 「범위 확인」 → 저장 → 조그로
정면 → 기준점 캡처 → 저장 → 「장비에 적용 · 모터 재시작」.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from motion_common import joint_mapping
from motion_common import motor_ref as motor_ref_rules
from motion_common.values import optional_int

PREFIX = '수동 조작 불가 · '


def _rows_of(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get('mappings')
    if rows is None:
        rows = payload.get('axes')
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _row_axes(row: Dict[str, Any], motors: List[Dict[str, Any]]) -> List[int]:
    """이 줄이 움직이는 모터 번호 · 재생과 같이 `motor_ref` 가 우선 · 없으면 옛 `motor_axis`"""
    ref = str(row.get('motor_ref') or '').strip()
    if ref and motors:
        return [
            axis for axis in (
                optional_int(motor.get('controller_index'), None)
                for motor in motor_ref_rules.motors_for_ref(ref, motors)
            ) if axis is not None
        ]
    axis = optional_int(row.get('motor_axis'), None)
    return [] if axis is None else [axis]


def mapped_axes(rows: List[Dict[str, Any]], motors: List[Dict[str, Any]]) -> set:
    """「사용」 줄이 연결된 모터 번호"""
    axes = set()
    for row in rows:
        if row.get('enabled') is False or not str(row.get('motion_id') or '').strip():
            continue
        axes.update(_row_axes(row, motors))
    return axes


def block_reason(
    saved_rows: List[Dict[str, Any]],
    applied_rows: List[Dict[str, Any]],
    motors: List[Dict[str, Any]],
    axis: Optional[int] = None,
) -> str:
    """막을 이유 · 빈 글자면 통과 · 순수 계산(시험은 이것을 본다)"""
    for rows in (saved_rows, applied_rows):
        reason = joint_mapping.range_block_reason(rows)
        if reason:
            return PREFIX + reason
    if axis is not None and axis not in mapped_axes(saved_rows, motors):
        return (
            f'{PREFIX}{axis}번 모터는 조인트 매핑의 「사용」 줄에 없습니다 · '
            '범위를 모르는 모터는 손으로도 움직이지 않습니다 · 조인트 매핑에서 연결하고 범위를 넣으세요'
        )
    return ''


class ManualRangeGate:
    """브리지에 하나 · 저장된 매핑 파일은 바뀌었을 때만 다시 읽는다"""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._lock = threading.Lock()
        self._file_key: Optional[Tuple[str, int, int]] = None
        self._file_rows: List[Dict[str, Any]] = []
        # 마지막 전체 판정 · 페이더 목표(초당 수십 번)는 이것으로 축만 본다
        self._last: Tuple[str, List[Dict[str, Any]]] = ('조인트 매핑 확인 전', [])

    def _saved_rows(self, project_id: str) -> List[Dict[str, Any]]:
        repository = self._bridge.project_repository
        project = repository.get_project(project_id).get('project') or {}
        mapping_id = str((project.get('active_files') or {}).get('motion_axis_matching') or '').strip()
        if not mapping_id:
            raise ValueError('조인트 매핑이 없습니다 · 모터 관리에서 조인트 매핑을 만들고 범위를 넣으세요')
        path = Path(repository.export_path(project_id, 'motion_axis_matching', mapping_id))
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if key == self._file_key:
                return [dict(row) for row in self._file_rows]
        rows = _rows_of(yaml.safe_load(path.read_text(encoding='utf-8')) or {})
        with self._lock:
            self._file_key = key
            self._file_rows = rows
        return [dict(row) for row in rows]

    def _applied_rows(self, project_id: str) -> List[Dict[str, Any]]:
        context_service = getattr(self._bridge, '_execution_context', None)
        loader = getattr(self._bridge, '_monitoring_mapping_rows_for_context', None)
        if context_service is None or not callable(loader):
            return []
        return loader(context_service.status(validate_files=False), project_id)

    def _motors(self) -> List[Dict[str, Any]]:
        state = self._bridge.motion_state()
        motors = state.get('motors') if isinstance(state, dict) else None
        return [motor for motor in motors if isinstance(motor, dict)] if isinstance(motors, list) else []

    def block_reason(self, axis: Any = None) -> str:
        """조그·다이얼·절대 이동·범위 복구·페이더 연결 때 · 파일·상태를 새로 본다"""
        axis_value = optional_int(axis, None)
        try:
            project_id = self._bridge.project_repository.require_selected_project_id()
            saved = self._saved_rows(project_id)
            applied = self._applied_rows(project_id)
            motors = self._motors()
        except Exception as exc:  # noqa: BLE001 · 모르면 막는다(보수적)
            reason = f'{PREFIX}조인트 범위를 확인할 수 없습니다 ({exc})'
            with self._lock:
                self._last = (reason, [])
            return reason
        reason = block_reason(saved, applied, motors)
        with self._lock:
            self._last = (reason, saved)
        if reason or axis_value is None:
            return reason
        return block_reason(saved, [], motors, axis_value)

    def cached_axis_reason(self, axis: Any) -> str:
        """페이더 목표 하나 · 마지막 전체 판정(0.5초마다 새로 봄)과 축 연결만"""
        with self._lock:
            reason, saved = self._last
        if reason:
            return reason
        axis_value = optional_int(axis, None)
        if axis_value is None:
            return f'{PREFIX}모터 번호가 없습니다'
        return block_reason(saved, [], self._motors(), axis_value)
