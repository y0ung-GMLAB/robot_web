"""X-Touch 녹화 · 수정 목록 156 (사용자 결정 2026-10-17)

X-Touch 페이더로 움직인 축을 애니메이션 파일로 남긴다 · 로봇 쪽(브리지)에서 기록한다 ·
화면(브라우저)은 시작·정지만 보낸다 · 화면이 끊겨도 여기서 끊긴 순간까지 저장한다.

    기록 값   **명령값 · 램프 뒤** · supervisor 램프가 주기마다 모터로 보낸 값(`MANUAL_STREAM_SAMPLES`) ·
              모터 rad 를 조인트 매핑 식으로 되돌려 조인트 rad 로
    주기      20 ms · 램프 주기 번호(`seq`)가 이어지면 다음 프레임 · 끊겼다 다시 오면 받은 벽시계로 자리를 정한다 ·
              램프가 없는 동안(놓고 도착함)은 마지막 값 그대로(축이 서 있다)
    축        녹화 시작 때 고른 축(+ 녹화 중 더한 축) · 그 밖의 축은 파일에 안 넣는다 ·
              속도·가속도 상한이 빈 축은 시작 거절
    시작      카운트다운 3초 뒤부터 · 그 전 값은 첫 프레임 값으로만
    저장      Blender 내보내기와 같은 JSON Lines(첫 줄 `motion_header` · rad) · 프로젝트 애니메이션 목록 ·
              같은 이름이면 `_2` · `_3` · 저장 전에 재생과 같은 속도·가속도 검사(`rate_check`) · 넘으면 저장 안 함
    끊김      소켓이 닫히거나 수신이 끊기면 마지막으로 받은 순간까지 자동 저장(자동 번호)

바탕 위 녹화(⑨ 추가 녹화 · ⑨-2 구간 덮어쓰기) · 바탕 애니메이션을 재생 노드가 재생하고 프레임 번호를 알린다 ·
덮어쓰기는 재생 노드가 하고 보낸 값을 알린다 · 합치기는 `xtouch_base_take`.

순수 계산은 `xtouch_recording_core`(`Take` · `animation_text`) · `xtouch_base_take` · 여기는 상태(`RecordingService`).
"""

from __future__ import annotations

import json
import math
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from motion_common import joint_mapping

from .xtouch_base_take import BaseTake, load_base, mapped_rows, punchable
from .xtouch_recording_core import (  # noqa: F401 · 시험·다른 모듈이 이 이름으로도 쓴다
    COUNTDOWN_SEC, DEFAULT_PREFIX, PERIOD_SEC, SAME_NAME_TEXT, Take, TakeAxis,
    animation_text, clean_name, rate_problem, save_unique,
)


