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

from motion_common import joint_mapping, manual_speed
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


def axis_gain(rows: List[Dict[str, Any]], motors: List[Dict[str, Any]], axis: int) -> Optional[float]:
    """이 모터를 모는 「사용」 줄의 |이득| · 여러 줄이면 작은 쪽(조인트가 더 빨라지지 않게) · 없으면 None"""
    gains = []
    for row in rows:
        if row.get('enabled') is False or not str(row.get('motion_id') or '').strip():
            continue
        if axis in _row_axes(row, motors):
            value = abs(joint_mapping.gain(row))
            if value > 0.0:
                gains.append(value)
    return min(gains) if gains else None


def axis_rows(rows: List[Dict[str, Any]], motors: List[Dict[str, Any]], axis: int) -> List[Dict[str, Any]]:
    """이 모터를 모는 「사용」 줄들"""
    return [
        row for row in rows
        if row.get('enabled') is not False and str(row.get('motion_id') or '').strip()
        and axis in _row_axes(row, motors)
    ]


def xtouch_limits(
    rows: List[Dict[str, Any]], motors: List[Dict[str, Any]], axis: int,
) -> Tuple[Dict[str, float], str]:
    """X-Touch 상한 · 조인트 매핑 최대 속도·가속도 × |이득| → 모터 rad/s · rad/s² · 수정 목록 156

    웹 페이더·다이얼(조인트 2 °/s)과 달리 X-Touch 는 재생 검사와 같은 상한으로 따라간다
    (사용자 결정 2026-10-18 · 잡기(pickup) 전에는 축이 안 움직여 잘못 찍어도 튀지 않는다) ·
    상한이 빈 줄이면 (빈 dict, 이유) · 여러 줄이면 모터 기준 작은 쪽.
    """
    found = axis_rows(rows, motors, axis)
    if not found:
        return {}, f'{PREFIX}{axis}번 모터는 조인트 매핑의 「사용」 줄에 없습니다.'
    velocity: Optional[float] = None
    acceleration: Optional[float] = None
    for row in found:
        if not joint_mapping.rate_limits_set(row):
            return {}, (
                f'{PREFIX}{row.get("motion_id")} ({axis}번 모터) 속도·가속도 상한을 먼저 채우세요 · '
                'X-Touch 는 조인트 매핑의 최대 속도·가속도로 따라갑니다'
            )
        gain_value = abs(joint_mapping.gain(row)) or 1.0
        row_velocity = float(joint_mapping.rate(row, 'max_velocity')) * gain_value
        row_acceleration = float(joint_mapping.rate(row, 'max_acceleration')) * gain_value
        velocity = row_velocity if velocity is None else min(velocity, row_velocity)
        acceleration = row_acceleration if acceleration is None else min(acceleration, row_acceleration)
    # 상한에 딱 맞추면 녹화 파일이 반올림만으로 재생 검사를 넘는다 · 2 % 아래로
    ratio = manual_speed.XTOUCH_LIMIT_RATIO
    return {
        manual_speed.VELOCITY_FIELD: float(velocity) * ratio,
        manual_speed.ACCELERATION_FIELD: float(acceleration) * ratio,
    }, ''


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
            f'{PREFIX}{axis}번 모터는 조인트 매핑의 「사용」 줄에 없습니다. '
            '범위를 모르는 모터는 수동으로도 움직일 수 없습니다. 조인트 매핑에서 모터를 연결하고 범위를 입력하세요.'
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
            raise ValueError('조인트 매핑이 없습니다. 모터 설정에서 조인트 매핑을 만들고 범위를 입력하세요.')
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

    def speed_limits(self, axis: Any) -> Dict[str, float]:
        """수동 조작 상한 · 모터 rad/s · rad/s² · 마지막 판정 때 읽은 저장 매핑으로 · 수정 목록 126

        이득을 모르면 1 (모터 2 °/s · 가장 느림) · 그런 축은 어차피 위 판정이 막는다
        """
        with self._lock:
            _, saved = self._last
        axis_value = optional_int(axis, None)
        gain = axis_gain(saved, self._motors(), axis_value) if axis_value is not None else None
        return manual_speed.motor_limits(gain)

    def xtouch_limits(self, axis: Any) -> Tuple[Dict[str, float], str]:
        """X-Touch 상한 · 마지막 판정 때 읽은 저장 매핑으로 · 비면 (빈 dict, 이유) · 수정 목록 156"""
        with self._lock:
            _, saved = self._last
        axis_value = optional_int(axis, None)
        if axis_value is None:
            return {}, f'{PREFIX}모터 번호가 없습니다'
        return xtouch_limits(saved, self._motors(), axis_value)

    def saved_rows(self) -> List[Dict[str, Any]]:
        """마지막 판정 때 읽은 저장 매핑 줄 · 녹화가 조인트 이름·변환식을 여기서 얻는다 · 수정 목록 156"""
        with self._lock:
            _, saved = self._last
        return [dict(row) for row in saved]

    def motors(self) -> List[Dict[str, Any]]:
        return self._motors()

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
