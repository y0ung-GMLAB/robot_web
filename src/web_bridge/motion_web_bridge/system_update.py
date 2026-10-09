"""웹에서 업데이트 · 이 PC 와 같은 망의 로봇 PC 전부 · 2026-10-08 (사용자 요청)

이 PC
    `bash scripts/install.sh --code-only` 를 **systemd 의 따로 된 작업**(`systemd-run --user`)
    으로 돌린다 · 설치가 웹 서비스(motion-control)를 내렸다 올리므로, 웹 프로세스의 자식으로
    돌리면 같이 죽는다 · 출력은 `log/system_update/update-<시각>.log` · 끝나면 옆에 `.rc`
    (종료 코드) · 관리자 비밀번호는 묻지 않는다(첫 설치 때 끝남 · 새 시스템 패키지가 필요하면
    install.sh 가 멈추고 터미널 설치를 안내한다).

모든 PC
    같은 망 PC 표(`runtime.network_pcs` · 수정 목록 75)의 **연결된 로봇 PC** 마다 그 PC 웹의
    `POST /api/system/update` 를 이 서버가 대신 부른다(브라우저가 남의 주소를 직접 부르지 않는다) ·
    이 PC 는 맨 마지막(제 웹이 내려가도 다른 PC 요청은 이미 나갔다) · 스피커 PC 는 다른 설치라
    여기서 하지 않고 안내만 한다.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

LOG_DIR = Path('log') / 'system_update'
STATE_FILE = 'state.json'
#: install.sh 가 끝까지 가면 쓴다 · 웹 업데이트 실패 뒤 터미널 설치로 복구됐는지 (82)
SUCCESS_FILE = 'last_success.json'
TAIL_LINES = 15
REMOTE_START_TIMEOUT_SEC = 5.0
REMOTE_STATUS_TIMEOUT_SEC = 2.5
SPEAKER_HINT = '스피커 PC 는 그 PC 터미널에서 · bash ~/robot_web/scripts/install_speaker.sh'
ROBOT_COMMAND = 'bash scripts/install.sh --code-only'
#: 스피커 PC · speaker_app 이 이 모듈을 그대로 쓴다(같은 저장소) · 2026-10-08
SPEAKER_COMMAND = 'bash scripts/install_speaker.sh --code-only'


class SystemUpdate:
    """이 PC 의 코드 갱신 · 시작 · 상태."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        run: Callable[..., Any] = subprocess.run,
        now: Callable[[], float] = time.time,
        blocker: Callable[[], str] = lambda: '',
        command: str = ROBOT_COMMAND,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self._run = run
        self._now = now
        self._blocker = blocker
        self._command = command

    # ------------------------------------------------------------------ #

    @property
    def log_dir(self) -> Path:
        return self.workspace_root / LOG_DIR

    def _read_state(self) -> Dict[str, Any]:
        try:
            data = json.loads((self.log_dir / STATE_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: Mapping[str, Any]) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.log_dir / f'{STATE_FILE}.tmp'
        tmp.write_text(json.dumps(dict(state), ensure_ascii=False), encoding='utf-8')
        tmp.replace(self.log_dir / STATE_FILE)

    def _git_hash(self) -> str:
        try:
            result = self._run(
                ['git', '-C', str(self.workspace_root), 'rev-parse', '--short', 'HEAD'],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return ''
        return str(getattr(result, 'stdout', '') or '').strip() if getattr(result, 'returncode', 1) == 0 else ''

    def _unit_active(self, unit: str) -> bool:
        if not unit:
            return False
        try:
            result = self._run(
                ['systemctl', '--user', 'is-active', '--quiet', unit],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return getattr(result, 'returncode', 1) == 0

    def _last_success(self) -> Dict[str, Any]:
        try:
            data = json.loads((self.log_dir / SUCCESS_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _failure_reason(tail: List[str]) -> str:
        """로그에서 사람이 읽을 이유 · install.sh 의 `!!` 줄 · 없으면 「멈춘 단계」 줄."""
        for line in tail:
            text = line.strip()
            if text.startswith('!!') and '되돌립니다' not in text and '되돌림' not in text and '다시 켰습니다' not in text:
                return text.lstrip('! ').strip()
        for line in tail:
            if line.strip().startswith('멈춘 단계'):
                return line.strip()
        return ''

    @staticmethod
    def _tail(path: Path, lines: int = TAIL_LINES) -> List[str]:
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            return []
        return [line for line in text.splitlines() if line.strip()][-lines:]

    # ------------------------------------------------------------------ #

    def status(self) -> Dict[str, Any]:
        """idle · running · done · failed · 마지막 줄들 · 지금 코드 버전."""
        state = self._read_state()
        out: Dict[str, Any] = {'success': True, 'git_hash': self._git_hash(), 'state': 'idle'}
        if not state:
            return out
        log = Path(state.get('log') or '')
        rc_path = Path(state.get('rc') or '')
        out.update({
            'started_at': state.get('started_at'),
            'before_hash': state.get('before_hash', ''),
            'tail': self._tail(log) if log.name else [],
        })
        if rc_path.name and rc_path.is_file():
            try:
                code = int(rc_path.read_text(encoding='utf-8').strip() or '1')
            except ValueError:
                code = 1
            finished = rc_path.stat().st_mtime
            out.update({
                'state': 'done' if code == 0 else 'failed',
                'exit_code': code,
                'finished_at': finished,
            })
            if code == 0:
                out['after_hash'] = out.get('git_hash', '')
            else:
                out['message'] = self._failure_reason(self._tail(log, 80) if log.name else []) or f'실패 (종료 코드 {code})'
                success = self._last_success()
                if float(success.get('time') or 0) > finished:
                    # 그 뒤 터미널에서 설치가 끝까지 됐다 · 실패만 남겨 두면 지금 상태를 잘못 읽는다
                    out.update({
                        'state': 'done', 'after_hash': str(success.get('hash') or out.get('git_hash', '')),
                        'message': '웹 업데이트는 실패했지만 그 뒤 설치로 복구됨',
                    })
            return out
        if self._unit_active(str(state.get('unit') or '')):
            out['state'] = 'running'
            return out
        out.update({'state': 'failed', 'message': '업데이트 작업이 결과 없이 끝났습니다 · 로그를 보세요'})
        success = self._last_success()
        if float(success.get('time') or 0) > float(state.get('started_at') or 0):
            out.update({
                'state': 'done', 'after_hash': str(success.get('hash') or out.get('git_hash', '')),
                'message': '웹 업데이트는 결과 없이 끝났지만 그 뒤 설치로 복구됨',
            })
        return out

    def start(self) -> Dict[str, Any]:
        current = self.status()
        if current.get('state') == 'running':
            return {**current, 'success': True, 'message': '이미 업데이트 중입니다'}
        reason = self._blocker()
        if reason:
            return {**current, 'success': False, 'message': reason}
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(self._now()))
        log = self.log_dir / f'update-{stamp}.log'
        rc = self.log_dir / f'update-{stamp}.rc'
        unit = f'robot-web-update-{stamp}'
        shell = f'{self._command} > "{log}" 2>&1; echo $? > "{rc}"'
        command = [
            'systemd-run', '--user', '--unit', unit, '--collect', '--quiet',
            f'--working-directory={self.workspace_root}',
            '/bin/bash', '-lc', shell,
        ]
        try:
            result = self._run(command, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            return {**current, 'success': False, 'message': f'업데이트를 시작하지 못했습니다 · {exc}'}
        if getattr(result, 'returncode', 1) != 0:
            detail = str(getattr(result, 'stderr', '') or '').strip()
            return {**current, 'success': False, 'message': f'업데이트를 시작하지 못했습니다 · {detail or "systemd-run 실패"}'}
        self._write_state({
            'unit': unit, 'log': str(log), 'rc': str(rc),
            'started_at': self._now(), 'before_hash': current.get('git_hash', ''),
        })
        return {**self.status(), 'success': True, 'message': '업데이트 시작 · 몇 분 걸립니다 · 이 PC 웹이 잠깐 끊깁니다'}


# ---------------------------------------------------------------------- #
# 같은 망의 로봇 PC 전부
# ---------------------------------------------------------------------- #

def _http_json(url: str, *, method: str = 'GET', timeout: float, body: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(dict(body or {})).encode('utf-8') if method == 'POST' else None
    request = urllib.request.Request(
        url, method=method, data=data,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 · 같은 망 PC
        payload = json.loads(response.read().decode('utf-8') or '{}')
    return payload if isinstance(payload, dict) else {}


def _row(pc: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        'pc_id': str(pc.get('pc_id') or ''),
        'display_name': str(pc.get('display_name') or pc.get('pc_id') or ''),
        'role': str(pc.get('role') or 'robot'),
        'is_local': bool(pc.get('is_local')),
        'is_master': bool(pc.get('is_master')),
        'web_url': str(pc.get('web_url') or ''),
    }


def robot_targets(network_pcs: Any) -> List[Dict[str, Any]]:
    """업데이트할 PC · 연결된 로봇 PC (스피커 · 끊긴 PC 는 빼고 표에만) · 이 PC 는 맨 뒤."""
    pcs = [pc for pc in (network_pcs or []) if isinstance(pc, Mapping)]
    robots = [pc for pc in pcs if str(pc.get('role') or 'robot') != 'speaker']
    remote = [pc for pc in robots if not pc.get('is_local')]
    local = [pc for pc in robots if pc.get('is_local')]
    return [_row(pc) for pc in remote + local]


def start_all(
    network_pcs: Any,
    local: SystemUpdate,
    *,
    http: Callable[..., Dict[str, Any]] = _http_json,
) -> Dict[str, Any]:
    rows = []
    for pc in network_pcs or []:
        if not isinstance(pc, Mapping):
            continue
        row = _row(pc)
        if not pc.get('online', True) and not row['is_local']:
            rows.append({**row, 'state': 'offline', 'message': '연결 안 됨 · 건너뜀'})
        elif row['role'] == 'speaker' and row['web_url']:
            # 스피커 PC · 그 앱의 같은 주소를 부른다 · 옛 스피커 앱이면 안내만
            try:
                result = http(f"{row['web_url']}/api/system/update", method='POST', timeout=REMOTE_START_TIMEOUT_SEC)
                rows.append({**row, **result, 'state': result.get('state') or ('running' if result.get('success') else 'failed')})
            except (OSError, ValueError, urllib.error.URLError):
                rows.append({**row, 'state': 'manual', 'message': SPEAKER_HINT})
        elif row['role'] == 'speaker':
            rows.append({**row, 'state': 'manual', 'message': SPEAKER_HINT})
    for target in robot_targets([pc for pc in (network_pcs or []) if isinstance(pc, Mapping)
                                 and (pc.get('online', True) or pc.get('is_local'))]):
        if target['is_local']:
            continue
        try:
            result = http(f"{target['web_url']}/api/system/update", method='POST', timeout=REMOTE_START_TIMEOUT_SEC)
            rows.append({**target, **result, 'state': result.get('state') or ('running' if result.get('success') else 'failed')})
        except (OSError, ValueError, urllib.error.URLError) as exc:
            rows.append({**target, 'state': 'failed', 'success': False, 'message': f'요청 실패 · {exc}'})
    local_row = next((row for row in robot_targets(network_pcs) if row['is_local']), None)
    if local_row is not None:
        rows.append({**local_row, **local.start()})
    started = [row for row in rows if row.get('state') == 'running']
    return {
        'success': bool(started),
        'message': f'{len(started)}대 업데이트 시작 · 이 PC 웹은 잠깐 끊겼다 돌아옵니다' if started else '시작한 PC 가 없습니다',
        'pcs': rows,
    }


def status_all(
    network_pcs: Any,
    local: SystemUpdate,
    *,
    http: Callable[..., Dict[str, Any]] = _http_json,
) -> Dict[str, Any]:
    rows = []
    for pc in network_pcs or []:
        if not isinstance(pc, Mapping):
            continue
        row = _row(pc)
        if row['role'] == 'speaker':
            if pc.get('online', True) and row['web_url']:
                try:
                    rows.append({**row, **http(f"{row['web_url']}/api/system/update", timeout=REMOTE_STATUS_TIMEOUT_SEC)})
                    continue
                except (OSError, ValueError, urllib.error.URLError):
                    pass
            rows.append({**row, 'state': 'manual', 'message': SPEAKER_HINT, 'git_hash': str(pc.get('git_hash') or '')})
            continue
        if row['is_local']:
            rows.append({**row, **local.status()})
            continue
        if not pc.get('online', True):
            rows.append({**row, 'state': 'offline', 'message': '연결 안 됨', 'git_hash': str(pc.get('git_hash') or '')})
            continue
        try:
            rows.append({**row, **http(f"{row['web_url']}/api/system/update", timeout=REMOTE_STATUS_TIMEOUT_SEC)})
        except (OSError, ValueError, urllib.error.URLError):
            # 업데이트 중에는 그 PC 웹이 잠깐 내려간다 · 실패가 아니라 기다림
            rows.append({**row, 'state': 'unreachable', 'message': '응답 없음 · 업데이트 중이면 잠시 뒤 돌아옵니다',
                         'git_hash': str(pc.get('git_hash') or '')})
    hashes = {str(row.get('git_hash') or '') for row in rows if row.get('role') != 'speaker' and row.get('git_hash')}
    return {'success': True, 'pcs': rows, 'same_version': len(hashes) <= 1}


def blocker_from_run_status(motion_run_status: Mapping[str, Any]) -> str:
    """재생·초기 이동 중이면 업데이트하지 않는다 (재시작이 모터를 세운다)."""
    from motion_common import run_state  # 지연 import · 시험에서 가볍게

    state = str((motion_run_status or {}).get('state') or '')
    if state and run_state.is_running(state):
        return f'이 PC 가 재생 중입니다({state}) · 정지한 뒤 업데이트하세요'
    return ''
