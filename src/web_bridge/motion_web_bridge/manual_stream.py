"""수동 스트림(페이더) 중계 · 브라우저 → 브리지 → supervisor.

브라우저가 20Hz 안팎으로 **모터 deg** 목표를 흘리면 그대로 수동 스트림
토픽(`MANUAL_STREAM_REQUEST`)에 싣는다 · 조인트 deg → 모터 deg 변환은
화면이 자기 매핑 행으로 한다 · 축별 소유 임대(0.15s)는 supervisor 가
관리하므로 여기서는 응답을 기다리지 않는다(발사 후 망각) · 거부 사유는
결과 구독으로 받아 **축별 마지막 것**만 들고 있다가 화면에 돌려준다.

놓으면 잡은 곳에 선다 · release 는 `hold_axes` 요청으로 바뀌어 supervisor
가 현재 위치를 다시 목표로 박는다 · PP 모드 드라이브는 임대가 끝나도
마지막 목표에 머무르므로, hold 는 "날아가던 목표" 가 아니라 "지금 서 있는
곳" 에 세우기 위한 것이다.
"""

from __future__ import annotations

import json
import math
import threading
from typing import Any, Dict, List, Optional

from std_msgs.msg import String

from motion_common import generation


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
        target_deg: Any,
        *,
        motion_id: Any = None,
        motion_deg: Any = None,
    ) -> Dict[str, Any]:
        axis_int = _optional_axis(axis)
        if axis_int is None:
            return {'success': False, 'message': '모터 번호(axis)가 필요합니다'}
        target = _finite_float(target_deg)
        if target is None:
            return {'success': False, 'message': '목표 위치(target_deg · 모터 deg)가 필요합니다'}
        request = self._base_request()
        request['axis'] = axis_int
        request['target_deg'] = target
        if motion_id:
            request['motion_id'] = str(motion_id)
        joint_deg = _finite_float(motion_deg)
        if joint_deg is not None:
            request['motion_deg'] = joint_deg
        self._publish(request)
        return {'success': True, 'axis': axis_int, 'request_id': request['request_id']}

    def hold(self, axes: Any) -> Dict[str, Any]:
        """놓은 축들을 현재 위치에 세운다 · supervisor 가 위치를 읽어 박는다."""
        clean: List[int] = []
        for value in axes if isinstance(axes, (list, tuple)) else []:
            axis = _optional_axis(value)
            if axis is not None and axis not in clean:
                clean.append(axis)
        if not clean:
            return {'success': False, 'message': '잡아 둘 모터가 없습니다'}
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
