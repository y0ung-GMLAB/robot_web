"""X-Touch 녹화 재생 · 재생 루프가 프레임마다 부른다 · 수정 목록 156 ⑨ ⑨-2 (사용자 결정 2026-10-17)

녹화 화면이 기존 애니메이션 위에 녹화하면(추가 녹화 · 구간 덮어쓰기) 그 애니메이션을 이 노드가 재생한다 ·
여기는 두 가지만 더 한다.

    프레임 알림   프레임마다 번호와 보낸 벽시계 · 녹화(브리지)가 페이더 값을 이 프레임에 맞춘다
    덮어쓰기      사람이 잡은 조인트만 원본 대신 `motion_common.punch` 값 · 보낸 값을 그대로 알린다(녹화 = 보낸 값)

`xtouch_take` 가 없는 재생(보통 재생 · 그룹 · 스케줄)은 이 객체를 만들지 않는다 · 아무 영향 없음.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Tuple

from std_msgs.msg import String

from motion_common import punch

from . import motion_run_rules


class TakePlayback:
    def __init__(self, manager: Any, plan: Dict[str, Any]) -> None:
        self.manager = manager
        self.take_id = str(plan.get('xtouch_take_id') or '')
        self.axes = {str(axis['motion_id']): axis for axis in plan.get('axes') or []}
        joints = {
            motion_id: spec for motion_id, spec in (plan.get('punch_joints') or {}).items()
            if motion_id in self.axes
        }
        samples = plan.get('samples') or []
        self.series = {
            motion_id: [float(sample['motion_values'][motion_id]) for sample in samples]
            for motion_id in joints
        }
        self.controller = punch.PunchController(joints, float(manager.period_sec)) if joints else None
        with manager._punch_lock:
            manager._punch_controller = self.controller

    def apply(
        self, index: int, positions: Dict[int, float], motion_values: Dict[str, float] | None,
    ) -> Tuple[Dict[int, float], Dict[str, float] | None]:
        """덮어쓴 조인트만 바꾼 새 사전 · 프레임 알림도 여기서 보낸다"""
        values: Dict[str, float] = {}
        overrun = []
        if self.controller is not None:
            with self.manager._punch_lock:
                out = self.controller.frame(
                    {motion_id: punch.SeriesTail(series, index) for motion_id, series in self.series.items()},
                    time.monotonic(),
                )
                for motion_id, joint in self.controller.joints.items():
                    if not joint.blend_ok:
                        overrun.append(motion_id)
            changed = {
                motion_id: value for motion_id, (value, state) in out.items() if state != punch.PLAY
            }
            if changed:
                positions = dict(positions)
                motion_values = dict(motion_values or {})
                for motion_id, value in changed.items():
                    axis = self.axes[motion_id]
                    motor_axis = int(axis['motor_axis'])
                    if motor_axis in positions:
                        positions[motor_axis] = motion_run_rules._clamp_to_motor_limits(
                            motion_run_rules._motor_target(axis['row'], value), axis.get('motor_for_limits'),
                        )
                    motion_values[motion_id] = value
                values = changed
        self._publish({
            'take_id': self.take_id, 'frame': int(index), 't': time.time(),
            'values': values, 'blend_overrun': overrun,
        })
        return positions, motion_values

    def _publish(self, payload: Dict[str, Any]) -> None:
        publisher = getattr(self.manager, '_take_frame_pub', None)
        if publisher is not None:
            publisher.publish(String(data=json.dumps(payload)))

    @staticmethod
    def announce_failure(manager: Any, payload: Dict[str, Any], message: str) -> None:
        """재생을 시작도 못 했거나 오류로 끝남 · 녹화(브리지)가 기다리지 않게 끝 알림 + 이유 · 2026-10-19"""
        take_id = str(payload.get('xtouch_take_id') or '')
        publisher = getattr(manager, '_take_frame_pub', None)
        if not payload.get('xtouch_take') or not take_id or publisher is None:
            return
        publisher.publish(String(data=json.dumps(
            {'take_id': take_id, 'end': True, 'error': str(message), 't': time.time()}, ensure_ascii=False,
        )))

    def close(self) -> None:
        with self.manager._punch_lock:
            if self.manager._punch_controller is self.controller:
                self.manager._punch_controller = None
        self._publish({'take_id': self.take_id, 'end': True, 't': time.time()})
