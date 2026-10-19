"""수동 스트림(페이더) 중계 · 브라우저 → 브리지 → supervisor.

브라우저가 20Hz 안팎으로 **모터 rad** 목표를 흘리면 그대로 수동 스트림
토픽(`MANUAL_STREAM_REQUEST`)에 싣는다 · 조인트 → 모터 변환은 화면이 자기
매핑 행으로 한다(화면은 deg 로 계산하고 보낼 때 rad · 수정 목록 6) · 축별 소유 임대(0.15s)는 supervisor 가
관리하므로 여기서는 응답을 기다리지 않는다(발사 후 망각) · 거부 사유는
결과 구독으로 받아 **축별 마지막 것**만 들고 있다가 화면에 돌려준다.

목표는 「가고 싶은 곳」 · supervisor 가 조인트 2 °/s · 4 °/s² 로 천천히 다가간다 ·
상한(모터 단위)은 여기서 매핑 이득으로 계산해 싣는다 · 수정 목록 126 ·
출처가 X-Touch(`xtouch`)면 조인트 매핑 최대 속도·가속도로 · 비면 거절 · 수정 목록 156 ·
X-Touch 는 날 값 + `smooth_sec`(화면에서 고른 스무딩) · 거르는 것은 supervisor

    놓기(release)  `release_axes` · 멈추지 않고 마지막 목표까지 간 뒤 끝
    세우기(hold)   `hold_axes` · supervisor 가 현재 위치를 다시 목표로 박는다 ·
                   화면 「정지」 · 페이지를 떠남 · 소켓이 끊김
"""

from __future__ import annotations

import json
import math
import threading
from typing import Any, Dict, List, Optional

from std_msgs.msg import String

from motion_common import generation, smoothing

#: X-Touch 출처 · 조인트 매핑 최대 속도·가속도로 따라간다 · 수정 목록 156
XTOUCH_SOURCE = 'xtouch'


