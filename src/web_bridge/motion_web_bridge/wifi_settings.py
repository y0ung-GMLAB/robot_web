"""Wi-Fi · 웹에서 이 PC 의 연결 보기·바꾸기 · 수정 목록 81 (2026-10-08 · 사용자 요청)

우분투 NetworkManager(`nmcli`)를 그대로 부른다 · 권한은 설치 때 polkit 규칙 하나
(`scripts/setup/site.sh` `site_web_admin_permissions` · 이 계정만 NetworkManager 설정 변경).

**되돌리기** · 원격으로 Wi-Fi 를 바꾸다 틀리면 그 PC 에 다시 못 붙는다 · 그래서 바꾸기 **전에**
`systemd-run --user --on-active=<초>` 로 「이전 연결 다시 켜고 새 연결 지우기」 를 걸어 둔다 ·
「유지」(confirm)를 누르면 그 예약을 지운다 · 웹 서비스가 재시작돼도 예약은 산다.

새 연결 · 이름 `robot-wifi-<SSID>` · Wi-Fi 절전 끔(`802-11-wireless.powersave 2` · 연동 지연 방지) ·
주소는 자동(DHCP · 공유기 예약 권장) 또는 고정.
"""

from __future__ import annotations

import ipaddress
import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

ROLLBACK_UNIT = 'robot-wifi-rollback'
DEFAULT_CONFIRM_SEC = 60
CONNECTION_PREFIX = 'robot-wifi-'
STATE_FILE = Path('log') / 'wifi' / 'pending.json'
POWERSAVE_DISABLE = '2'
POWERSAVE_TEXT = {'0': '기본값', '1': '그대로', '2': '꺼짐', '3': '켜짐'}
NOT_ALLOWED_HINT = (
    '이 계정에 Wi-Fi 설정 권한이 없습니다 · 이 PC 터미널에서 한 번 · '
    'bash ~/ros2_ws/scripts/allow_web_admin.sh'
)


def split_terse(line: str) -> List[str]:
    """`nmcli -t` 한 줄 · `:` 로 나누되 `\\:` 는 글자 그대로."""
    fields, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            fields.append(''.join(current))
            current = []
        else:
            current.append(char)
    fields.append(''.join(current))
    return fields


def _permission_denied(text: str) -> bool:
    low = text.lower()
    return 'not authorized' in low or 'insufficient privileges' in low or 'permission denied' in low


