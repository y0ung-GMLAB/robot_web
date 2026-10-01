"""애니메이션 무조코(시뮬) 미리보기 · 계산과 재생을 현장 명령에 맡긴다 · P7

플랫폼은 로봇도 시뮬레이터도 모른다 · 로봇마다(플로팅 헤드, 다음 로봇…)
모델·스크립트가 다르므로, 여기는 **명령 틀과 결과 경로**만 안다 · 채우는
것은 각 PC 의 `config/animation_preview.yaml` 이다 (모터 불문 원칙과 같다).

두 단계다 · 뷰어는 **계산이 끝난 것만** 튼다:

    계산(precompute)   무거운 물리 시뮬 · 업로드되면 한 번 · 결과 파일을 남긴다
    재생(preview)      결과 파일을 그대로 튼다 · 가볍다 · 모터 재생과 동시 실행 가능

설정 (`config/animation_preview.example.yaml` 참고):

    precompute:
      command: [...]            # {motion_path} {motion_stem} 치환
      result: '{motion_stem}.sim.npz'   # 이 파일이 생기면 「계산 끝」
    preview:
      command: [...]            # {motion_path} {motion_stem} {result} {fps} 치환
    fps: 60                     # 기본 fps · 화면에서 30/60/120/144 선택
    cwd: ...                    # 명령 실행 폴더

`precompute` 없이 `preview`(또는 옛 `command`)만 있으면 게이트 없이 바로
튼다(direct) · 물리 없는 kinematic 뷰어처럼 계산이 필요 없는 구성용.

실행은 **발사 후 망각**이다 · 뷰어 창은 그 PC 화면에 뜨고 닫는 것도 사람이
한다 · 계산은 끝났는지(결과 파일 존재)와 도는 중인지만 기억한다.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

CONFIG_NAME = 'animation_preview.yaml'
ALLOWED_FPS = (30, 60, 120, 144)
NOT_CONFIGURED_MESSAGE = (
    '미리보기 명령이 설정되지 않았습니다 · '
    'config/animation_preview.yaml 을 만드세요 '
    '(본보기: config/animation_preview.example.yaml)'
)

#: 도는 계산들 · {결과 경로: Popen} · 끝난 것은 보일 때 거둔다
_RUNNING: Dict[str, subprocess.Popen] = {}
#: 마지막으로 끝난 계산의 종료 코드 · 실패를 「미계산」과 구별해 말한다
_LAST_RC: Dict[str, int] = {}
_LOCK = threading.Lock()


def preview_config(workspace_root: Path) -> Optional[Dict[str, Any]]:
    """설정을 읽는다 · 없거나 모양이 틀리면 None."""
    path = Path(workspace_root) / 'config' / CONFIG_NAME
    try:
        payload = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    preview = payload.get('preview')
    if not isinstance(preview, dict):
        # 옛 모양 · 최상위 command 하나 = 게이트 없는 direct 재생
        command = payload.get('command')
        if not _valid_command(command):
            return None
        payload = dict(payload)
        payload['preview'] = {'command': command}
        preview = payload['preview']
    if not _valid_command(preview.get('command')):
        return None
    precompute = payload.get('precompute')
    if precompute is not None:
        if not isinstance(precompute, dict) or not _valid_command(precompute.get('command')):
            return None
        if not str(precompute.get('result') or '').strip():
            return None
    return payload


def _valid_command(command: Any) -> bool:
    return (
        isinstance(command, list)
        and bool(command)
        and all(isinstance(part, (str, int, float)) for part in command)
    )


def _fill(parts: List[Any], motion_path: Path, *, result: str = '', fps: Any = '') -> List[str]:
    stem = str(motion_path)
    if stem.lower().endswith('.json'):
        stem = stem[: -len('.json')]
    return [
        str(part)
        .replace('{motion_path}', str(motion_path))
        .replace('{motion_stem}', stem)
        .replace('{result}', result)
        .replace('{fps}', str(fps))
        for part in parts
    ]


def normalized_fps(config: Dict[str, Any], requested: Any = None) -> int:
    """화면이 고른 fps · 허용 값(30/60/120/144)만 · 아니면 설정 기본."""
    try:
        value = int(requested)
    except (TypeError, ValueError):
        value = None
    if value in ALLOWED_FPS:
        return value
    try:
        fallback = int(config.get('fps', 60))
    except (TypeError, ValueError):
        fallback = 60
    return fallback if fallback in ALLOWED_FPS else 60


def result_path_for(config: Dict[str, Any], motion_path: Path) -> Optional[Path]:
    precompute = config.get('precompute')
    if not isinstance(precompute, dict):
        return None
    [template] = _fill([precompute['result']], Path(motion_path))
    return Path(template)


def _reap() -> None:
    with _LOCK:
        for key in list(_RUNNING):
            code = _RUNNING[key].poll()
            if code is not None:
                _LAST_RC[key] = code
                del _RUNNING[key]


def preview_state(workspace_root: Path, motion_path: Path) -> Dict[str, Any]:
    """이 애니메이션의 무조코 상태 · 화면 배지와 버튼이 이대로 그린다.

        unavailable  설정 없음
        direct       계산 없이 바로 트는 구성
        computing    계산 도는 중 (그레이)
        ready        계산 끝 · 같이 보기 가능
        failed       마지막 계산이 실패함
        missing      아직 계산 안 함
    """
    config = preview_config(Path(workspace_root))
    if config is None:
        return {'state': 'unavailable', 'message': NOT_CONFIGURED_MESSAGE}
    result = result_path_for(config, Path(motion_path))
    if result is None:
        return {'state': 'direct'}
    _reap()
    key = str(result)
    with _LOCK:
        if key in _RUNNING:
            return {'state': 'computing'}
    if result.is_file():
        return {'state': 'ready'}
    with _LOCK:
        last_rc = _LAST_RC.get(key)
    if last_rc not in (None, 0):
        return {'state': 'failed', 'message': f'마지막 계산이 실패했습니다 (코드 {last_rc})'}
    return {'state': 'missing'}


def annotate_files(workspace_root: Path, files_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """파일 목록에 무조코 상태를 싣는다 · 설정 없으면 손대지 않는다."""
    config = preview_config(Path(workspace_root))
    if config is None:
        return payload
    files = payload.get('files')
    if not isinstance(files, list):
        return payload
    for entry in files:
        if not isinstance(entry, dict) or not entry.get('id'):
            continue
        entry['preview'] = preview_state(
            workspace_root, Path(files_dir) / str(entry['id']),
        )
    return payload


def launch_precompute(
    workspace_root: Path,
    motion_path: Path,
    *,
    spawn=subprocess.Popen,
) -> Dict[str, Any]:
    """무거운 계산을 시작한다 · 이미 돌고 있으면 그대로 둔다."""
    config = preview_config(Path(workspace_root))
    if config is None:
        return {'success': False, 'message': NOT_CONFIGURED_MESSAGE}
    result = result_path_for(config, Path(motion_path))
    if result is None:
        return {'success': True, 'message': '계산이 필요 없는 구성입니다 · 바로 재생됩니다'}
    motion_path = Path(motion_path)
    if not motion_path.is_file():
        return {'success': False, 'message': f'애니메이션 파일이 없습니다: {motion_path.name}'}
    _reap()
    key = str(result)
    with _LOCK:
        if key in _RUNNING:
            return {'success': True, 'message': f'이미 계산 중입니다: {motion_path.name}'}
    args = _fill(config['precompute']['command'], motion_path, result=key)
    cwd = str(config.get('cwd') or workspace_root)
    try:
        handle = spawn(
            args, cwd=cwd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
        )
    except OSError as exc:
        return {'success': False, 'message': f'계산 시작 실패: {exc}'}
    with _LOCK:
        _RUNNING[key] = handle
        _LAST_RC.pop(key, None)
    return {
        'success': True,
        'message': f'무조코 계산 시작: {motion_path.name} · 끝나면 같이 보기가 켜집니다',
    }


def launch_preview(
    workspace_root: Path,
    motion_path: Path,
    *,
    fps: Any = None,
    spawn=subprocess.Popen,
) -> Dict[str, Any]:
    """뷰어를 띄운다 · 계산이 있는 구성이면 **끝난 것만** 튼다."""
    config = preview_config(Path(workspace_root))
    if config is None:
        return {'success': False, 'message': NOT_CONFIGURED_MESSAGE}
    motion_path = Path(motion_path)
    if not motion_path.is_file():
        return {'success': False, 'message': f'애니메이션 파일이 없습니다: {motion_path.name}'}
    state = preview_state(workspace_root, motion_path)
    if state['state'] == 'computing':
        return {'success': False, 'message': '무조코 계산 중입니다 · 끝나면 틀 수 있습니다'}
    if state['state'] in ('missing', 'failed'):
        return {
            'success': False,
            'message': state.get('message')
            or '계산 결과가 없습니다 · 「무조코 계산」을 먼저 누르세요',
        }
    result = result_path_for(config, motion_path)
    args = _fill(
        config['preview']['command'], motion_path,
        result=str(result) if result else '',
        fps=normalized_fps(config, fps),
    )
    cwd = str(config.get('cwd') or workspace_root)
    try:
        spawn(
            args, cwd=cwd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
        )
    except OSError as exc:
        return {'success': False, 'message': f'미리보기 실행 실패: {exc}'}
    return {
        'success': True,
        'message': f'무조코 재생: {motion_path.name} · 창은 이 PC 화면에 뜹니다',
    }