class ManualStreamService:
    """스트림 요청 발행과 결과 보관 · 최종 모터 출력은 supervisor 단독이다."""

    def __init__(self, bridge: Any, *, publisher: Any) -> None:
        self.bridge = bridge
        self._publisher = publisher
        self._lock = threading.Lock()
        #: 축별 마지막 결과 · 스트림은 1:1 응답 대기가 없어서 저장소가 다르다
        self._last_results: Dict[int, Dict[str, Any]] = {}
        self._seq = 0

    def clear_pending(self) -> None:
        """프로젝트가 바뀌면 이전 프로젝트의 결과를 남기지 않는다."""
        with self._lock:
            self._last_results.clear()

    # ------------------------------------------------------------------ #
    # supervisor 결과
    # ------------------------------------------------------------------ #

    def result_callback(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        if not generation.request_id_matches(
            payload.get('request_id'), self.bridge.current_project_generation()
        ):
            return
        entries = payload.get('results')
        if not isinstance(entries, list):
            entries = [payload]
        with self._lock:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                axis = _optional_axis(entry.get('axis'))
                if axis is None:
                    continue
                self._last_results[axis] = entry

    def pop_result(self, axis: Any) -> Optional[Dict[str, Any]]:
        """이 축의 마지막 결과를 꺼내고 비운다 · 없으면 None."""
        key = _optional_axis(axis)
        if key is None:
            return None
        with self._lock:
            return self._last_results.pop(key, None)

    # ------------------------------------------------------------------ #
    # 요청 발행
    # ------------------------------------------------------------------ #

    def send_target(
        self,
        axis: Any,
        target_rad: Any,
        *,
        motion_id: Any = None,
        motion_rad: Any = None,
        source: Any = None,
        smooth_sec: Any = None,
    ) -> Dict[str, Any]:
        axis_int = _optional_axis(axis)
        if axis_int is None:
            return {'success': False, 'message': '모터 번호(axis)가 필요합니다'}
        target = _finite_float(target_rad)
        if target is None:
            return {'success': False, 'message': '목표 위치(target_rad · 모터 rad)가 필요합니다'}
        request = self._base_request()
        request['axis'] = axis_int
        request['target_rad'] = target
        if motion_id:
            request['motion_id'] = str(motion_id)
        joint_rad = _finite_float(motion_rad)
        if joint_rad is not None:
            request['motion_rad'] = joint_rad
        # 같은 조작이면 새 목표로 · 다른 조작은 움직이는 동안 거절 (supervisor 판정)
        source_text = str(source or '').strip().lower()
        if source_text in ('fader', 'dial', XTOUCH_SOURCE):
            request['source'] = source_text
        if source_text == XTOUCH_SOURCE:
            # X-Touch 는 조인트 매핑 최대 속도·가속도로 · 비면 거절 · 수정 목록 156
            limits, reason = self._xtouch_limits(axis_int)
            if reason:
                return {'success': False, 'axis': axis_int, 'message': reason}
            request.update(limits)
            # 화면은 날 값 · 스무딩은 supervisor 램프 앞에서 · 사용자 결정 2026-10-19
            smooth = smoothing.smooth_sec_from(smooth_sec)
            if smooth > 0.0:
                request['smooth_sec'] = smooth
        else:
            request.update(self._speed_limits(axis_int))
        self._publish(request)
        return {'success': True, 'axis': axis_int, 'request_id': request['request_id']}

    def release(self, axes: Any) -> Dict[str, Any]:
        """놓음 · 마지막 목표까지 천천히 간 뒤 끝 · 수정 목록 126"""
        clean = _clean_axes(axes)
        if not clean:
            return {'success': False, 'message': '놓을 모터가 없습니다'}
        request = self._base_request()
        request['release_axes'] = clean
        self._publish(request)
        return {'success': True, 'axes': clean, 'request_id': request['request_id']}

    def _speed_limits(self, axis: int) -> Dict[str, Any]:
        lookup = getattr(self.bridge, 'manual_speed_limits', None)
        if not callable(lookup):
            return {}
        try:
            return dict(lookup(axis) or {})
        except Exception:  # noqa: BLE001 · 못 구하면 싣지 않는다 → supervisor 가 가장 느린 값
            return {}

    def _xtouch_limits(self, axis: int) -> tuple:
        lookup = getattr(self.bridge, 'xtouch_speed_limits', None)
        if not callable(lookup):
            return {}, 'X-Touch 상한을 읽을 수 없습니다'
        try:
            limits, reason = lookup(axis)
        except Exception as exc:  # noqa: BLE001 · 모르면 거절(보수적)
            return {}, f'X-Touch 상한을 읽을 수 없습니다 ({exc})'
        return dict(limits or {}), str(reason or '')

    def hold(self, axes: Any) -> Dict[str, Any]:
        """그 자리에 세운다 · 정지 · 끊김 · supervisor 가 위치를 읽어 박는다."""
        clean = _clean_axes(axes)
        if not clean:
            return {'success': False, 'message': '위치를 유지할 모터가 없습니다'}
        request = self._base_request()
        request['hold_axes'] = clean
        self._publish(request)
        return {'success': True, 'axes': clean, 'request_id': request['request_id']}

    def _base_request(self) -> Dict[str, Any]:
        project_generation = self.bridge.current_project_generation()
        self._seq += 1
        return {
            'request_id': generation.new_request_id(
                'stream', project_generation, self._seq
            ),
            'project_generation': project_generation,
        }

    def _publish(self, request: Dict[str, Any]) -> None:
        self._publisher.publish(
            String(data=json.dumps(request, ensure_ascii=False))
        )


def _clean_axes(axes: Any) -> List[int]:
    clean: List[int] = []
    for value in axes if isinstance(axes, (list, tuple)) else []:
        axis = _optional_axis(value)
        if axis is not None and axis not in clean:
            clean.append(axis)
    return clean


def _optional_axis(value: Any) -> Optional[int]:
    try:
        axis = int(value)
    except (TypeError, ValueError):
        return None
    return axis if axis >= 0 else None


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