class RecordingService:
    """브리지에 하나 · 한 번에 녹화 하나(X-Touch 를 쥔 화면 하나) · 잠금 안에서만 바꾼다

    녹화 두 가지 ·
        새로 녹화        `Take` · 3초 카운트다운 · 고른 축만
        바탕 위에 녹화   `BaseTake` · 바탕 애니메이션을 재생 노드가 재생(초기 위치 이동이 카운트다운) ·
                         바탕 조인트는 잡으면 구간 덮어쓰기 · 바탕에 없는 축은 추가 녹화 · 수정 목록 156 ⑨

    브리지 속은 안 만진다 · 필요한 것은 만들 때 받는다(§6-170) ·
        mapping         () → (저장된 매핑 「사용」 줄들, 모터 상태들) · 막는 이유를 먼저 본 뒤 부른다
        record_event    (event_type, content, details) · 모터 기록(운영 로그)
        read_motion     (파일 이름) → 내용 · 바탕 애니메이션
        start_playback  (요청) → 결과 · 바탕 재생 시작(`bridge.motion_run_start`)
        stop_playback   () → 결과
        publish_punch   (요청) · 구간 덮어쓰기 입력 → 재생 노드
    """

    #: 정지를 누른 뒤 재생 노드의 끝 알림을 기다리는 시간 · 초
    END_WAIT_SEC = 3.0

    def __init__(
        self,
        bridge: Any,
        *,
        mapping: Callable[[], Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]],
        record_event: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        read_motion: Optional[Callable[[str], str]] = None,
        start_playback: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        stop_playback: Optional[Callable[[], Any]] = None,
        publish_punch: Optional[Callable[[Dict[str, Any]], None]] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.bridge = bridge
        self._mapping = mapping
        self._event = record_event
        self._read_motion = read_motion
        self._start_playback = start_playback
        self._stop_playback = stop_playback
        self._publish_punch = publish_punch
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._take: Optional[Take] = None
        self._base: Optional[BaseTake] = None
        self._owner: Any = None
        self._name = ''
        self._finishing = False
        self.last_event_error = ''
        #: 마지막 결과 · 화면이 끊겨 있던 사이 끝난 녹화도 다음 ping 에 알린다
        self._last_result: Dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # 받는 값 · supervisor 램프 · 재생 노드 프레임
    # ------------------------------------------------------------------ #

    def samples_callback(self, msg: Any) -> None:
        try:
            payload = json.loads(msg.data)
        except (AttributeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        try:
            seq = int(payload.get('seq'))
            wall = float(payload.get('t'))
        except (TypeError, ValueError):
            return
        samples = []
        for item in payload.get('samples') or []:
            try:
                axis, value = int(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if math.isfinite(value):
                samples.append((axis, value))
        with self._lock:
            if self._take is not None and samples:
                self._take.add_samples(seq, wall, samples)
            if self._base is not None:
                for axis, value in samples:
                    if axis in self._base.overdub:
                        self._base.samples.append((seq, wall, axis, value))

    def take_frames_callback(self, msg: Any) -> None:
        """재생 노드 프레임 알림 · 끝 알림이면 저장(재생이 끝까지 갔다 · 다른 곳에서 정지)"""
        try:
            payload = json.loads(msg.data)
        except (AttributeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        with self._lock:
            base = self._base
            if base is None or str(payload.get('take_id') or '') != base.take_id:
                return
            base.on_frame(payload)
            finish = base.ended and not self._finishing
        if finish:
            threading.Thread(target=self._finish_base, args=(base, '재생 끝'), daemon=True).start()

    # ------------------------------------------------------------------ #
    # 화면 요청
    # ------------------------------------------------------------------ #

    def active_for(self, owner: Any) -> bool:
        with self._lock:
            return (self._take is not None or self._base is not None) and self._owner is owner

    def base_active_for(self, owner: Any) -> bool:
        """바탕 재생 중인 이 화면의 녹화 · 재생 중에도 X-Touch 를 받는다"""
        with self._lock:
            return self._base is not None and self._owner is owner

    def status(self) -> Dict[str, Any]:
        with self._lock:
            last = dict(self._last_result)
            if self._base is not None:
                base = self._base
                return {
                    'state': 'countdown' if base.t0 is None else 'recording',
                    'name': self._name, 'base': base.base.file_id,
                    'axes': sorted(base.overdub),
                    'punch_ids': sorted(base.punch_rows),
                    'elapsed_sec': max(0, base.last_frame + 1) * PERIOD_SEC,
                    'duration_sec': base.base.count * PERIOD_SEC,
                    'last_result': last,
                }
            take = self._take
            if take is None:
                return {'state': 'idle', 'last_result': last}
            now = self._clock()
            return {
                'state': 'countdown' if now < take.t0 else 'recording',
                'name': self._name,
                'axes': sorted(take.axes),
                'starts_in_sec': max(0.0, take.t0 - now),
                'elapsed_sec': max(0.0, now - take.t0),
                'last_result': last,
            }

    def _busy(self) -> bool:
        return self._take is not None or self._base is not None or self._finishing

    def start(self, owner: Any, axes: Any, name: Any = '', base: Any = '') -> Dict[str, Any]:
        with self._lock:
            if self._busy():
                return {'success': False, 'message': BUSY_MESSAGE}
        block = self._block_reason()
        if block:
            return {'success': False, 'message': block}
        if str(base or '').strip():
            return self._start_base(owner, axes, name, str(base).strip())
        resolved, error = self._resolve_axes(axes)
        if error:
            return {'success': False, 'message': error}
        if not resolved:
            return {'success': False, 'message': '녹화할 축이 없습니다 · X-Touch 에서 SELECT 로 축을 고르세요'}
        now = self._clock()
        take = Take(t0=now + COUNTDOWN_SEC)
        for item in resolved:
            take.add_axis(item)
        with self._lock:
            if self._busy():
                return {'success': False, 'message': BUSY_MESSAGE}
            self._take = take
            self._owner = owner
            self._name = clean_name(name)
        return {'success': True, 'message': f'{COUNTDOWN_SEC:g}초 뒤 녹화 시작', **self.status()}

    def _split_axes(self, base: BaseTake | Any, axes: Any) -> Tuple[List[int], List[str], str]:
        """고른 축 → (추가 녹화 축, 덮어쓸 조인트, 거절 이유) · 바탕에 있으면 덮어쓰기 · 없으면 추가 녹화"""
        from .manual_range_gate import axis_rows   # 순환 import 피함

        rows, motors = self._mapping()
        punch_rows = base.punch_rows if isinstance(base, BaseTake) else punchable(base, rows)
        ids_in_base = base.base.ids if isinstance(base, BaseTake) else base.ids
        overdub: List[int] = []
        punch_ids: List[str] = []
        for axis in _axis_list(axes):
            found = axis_rows(rows, motors, axis)
            ids = [str(row.get('motion_id') or '') for row in found]
            if found and all(motion_id in ids_in_base for motion_id in ids):
                missing = [motion_id for motion_id in ids if motion_id not in punch_rows]
                if missing:
                    return [], [], (
                        f'축 {axis} ({", ".join(missing)}) 속도·가속도 상한을 먼저 채우세요 · '
                        '조인트 매핑의 최대 속도·가속도'
                    )
                punch_ids.extend(ids)
                continue
            overdub.append(axis)
        return overdub, punch_ids, ''

    def _start_base(self, owner: Any, axes: Any, name: Any, base_file: str) -> Dict[str, Any]:
        if self._read_motion is None or self._start_playback is None:
            return {'success': False, 'message': '이 서버는 바탕 위 녹화를 지원하지 않습니다'}
        try:
            base = load_base(base_file, self._read_motion(base_file))
        except Exception as exc:  # noqa: BLE001 · 화면에 그대로
            return {'success': False, 'message': f'바탕 애니메이션을 읽을 수 없습니다 · {exc}'}
        rows, _motors = self._mapping()
        if not any(motion_id in mapped_rows(rows) for motion_id in base.ids):
            return {'success': False, 'message': f'{base_file} 에 이 로봇의 조인트가 없습니다'}
        overdub_axes, _punch_ids, error = self._split_axes(base, axes)
        if error:
            return {'success': False, 'message': error}
        resolved, error = self._resolve_axes(overdub_axes)
        if error:
            return {'success': False, 'message': error}
        punch_rows = punchable(base, rows)
        take = BaseTake(
            take_id=uuid.uuid4().hex[:12], base=base, punch_rows=punch_rows,
            overdub={item.axis: item for item in resolved},
        )
        with self._lock:
            if self._busy():
                return {'success': False, 'message': BUSY_MESSAGE}
            self._base = take
            self._owner = owner
            self._name = clean_name(name or f'{base_file.rsplit(".", 1)[0]}_xtouch')
        try:
            result = self._start_playback({
                'motion_file_id': base_file, 'run_mode': 'once', 'repeat_mode': 'reinitialize',
                'xtouch_take': True, 'xtouch_take_id': take.take_id, 'xtouch_punch_ids': sorted(punch_rows),
            }) or {}
        except Exception as exc:  # noqa: BLE001 · 화면에 그대로
            result = {'success': False, 'message': str(exc)}
        if result.get('success') is False:
            with self._lock:
                if self._base is take:
                    self._base = None
                    self._owner = None
            return {'success': False, 'message': str(result.get('message') or '바탕 애니메이션 재생을 시작하지 못했습니다')}
        return {'success': True, 'message': f'{base_file} 재생 · 초기 위치로 이동한 뒤 녹화', **self.status()}

    def add_axes(self, owner: Any, axes: Any) -> Dict[str, Any]:
        """녹화 중 SELECT 로 더한 축 · 그 전 프레임은 지금 위치 그대로(그동안 안 움직였다)

        바탕 위 녹화에서 바탕에 있는 축은 처음부터 덮어쓸 수 있다(재생 노드가 안다) · 더할 것 없음
        """
        with self._lock:
            if self._owner is not owner or (self._take is None and self._base is None):
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            base = self._base
            known = set(base.overdub) if base is not None else set(self._take.axes)
        wanted = [axis for axis in _axis_list(axes) if axis not in known]
        if base is not None and wanted:
            wanted, _punch_ids, error = self._split_axes(base, wanted)
            if error:
                return {'success': False, 'message': error}
        if not wanted:
            return {'success': True, 'message': '', **self.status()}
        resolved, error = self._resolve_axes(wanted)
        if error:
            return {'success': False, 'message': error}
        with self._lock:
            if self._owner is not owner:
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            for item in resolved:
                if self._base is not None:
                    self._base.overdub[item.axis] = item
                elif self._take is not None:
                    self._take.add_axis(item)
        return {'success': True, 'message': '', **self.status()}

    def punch(self, owner: Any, motion_id: Any, target_rad: Any = None, *, release: bool = False) -> Dict[str, Any]:
        """구간 덮어쓰기 입력 → 재생 노드 · 바탕 조인트만 · 수정 목록 156 ⑨-2"""
        name = str(motion_id or '')
        with self._lock:
            base = self._base if self._owner is owner else None
        if base is None:
            return {'success': False, 'message': '바탕 위 녹화 중이 아닙니다'}
        if name not in base.punch_rows:
            return {'success': False, 'message': f'{name} 은 이 녹화에서 덮어쓸 수 없습니다(바탕에 없거나 속도·가속도 상한 없음)'}
        if self._publish_punch is None:
            return {'success': False, 'message': '이 서버는 구간 덮어쓰기를 지원하지 않습니다'}
        if release:
            self._publish_punch({'motion_id': name, 'release': True})
            return {'success': True}
        try:
            value = float(target_rad)
        except (TypeError, ValueError):
            return {'success': False, 'message': '목표(조인트 rad)가 필요합니다'}
        if not math.isfinite(value):
            return {'success': False, 'message': '목표(조인트 rad)가 필요합니다'}
        self._publish_punch({'motion_id': name, 'target_rad': value})
        return {'success': True}

    def cancel(self, owner: Any) -> Dict[str, Any]:
        with self._lock:
            if self._owner is not owner or (self._take is None and self._base is None):
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            base = self._base
            self._take = None
            self._base = None
            self._owner = None
        if base is not None and self._stop_playback is not None:
            self._stop_playback()
        return {'success': True, 'state': 'idle', 'message': '녹화를 취소했습니다 · 저장하지 않았습니다'}

    def stop(self, owner: Any, end_wall: Optional[float] = None, *, reason: str = '') -> Dict[str, Any]:
        """정지 · 저장 · 카운트다운 중이면 저장할 것 없이 취소"""
        with self._lock:
            if self._owner is not owner or (self._take is None and self._base is None):
                return {'success': False, 'message': '녹화 중이 아닙니다'}
            base = self._base
            take = self._take
            name = self._name
            if base is None:
                self._take = None
                self._owner = None
        if base is not None:
            return self._stop_base(base, reason)
        end = self._clock() if end_wall is None else float(end_wall)
        if end < take.t0 + PERIOD_SEC:
            return {'success': False, 'state': 'idle', 'message': '카운트다운 중에 멈췄습니다 · 저장할 녹화가 없습니다'}
        return self._remember(self._save(take.joint_series(end), name, reason))

    def _stop_base(self, base: BaseTake, reason: str) -> Dict[str, Any]:
        """재생을 멈추고 끝 알림을 기다린 뒤 저장 · 재생 노드 알림이 먼저 저장했으면 그 결과"""
        if not base.ended and self._stop_playback is not None:
            self._stop_playback()
        waited = 0.0
        while not base.ended and waited < self.END_WAIT_SEC:
            self._sleep(0.05)
            waited += 0.05
        result = self._finish_base(base, reason or '정지')
        if result is not None:
            return result
        # 다른 실(끝 알림)이 저장 중 · 끝나기를 기다린다
        waited = 0.0
        while waited < self.END_WAIT_SEC * 2:
            with self._lock:
                done = not self._finishing and self._base is None
                last = dict(self._last_result)
            if done:
                return last
            self._sleep(0.05)
            waited += 0.05
        return {'success': False, 'message': '저장 결과를 기다리다 시간이 지났습니다 · 애니메이션 목록을 확인하세요'}

    def _finish_base(self, expected: BaseTake, reason: str) -> Optional[Dict[str, Any]]:
        """한 번만 · 먼저 잡은 쪽이 저장 · 못 잡으면 None"""
        with self._lock:
            if self._base is not expected or self._finishing:
                return None
            self._finishing = True
            name = self._name
        try:
            base = expected
            if base.frame_count() == 0:
                result = {'success': False, 'state': 'idle', 'message': '초기 위치 이동 중에 멈췄습니다 · 저장할 녹화가 없습니다'}
            elif base.overrun:
                problem = f'원본으로 잇기가 10초 안에 상한을 못 맞췄습니다 · {", ".join(sorted(base.overrun))}'
                self._record_event('xtouch_record_refused', f'녹화 저장 거절 · {problem}', {'name': name})
                result = {'success': False, 'state': 'idle', 'message': f'저장 안 함 · {problem}'}
            else:
                joints, _count = base.compose()
                result = self._save(joints, name, reason, start=base.base.start, base_file=base.base.file_id)
        finally:
            with self._lock:
                self._base = None
                self._owner = None
                self._finishing = False
        return self._remember(result)

    def _remember(self, result: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._last_result = {**result, 'at': self._clock()}
        return result

    # ------------------------------------------------------------------ #

    def _block_reason(self) -> str:
        blocker = getattr(self.bridge, 'manual_range_blocker', None)
        return str(blocker() or '') if callable(blocker) else ''

    def _resolve_axes(self, axes: Any) -> Tuple[List[TakeAxis], str]:
        from .manual_range_gate import axis_rows   # 순환 import 피함

        rows, motors = self._mapping()
        positions = {}
        for motor in motors:
            index = motor.get('controller_index')
            value = motor.get('position_rad')
            try:
                positions[int(index)] = float(value)
            except (TypeError, ValueError):
                continue
        result = []
        for axis in _axis_list(axes):
            found = axis_rows(rows, motors, axis)
            if not found:
                return [], f'{axis}번 모터는 조인트 매핑의 「사용」 줄에 없습니다'
            for row in found:
                if not joint_mapping.rate_limits_set(row):
                    return [], (
                        f'축 {axis} ({row.get("motion_id")}) 속도·가속도 상한을 먼저 채우세요 · '
                        '조인트 매핑의 최대 속도·가속도'
                    )
            if axis not in positions or not math.isfinite(positions[axis]):
                return [], f'{axis}번 모터의 현재 위치를 읽을 수 없습니다'
            result.append(TakeAxis(axis=axis, rows=found, start_motor=positions[axis]))
        return result, ''

    def _save(
        self, joints: List[Tuple[str, Any, List[float]]], name: str, reason: str,
        *, start: float = PERIOD_SEC, base_file: str = '',
    ) -> Dict[str, Any]:
        frames = len(joints[0][2]) if joints else 0
        problem = rate_problem(joints)
        if problem:
            self._record_event('xtouch_record_refused', f'녹화 저장 거절 · {problem}', {'name': name})
            return {'success': False, 'state': 'idle', 'message': f'저장 안 함 · {problem}'}
        repository = self.bridge.project_repository
        try:
            project_id = repository.require_selected_project_id()
            file_name = save_unique(
                lambda candidate: repository.import_text(
                    project_id, 'motions', candidate,
                    animation_text(candidate[:-len('.json')], joints, start=start, base=base_file),
                ),
                name,
            )
        except Exception as exc:  # noqa: BLE001 · 화면에 그대로
            self._record_event('xtouch_record_failed', f'녹화 저장 실패 · {exc}', {'name': name})
            return {'success': False, 'state': 'idle', 'message': f'저장 실패 · {exc}'}
        duration = frames * PERIOD_SEC
        ids = [joint[0] for joint in joints]
        content = f'X-Touch 녹화 저장 · {file_name} · {duration:.2f} s · {", ".join(ids)}'
        if base_file:
            content = f'{content} · 바탕 {base_file}'
        if reason:
            content = f'{content} · {reason}'
        self._record_event('xtouch_record_saved', content, {
            'file': file_name, 'frames': frames, 'motion_ids': ids, 'reason': reason, 'base_file': base_file,
        })
        return {
            'success': True, 'state': 'saved', 'file': file_name, 'frames': frames,
            'duration_sec': duration, 'motion_ids': ids, 'base_file': base_file,
            'message': f'저장했습니다 · {file_name} · {duration:.2f} s' + (f' · {reason}' if reason else ''),
        }

    def _record_event(self, event_type: str, content: str, details: Dict[str, Any]) -> None:
        if self._event is None:
            return
        try:
            self._event(event_type, content, details)
        except Exception as exc:  # noqa: BLE001 · 기록 실패로 녹화를 막지 않는다 · 마지막 것만 둔다
            self.last_event_error = str(exc)


BUSY_MESSAGE = '이미 녹화 중입니다 · 정지한 뒤 다시 시작하세요'


def _axis_list(axes: Any) -> List[int]:
    result: List[int] = []
    for value in axes if isinstance(axes, (list, tuple)) else []:
        try:
            axis = int(value)
        except (TypeError, ValueError):
            continue
        if axis >= 0 and axis not in result:
            result.append(axis)
    return result
