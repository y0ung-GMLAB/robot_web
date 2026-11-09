"""연동 노드가 **살아 있나** · 웹의 역감시가 「죽음」 과 「느림」 을 가른다 · 끊김 시험 E (2026-11-08)

웹은 그룹 실행 중 연동 노드의 질문(`local-status`)이 2 s 끊기면 이 PC 재생을 세운다(연동 노드가 죽으면
진행 PC 의 정지가 이 PC 에 못 온다) · 그런데 연동 노드가 통째로 2~3 s 멈췄다 깨어나는 일이 실물에 있었다
(끊김 시험 B) · 그때도 섰다.

연동 노드가 뜰 때 제 PID 를 `<워크스페이스>/log/motion_coordination.pid` 에 적는다 · 웹은 그 PID 의
`/proc/<pid>` 가 있고 명령줄에 `motion_coordination` 이 있으면 「살아 있음(느림)」 으로 본다 · 파일이
없거나 읽지 못하면 「모름」 = 죽음으로 본다(지금까지와 같은 2 s).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from . import paths

COORDINATION_PID_FILENAME = 'motion_coordination.pid'
COORDINATION_MARKER = 'motion_coordination'


def coordination_pid_path(workspace: Optional[Path] = None) -> Path:
    root = Path(workspace) if workspace is not None else Path(
        os.environ.get(paths.WORKSPACE_ENV) or Path.cwd()
    ).expanduser()
    return root / paths.LOG_DIRNAME / COORDINATION_PID_FILENAME


def write_pid_file(path: Path, pid: Optional[int] = None) -> bool:
    """제 PID 를 적는다 · 실패해도 노드는 돈다(웹은 「모름」 → 예전처럼 2 s)"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(f'{int(pid if pid is not None else os.getpid())}\n', encoding='utf-8')
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def pid_alive(pid: int, marker: str = COORDINATION_MARKER, *, proc_root: Path = Path('/proc')) -> bool:
    """그 PID 의 프로세스가 있고 좀비가 아니며 명령줄에 `marker` 가 있나"""
    if pid <= 0:
        return False
    base = proc_root / str(int(pid))
    try:
        cmdline = (base / 'cmdline').read_bytes().replace(b'\0', b' ').decode('utf-8', 'replace')
        stat = (base / 'stat').read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    # stat · 「pid (이름) 상태 …」 · 이름에 괄호가 있을 수 있어 마지막 ')' 뒤를 본다
    state = stat.rsplit(')', 1)[-1].split()[:1]
    if state and state[0] in {'Z', 'X'}:
        return False
    return marker in cmdline


def coordination_alive(path: Optional[Path] = None, *, proc_root: Path = Path('/proc')) -> bool:
    path = path if path is not None else coordination_pid_path()
    try:
        pid = int(path.read_text(encoding='utf-8').strip() or 0)
    except (OSError, ValueError):
        return False
    return pid_alive(pid, proc_root=proc_root)
