"""시간대 · 웹에서 이 PC 또는 같은 망 로봇 PC 전부 · 수정 목록 79 (2026-10-08 · 사용자 결정)

예전(§6-150 · §6-291)에는 root 권한이 필요해 화면은 칠 명령만 만들었고 나중에 화면에서 뺐다 ·
지금은 설치가 이 계정에 `org.freedesktop.timedate1.set-timezone` 하나만 허용한다(polkit ·
`scripts/setup/site.sh` `site_web_admin_permissions` · 81 Wi-Fi 와 같은 파일) · 그래서
`timedatectl set-timezone <도시>` 를 sudo 없이 부른다.

스케줄은 프로세스가 켜질 때의 시간대로 돈다(`datetime.now().astimezone()`) · 바꾼 뒤
2초 있다가 웹·스케줄 서비스(motion-control)를 다시 띄운다 · 응답이 먼저 나가게
`systemd-run --user --on-active=2` 로 건다(웹 프로세스가 제 서비스를 직접 내리면 응답 전에 죽는다).

스피커 PC 는 스케줄이 없어 시간대와 무관하다 · 모든 PC 적용에서 뺀다.
"""

from __future__ import annotations

import subprocess
import urllib.error
from typing import Any, Callable, Dict, Iterable, Mapping

from motion_common import local_clock

from .system_update import _http_json, _row

NOT_ALLOWED_HINT = (
    '이 계정에 시간대 변경 권한이 없습니다 · 이 PC 터미널에서 한 번 · '
    'bash ~/ros2_ws/scripts/allow_web_admin.sh'
)
RESTART_UNIT = 'robot-web-timezone-restart'


class SystemTimezone:
    def __init__(
        self,
        *,
        run: Callable[..., Any] = subprocess.run,
        zones: Callable[[], Iterable[str]] = local_clock.timezones,
        snapshot: Callable[[], Dict[str, Any]] = local_clock.snapshot,
        blocker: Callable[[], str] = lambda: '',
        restart_unit: str = 'motion-control.service',
        workspace_hint: str = '~/ros2_ws',
    ) -> None:
        self._run = run
        self._zones = zones
        self._snapshot = snapshot
        self._blocker = blocker
        #: 바꾼 뒤 다시 띄울 서비스 · 빈 값이면 안 띄운다(스피커 · 스케줄 없음 · 89)
        self._restart_unit = restart_unit
        self._workspace_hint = workspace_hint

    def _cmd(self, args):
        try:
            result = self._run(args, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)
        return int(getattr(result, 'returncode', 1)), str(getattr(result, 'stderr', '') or '')

    def status(self) -> Dict[str, Any]:
        return {'success': True, 'clock': self._snapshot(), 'timezones': list(self._zones())}

    def apply(self, zone: Any) -> Dict[str, Any]:
        zone = str(zone or '').strip()
        zones = list(self._zones())
        if not zone:
            return {'success': False, 'message': '시간대를 고르세요 (예 Asia/Seoul · Europe/Paris)'}
        if zones and zone not in zones:
            return {'success': False, 'message': f'목록에 없는 이름입니다 · {zone} · 도시 이름으로 고르세요'}
        current = str(self._snapshot().get('timezone') or '')
        if zone == current:
            return {'success': True, 'changed': False, 'message': f'이미 {zone} 입니다', 'clock': self._snapshot()}
        reason = self._blocker()
        if reason:
            return {'success': False, 'message': reason}
        code, err = self._cmd(['timedatectl', 'set-timezone', zone])
        if code != 0:
            low = err.lower()
            denied = 'interactive authentication required' in low or 'access denied' in low or 'not authorized' in low
            hint = NOT_ALLOWED_HINT.replace('~/ros2_ws', self._workspace_hint)
            return {'success': False, 'message': hint if denied else f'바꾸지 못했습니다 · {err.strip()}'}
        if not self._restart_unit:
            return {'success': True, 'changed': True, 'clock': self._snapshot(),
                    'message': f'{current or "?"} → {zone}'}
        # 스케줄이 새 시간대로 돌게 · 응답이 나간 뒤 다시 띄운다
        self._cmd([
            'systemd-run', '--user', '--on-active=2', '--unit', RESTART_UNIT, '--collect',
            'systemctl', '--user', 'restart', self._restart_unit,
        ])
        return {
            'success': True, 'changed': True, 'clock': self._snapshot(),
            'message': f'{current or "?"} → {zone} · 2초 뒤 프로그램을 다시 띄웁니다(스케줄이 새 시간대로)',
        }


def apply_all(
    network_pcs: Any,
    zone: Any,
    local: SystemTimezone,
    *,
    http: Callable[..., Dict[str, Any]] = _http_json,
) -> Dict[str, Any]:
    """같은 망의 연결된 로봇 PC 전부 · 이 PC 는 맨 뒤 · 스피커 · 끊긴 PC 는 건너뜀."""
    zone = str(zone or '').strip()
    rows = []
    local_row = None
    for pc in network_pcs or []:
        if not isinstance(pc, Mapping):
            continue
        row = _row(pc)
        if row['role'] == 'speaker':
            # 스피커도 바꾼다(로그 시각 · 89) · 옛 스피커 앱(주소 없음)이면 건너뜀 · 결과는 성공·실패 집계에 안 넣는다
            if not pc.get('online', True):
                rows.append({**row, 'success': True, 'message': '스피커 · 연결 안 됨 · 건너뜀'})
                continue
            try:
                result = http(f"{row['web_url']}/api/system/timezone", method='POST', timeout=25.0, body={'zone': zone})
                rows.append({**row, **result})
            except (OSError, ValueError, urllib.error.URLError):
                rows.append({**row, 'success': True, 'message': '스피커 · 옛 스피커 앱 · 건너뜀 (그 PC 터미널에서 install_speaker.sh 뒤 됨)'})
            continue
        if row['is_local']:
            local_row = row
            continue
        if not pc.get('online', True):
            rows.append({**row, 'success': False, 'message': '연결 안 됨 · 건너뜀'})
            continue
        try:
            result = http(f"{row['web_url']}/api/system/timezone", method='POST', timeout=25.0, body={'zone': zone})
            rows.append({**row, **result})
        except (OSError, ValueError, urllib.error.URLError) as exc:
            rows.append({**row, 'success': False, 'message': f'요청 실패 · {exc}'})
    if local_row is not None:
        rows.append({**local_row, **local.apply(zone)})
    robots = [row for row in rows if row['role'] != 'speaker']
    ok = [row for row in robots if row.get('success')]
    return {
        'success': bool(robots) and len(ok) == len(robots),
        'message': f'로봇 PC {len(ok)}/{len(robots)}대 {zone}',
        'pcs': rows,
    }