class WifiSettings:
    def __init__(
        self,
        workspace_root: Path,
        *,
        run: Callable[..., Any] = subprocess.run,
        now: Callable[[], float] = time.time,
        blocker: Callable[[], str] = lambda: '',
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self._run = run
        self._now = now
        self._blocker = blocker

    # ------------------------------------------------------------------ #

    def _cmd(self, args: List[str], timeout: float = 20.0):
        try:
            result = self._run(args, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return 127, '', f'{args[0]} 없음'
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, '', str(exc)
        return (
            int(getattr(result, 'returncode', 1)),
            str(getattr(result, 'stdout', '') or ''),
            str(getattr(result, 'stderr', '') or ''),
        )

    def _nmcli(self, *args: str, timeout: float = 20.0):
        return self._cmd(['nmcli', *args], timeout=timeout)

    def _device(self) -> Dict[str, str]:
        code, out, _ = self._nmcli('-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device')
        if code != 0:
            return {}
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) >= 4 and parts[1] == 'wifi':
                return {'device': parts[0], 'state': parts[2], 'connection': parts[3]}
        return {}

    def _state_path(self) -> Path:
        return self.workspace_root / STATE_FILE

    def _pending(self) -> Dict[str, Any]:
        try:
            data = json.loads(self._state_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        left = float(data.get('deadline', 0)) - self._now()
        if left <= 0:
            return {}
        code, _, _ = self._cmd(['systemctl', '--user', 'is-active', '--quiet', f'{ROLLBACK_UNIT}.timer'])
        if code != 0:
            return {}
        return {**data, 'seconds_left': round(left)}

    def _write_pending(self, data: Optional[Mapping[str, Any]]) -> None:
        path = self._state_path()
        if data is None:
            try:
                path.unlink()
            except OSError:
                pass
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(data), ensure_ascii=False), encoding='utf-8')

    # ------------------------------------------------------------------ #

    def status(self) -> Dict[str, Any]:
        device = self._device()
        if not device:
            return {'success': True, 'available': False, 'message': '이 PC 에 Wi-Fi 장치가 없거나 NetworkManager 가 응답하지 않습니다'}
        out: Dict[str, Any] = {
            'success': True, 'available': True,
            'device': device['device'], 'state': device['state'], 'connection': device['connection'],
            'ssid': '', 'signal': None, 'address': '', 'gateway': '', 'method': '', 'powersave': '',
        }
        if device['connection'] and device['connection'] != '--':
            code, show, _ = self._nmcli('-t', '-f', 'IP4.ADDRESS,IP4.GATEWAY', 'device', 'show', device['device'])
            if code == 0:
                for line in show.splitlines():
                    key, _, value = line.partition(':')
                    if key.startswith('IP4.ADDRESS') and not out['address']:
                        out['address'] = value
                    elif key == 'IP4.GATEWAY':
                        out['gateway'] = value
            code, conn, _ = self._nmcli(
                '-g', '802-11-wireless.ssid,802-11-wireless.powersave,ipv4.method',
                'connection', 'show', device['connection'],
            )
            if code == 0:
                values = conn.splitlines()
                if len(values) >= 3:
                    out['ssid'], power, out['method'] = values[0], values[1], values[2]
                    out['powersave'] = POWERSAVE_TEXT.get(power.strip(), power.strip())
            for network in self._list(rescan=False):
                if network['in_use']:
                    out['signal'] = network['signal']
                    out['ssid'] = out['ssid'] or network['ssid']
        pending = self._pending()
        if pending:
            out['pending'] = pending
        return out

    def _list(self, *, rescan: bool) -> List[Dict[str, Any]]:
        args = ['-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list', '--rescan', 'yes' if rescan else 'no']
        code, out, _ = self._nmcli(*args, timeout=30.0)
        if code != 0 and rescan:
            code, out, _ = self._nmcli(*args[:-1], 'no', timeout=30.0)
        if code != 0:
            return []
        best: Dict[str, Dict[str, Any]] = {}
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) < 4 or not parts[1]:
                continue
            try:
                signal = int(parts[2])
            except ValueError:
                signal = 0
            entry = {'ssid': parts[1], 'signal': signal, 'security': parts[3], 'in_use': parts[0].strip() == '*'}
            old = best.get(entry['ssid'])
            if old is None or entry['in_use'] or (signal > old['signal'] and not old['in_use']):
                best[entry['ssid']] = entry
        return sorted(best.values(), key=lambda item: (-int(item['in_use']), -item['signal']))

    def scan(self) -> Dict[str, Any]:
        if not self._device():
            return {'success': False, 'networks': [], 'message': 'Wi-Fi 장치가 없습니다'}
        networks = self._list(rescan=True)
        return {'success': True, 'networks': networks, 'message': f'{len(networks)}개 찾음'}

    # ------------------------------------------------------------------ #

    @staticmethod
    def _static_args(static: Optional[Mapping[str, Any]]) -> List[str]:
        if not static:
            return ['ipv4.method', 'auto']
        address = str(static.get('address') or '').strip()
        gateway = str(static.get('gateway') or '').strip()
        dns = str(static.get('dns') or '').strip() or gateway
        interface = ipaddress.ip_interface(address if '/' in address else f'{address}/24')
        if interface.version != 4:
            raise ValueError('IPv4 주소만 됩니다')
        gw = ipaddress.ip_address(gateway)
        if gw not in interface.network:
            raise ValueError(f'게이트웨이 {gw} 가 {interface.network} 안에 없습니다')
        servers = [str(ipaddress.ip_address(item.strip())) for item in dns.replace(',', ' ').split() if item.strip()]
        return [
            'ipv4.method', 'manual', 'ipv4.addresses', str(interface),
            'ipv4.gateway', str(gw), 'ipv4.dns', ' '.join(servers),
        ]

    @staticmethod
    def key_mgmt(security: str) -> str:
        """검색에서 본 보안 방식 → NetworkManager 키 관리 · WPA3 전용이면 SAE · 그 밖은 WPA-PSK."""
        text = str(security or '').upper()
        if 'WPA3' in text and 'WPA2' not in text and 'WPA1' not in text:
            return 'sae'
        return 'wpa-psk'

    def connect(
        self, ssid: Any, password: Any = '', static: Optional[Mapping[str, Any]] = None,
        confirm_sec: int = DEFAULT_CONFIRM_SEC, security: Any = '',
    ) -> Dict[str, Any]:
        ssid = str(ssid or '')
        password = str(password or '')
        security = str(security or '')
        if '802.1X' in security.upper():
            return {'success': False, 'message': '회사 인증(802.1X · 아이디·비밀번호) Wi-Fi 는 여기서 못 합니다 · 우분투 설정에서 연결하세요'}
        if security.strip() not in ('', '--') and not password:
            return {'success': False, 'message': '비밀번호가 있는 Wi-Fi 입니다 · 비밀번호를 넣으세요'}
        if not ssid or len(ssid.encode('utf-8')) > 32:
            return {'success': False, 'message': 'SSID 는 1~32 바이트여야 합니다'}
        if password and not 8 <= len(password) <= 63:
            return {'success': False, 'message': '비밀번호는 8~63 글자여야 합니다 (열린 Wi-Fi 면 비워 두기)'}
        reason = self._blocker()
        if reason:
            return {'success': False, 'message': reason}
        if self._pending():
            return {'success': False, 'message': '앞서 바꾼 연결이 확인을 기다립니다 · 「유지」 또는 「되돌리기」 먼저'}
        device = self._device()
        if not device:
            return {'success': False, 'message': 'Wi-Fi 장치가 없습니다'}
        try:
            ip_args = self._static_args(static)
        except ValueError as exc:
            return {'success': False, 'message': f'고정 IP 값 확인 · {exc}'}

        previous = device['connection'] if device['connection'] not in ('', '--') else ''
        name = f'{CONNECTION_PREFIX}{ssid}'
        if previous == name:
            return {'success': False, 'message': '이미 그 Wi-Fi 에 이 설정으로 연결돼 있습니다 · 다른 값이면 먼저 다른 Wi-Fi 로 바꾸세요'}
        self._nmcli('connection', 'delete', name)   # 같은 이름 옛 설정 · 없으면 실패해도 그만
        add = [
            'connection', 'add', 'type', 'wifi', 'ifname', device['device'], 'con-name', name, 'ssid', ssid,
            '802-11-wireless.powersave', POWERSAVE_DISABLE,
            'connection.autoconnect', 'yes', 'connection.autoconnect-priority', '0',
            *ip_args,
        ]
        if password:
            add += ['wifi-sec.key-mgmt', self.key_mgmt(security), 'wifi-sec.psk', password]
        code, _, err = self._nmcli(*add)
        if code != 0:
            hint = NOT_ALLOWED_HINT.replace('~/ros2_ws', str(self.workspace_root))
            return {'success': False, 'message': hint if _permission_denied(err) else f'연결 설정을 만들지 못했습니다 · {err.strip()}'}

        # 바꾸기 **전에** 되돌리기를 건다 · 확인 못 하면 이전 연결 다시 켜고 새 것은 지운다
        back = f'nmcli connection up {shlex.quote(previous)}; ' if previous else ''
        rollback = f'{back}nmcli connection delete {shlex.quote(name)}'
        seconds = max(20, int(confirm_sec))
        code, _, err = self._cmd([
            'systemd-run', '--user', f'--on-active={seconds}', '--unit', ROLLBACK_UNIT, '--collect',
            '/bin/sh', '-c', rollback,
        ])
        if code != 0:
            self._nmcli('connection', 'delete', name)
            return {'success': False, 'message': f'되돌리기 예약을 못 걸어 바꾸지 않았습니다 · {err.strip()}'}
        self._write_pending({
            'ssid': ssid, 'name': name, 'previous': previous,
            'deadline': self._now() + seconds, 'confirm_sec': seconds,
        })

        code, _, err = self._nmcli('connection', 'up', name, timeout=45.0)
        if code != 0:
            self.rollback()
            text = err.strip()
            if 'secrets were required' in text.lower() or 'password' in text.lower():
                text = '비밀번호가 맞지 않는 것 같습니다'
            return {'success': False, 'message': f'연결 실패 · 이전 연결로 되돌렸습니다 · {text}'}
        return {
            **self.status(), 'success': True,
            'message': f'{ssid} 연결됨 · {seconds}초 안에 「유지」 를 누르세요 · 안 누르면 이전 연결로 되돌립니다',
        }

    def confirm(self) -> Dict[str, Any]:
        pending = self._pending()
        if not pending:
            self._write_pending(None)
            return {**self.status(), 'success': False, 'message': '확인을 기다리는 변경이 없습니다'}
        self._cmd(['systemctl', '--user', 'stop', f'{ROLLBACK_UNIT}.timer'])
        self._nmcli('connection', 'modify', pending['name'], 'connection.autoconnect-priority', '10')
        self._write_pending(None)
        return {**self.status(), 'success': True, 'message': f"{pending['ssid']} 유지 · 다음 부팅에도 이 Wi-Fi 를 먼저 씁니다"}

    def rollback(self) -> Dict[str, Any]:
        """지금 바로 되돌린다 (예약을 앞당겨 실행)."""
        try:
            pending = json.loads(self._state_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pending = {}
        self._cmd(['systemctl', '--user', 'stop', f'{ROLLBACK_UNIT}.timer'])
        if isinstance(pending, dict) and pending.get('name'):
            if pending.get('previous'):
                self._nmcli('connection', 'up', str(pending['previous']), timeout=45.0)
            self._nmcli('connection', 'delete', str(pending['name']))
        self._write_pending(None)
        return {**self.status(), 'success': True, 'message': '이전 연결로 되돌렸습니다'}
