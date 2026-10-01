"""애니메이션 미리보기 실행기 · 설정된 외부 명령을 띄운다 · P7 2단계

「미리보기」 버튼은 **현장이 정한 명령**(MuJoCo 뷰어 등)에 선택한
애니메이션 경로를 끼워 실행할 뿐이다 · 플랫폼은 어떤 시뮬레이터가
있는지 모른다 (모터 종류를 모르는 것과 같은 이유 · 모터 불문 원칙).

설정 · `<작업공간>/config/animation_preview.yaml`:

    command:
      - uv
      - run
      - --no-project
      - --with=mujoco      # (예시) 전체 예시는 example 파일에
      - python
      - view_run.py
      - /경로/모델.xml
      - '{motion_path}'    # 선택한 애니메이션 파일로 치환
      - interp
      - '{fps}'            # 아래 fps 로 치환
      - kinematic
    fps: 60
    cwd: /경로/sim/scripts  # 명령을 실행할 폴더 (선택)

없으면 버튼이 사유를 말한다 · 켜 두는 비용이 없다.

실행은 **발사 후 망각**이다 · 뷰어 창은 그 PC 의 화면에 뜨고, 닫는 것도
사람이 한다 · 결과를 기다리면 20ms 재생 루프와 브리지가 같이 묶인다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

CONFIG_NAME = 'animation_preview.yaml'
NOT_CONFIGURED_MESSAGE = (
    '미리보기 명령이 설정되지 않았습니다 · '
    'config/animation_preview.yaml 을 만드세요 '
    '(본보기: config/animation_preview.example.yaml)'
)


def preview_config(workspace_root: Path) -> Optional[Dict[str, Any]]:
    """설정을 읽는다 · 없거나 모양이 틀리면 None."""
    path = Path(workspace_root) / 'config' / CONFIG_NAME
    try:
        payload = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    command = payload.get('command')
    if not isinstance(command, list) or not command:
        return None
    if not all(isinstance(part, (str, int, float)) for part in command):
        return None
    return payload


def build_command(config: Dict[str, Any], motion_path: Path) -> List[str]:
    """자리표시자({motion_path} · {fps})를 채운 실행 인자 · 셸은 안 거친다."""
    fps = config.get('fps', 60)
    return [
        str(part)
        .replace('{motion_path}', str(motion_path))
        .replace('{fps}', str(fps))
        for part in config['command']
    ]


def launch_preview(
    workspace_root: Path,
    motion_path: Path,
    *,
    spawn=subprocess.Popen,
) -> Dict[str, Any]:
    config = preview_config(workspace_root)
    if config is None:
        return {'success': False, 'message': NOT_CONFIGURED_MESSAGE}
    motion_path = Path(motion_path)
    if not motion_path.is_file():
        return {'success': False, 'message': f'애니메이션 파일이 없습니다: {motion_path.name}'}
    args = build_command(config, motion_path)
    cwd = str(config.get('cwd') or workspace_root)
    try:
        # 발사 후 망각 · 뷰어가 수십 초를 떠 있어도 브리지는 안 기다린다
        spawn(
            args,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        return {'success': False, 'message': f'미리보기 실행 실패: {exc}'}
    return {
        'success': True,
        'message': f'미리보기 실행: {motion_path.name} · 창은 이 PC 화면에 뜹니다',
    }
