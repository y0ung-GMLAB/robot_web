"""웹 3D 표시 · 장면(JSON)과 재생 프레임을 브라우저에 준다 · 수정 목록 7-a (2026-10-04)

네이티브 뷰어 창은 서버 PC 모니터에만 떠서 없앴다(7 · 2026-10-04) ·
원격 접속자가 보려면 브라우저가 그려야 한다 · 물리 계산은 그대로 MuJoCo
(`scripts/sim/sim_run.py` → `.sim.npz`) · 여기는 두 가지만 한다:

    장면      로봇 팩 → `scripts/sim/export_scene.py` (uv · MuJoCo 로 메쉬·바디·관절 내보냄)
              → `runtime/preview/scene-<팩 지문>.json` · 팩이 바뀌면 다른 파일 · 1회 계산
    프레임    `.sim.npz` 의 t · qpos 를 읽어 JSON 으로 (numpy · 60 Hz 로 솎음)

브라우저(`static/js/sim3d.js`)가 장면을 세우고 프레임마다 순방향 운동학을 돈다.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from motion_common import robot_pack

from motion_web_bridge import animation_preview

#: 장면 내보내기 명령 · preview.yaml 또는 config/animation_preview.yaml 의 `scene.command` 로 바꿀 수 있다
DEFAULT_SCENE_COMMAND = [
    'uv', 'run', '--no-project', '--with=mujoco', '--with=numpy', '--with=pyyaml',
    'python', '{stack}/scripts/sim/export_scene.py', '{pack}', '{result}',
]
SCENE_DIR_NAME = 'preview'
#: 프레임 응답 상한 · 100 Hz 기록을 이 아래로 솎는다 (브라우저 60 fps 면 충분)
MAX_FRAME_HZ = 60.0
NO_PACK_MESSAGE = '로봇 팩이 없습니다 · 시스템 정보 → 로봇 팩에서 올리세요'
NO_UV_MESSAGE = '장면 내보내기 실패 · uv 또는 MuJoCo 를 실행할 수 없습니다 (log/animation_preview/scene.log)'

_LOCK = threading.Lock()
#: 도는 장면 내보내기 · {결과 경로: Popen}
_RUNNING: Dict[str, subprocess.Popen] = {}
_LAST_RC: Dict[str, int] = {}


def scene_path(workspace_root: Path) -> Optional[Path]:
    """지금 팩의 장면 파일 경로 · 팩이 없으면 None · 팩 지문이 바뀌면 다른 파일."""
    pack_dir = robot_pack.pack_root(Path(workspace_root))
    fingerprint = robot_pack.current_fingerprint(pack_dir)
    if not fingerprint:
        return None
    return Path(workspace_root) / 'runtime' / SCENE_DIR_NAME / f'scene-{fingerprint[:16]}.json'


def _scene_command(workspace_root: Path, result: Path) -> List[str]:
    config = animation_preview.preview_config(Path(workspace_root)) or {}
    scene = config.get('scene') if isinstance(config.get('scene'), dict) else {}
    command = scene.get('command') if isinstance(scene.get('command'), list) and scene.get('command') else DEFAULT_SCENE_COMMAND
    stack = str(config.get('_stack') or workspace_root)
    pack = str(config.get('_pack') or robot_pack.pack_root(Path(workspace_root)))
    return [
        str(part).replace('{stack}', stack).replace('{pack}', pack).replace('{result}', str(result))
        for part in command
    ]


def _reap() -> None:
    with _LOCK:
        for key in list(_RUNNING):
            code = _RUNNING[key].poll()
            if code is not None:
                _LAST_RC[key] = code
                del _RUNNING[key]


def scene_state(workspace_root: Path) -> Dict[str, Any]:
    """unavailable(팩 없음) · computing · ready · failed · missing."""
    path = scene_path(workspace_root)
    if path is None:
        return {'state': 'unavailable', 'message': NO_PACK_MESSAGE}
    _reap()
    key = str(path)
    with _LOCK:
        if key in _RUNNING:
            return {'state': 'computing', 'message': '3D 장면을 만드는 중입니다'}
        last_rc = _LAST_RC.get(key)
    if path.is_file():
        return {'state': 'ready', 'path': key}
    if last_rc not in (None, 0):
        return {'state': 'failed', 'message': f'{NO_UV_MESSAGE} · 코드 {last_rc}'}
    return {'state': 'missing', 'message': '3D 장면이 아직 없습니다 · 「3D 장면 준비」를 누르세요'}


def launch_scene_export(workspace_root: Path, *, spawn=subprocess.Popen) -> Dict[str, Any]:
    """장면 내보내기 시작 · 이미 있으면 그대로 · 도는 중이면 그대로."""
    path = scene_path(workspace_root)
    if path is None:
        return {'success': False, 'message': NO_PACK_MESSAGE}
    state = scene_state(workspace_root)
    if state['state'] == 'ready':
        return {'success': True, 'message': '3D 장면이 이미 준비돼 있습니다'}
    if state['state'] == 'computing':
        return {'success': True, 'message': '3D 장면을 만드는 중입니다'}
    args = _scene_command(workspace_root, path)
    log = animation_preview._open_log(workspace_root, Path('scene.json'), 'scene')
    try:
        handle = spawn(args, cwd=str(workspace_root), stdout=log, stderr=log, shell=False)
    except OSError as exc:
        animation_preview._close_log(log)
        return {'success': False, 'message': f'장면 내보내기 시작 실패: {exc}'}
    animation_preview._close_log(log)
    with _LOCK:
        _RUNNING[str(path)] = handle
        _LAST_RC.pop(str(path), None)
    return {'success': True, 'message': '3D 장면을 만들기 시작했습니다 · 몇 초 뒤 다시 읽습니다'}


def read_scene(workspace_root: Path) -> Optional[Dict[str, Any]]:
    path = scene_path(workspace_root)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def frames_payload(workspace_root: Path, motion_path: Path, *, max_hz: float = MAX_FRAME_HZ) -> Dict[str, Any]:
    """`.sim.npz` → {t, qpos, n_frames, duration_sec, hz} · 없으면 success False."""
    config = animation_preview.preview_config(Path(workspace_root))
    if config is None:
        return {'success': False, 'message': animation_preview.NOT_CONFIGURED_MESSAGE}
    result = animation_preview.result_path_for(config, Path(motion_path))
    if result is None:
        return {'success': False, 'message': '계산 결과가 없는 구성입니다 (precompute 없음)'}
    if not result.is_file():
        return {'success': False, 'message': '계산 결과가 없습니다 · 「MuJoCo 계산」을 먼저 누르세요'}
    try:
        import numpy as np
    except ImportError:
        return {'success': False, 'message': 'numpy 가 없어 계산 결과를 읽을 수 없습니다'}
    try:
        with np.load(str(result), allow_pickle=False) as data:
            t = np.asarray(data['t'], dtype=float).reshape(-1)
            qpos = np.asarray(data['qpos'], dtype=float)
            n_frames = int(data['n_frames']) if 'n_frames' in data else 0
            ref = str(data['ref']) if 'ref' in data else ''
    except (OSError, ValueError, KeyError) as exc:
        return {'success': False, 'message': f'계산 결과를 읽지 못했습니다: {exc}'}
    if t.size == 0 or qpos.ndim != 2 or qpos.shape[0] != t.size:
        return {'success': False, 'message': '계산 결과 모양이 맞지 않습니다 (t · qpos)'}
    duration = float(t[-1] - t[0]) if t.size > 1 else 0.0
    source_hz = (t.size - 1) / duration if duration > 0 else 0.0
    step = max(1, int(round(source_hz / max_hz))) if source_hz > max_hz > 0 else 1
    t = t[::step]
    qpos = qpos[::step]
    return {
        'success': True,
        'n_frames': n_frames,
        'nq': int(qpos.shape[1]),
        'duration_sec': round(duration, 4),
        # 애니메이션 길이 · 끝의 정착 3초는 빼고 · 실물 따라가기는 여기서 회차를 끊는다 · 수정 목록 8
        'motion_sec': round(
            n_frames * 0.02 if n_frames else max(duration - 3.0, 0.0), 4,
        ),
        'hz': round(source_hz / step, 3) if step else 0.0,
        'ref': ref,
        'result': str(result),
        'generated_at': time.time(),
        't': [round(float(v), 4) for v in t],
        'qpos': [[round(float(v), 5) for v in row] for row in qpos],
    }
