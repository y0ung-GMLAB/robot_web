"""Wi-Fi · 웹에서 이 PC 연결 바꾸기 · 60초 확인 없으면 되돌림 · 수정 목록 81 (2026-10-08)"""

from types import SimpleNamespace

from motion_web_bridge.wifi_settings import WifiSettings, split_terse


def test_terse_lines_keep_escaped_colons():
    assert split_terse('*:my\\:net:72:WPA2') == ['*', 'my:net', '72', 'WPA2']


class _Nm:
    """nmcli · systemd-run · systemctl 대역"""

    def __init__(self, *, connection='old-home', up_rc=0, add_err=''):
        self.calls = []
        self.connection = connection
        self.up_rc = up_rc
        self.add_err = add_err
        self.timer_active = False

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        ok = SimpleNamespace(returncode=0, stdout='', stderr='')
        if args[:2] == ['nmcli', '-t'] and 'device' in args and args[-1] == 'device':
            return SimpleNamespace(returncode=0, stdout=f'eno1:ethernet:connected:wired\nwlp2s0:wifi:connected:{self.connection}\n', stderr='')
        if args[:3] == ['nmcli', '-t', '-f'] and 'list' in args:
            return SimpleNamespace(returncode=0, stdout='*:shop:72:WPA2\n:guest:40:\n:shop:30:WPA2\n:secure6:60:WPA3\n', stderr='')
        if args[:2] == ['nmcli', 'connection'] and args[2] == 'add':
            return SimpleNamespace(returncode=4 if self.add_err else 0, stdout='', stderr=self.add_err)
        if args[:3] == ['nmcli', 'connection', 'up']:
            return SimpleNamespace(returncode=self.up_rc, stdout='', stderr='Secrets were required, but not provided')
        if args[0] == 'systemd-run':
            self.timer_active = True
            return ok
        if args[:3] == ['systemctl', '--user', 'is-active']:
            return SimpleNamespace(returncode=0 if self.timer_active else 3, stdout='', stderr='')
        if args[:3] == ['systemctl', '--user', 'stop']:
            self.timer_active = False
            return ok
        return ok

    def find(self, prefix):
        return [c for c in self.calls if c[:len(prefix)] == prefix]


def test_scan_dedupes_and_puts_the_connected_one_first(tmp_path):
    wifi = WifiSettings(tmp_path, run=_Nm())
    networks = wifi.scan()['networks']
    assert [n['ssid'] for n in networks] == ['shop', 'secure6', 'guest']
    assert networks[0]['in_use'] is True and networks[0]['signal'] == 72


def test_connect_arms_the_rollback_before_switching_and_keeps_power_save_off(tmp_path):
    nm = _Nm()
    wifi = WifiSettings(tmp_path, run=nm, now=lambda: 1000.0)

    result = wifi.connect('shop', 'secret123', security='WPA2')

    assert result['success'] is True
    order = [c[0] if c[0] != 'nmcli' else ' '.join(c[1:3]) for c in nm.calls]
    assert order.index('systemd-run') < order.index('connection up'), '되돌리기를 먼저 건다'
    [run] = nm.find(['systemd-run'])
    assert '--on-active=60' in run and run[-1] == "nmcli connection up old-home; nmcli connection delete robot-wifi-shop"
    [add] = nm.find(['nmcli', 'connection', 'add'])
    assert add[add.index('802-11-wireless.powersave') + 1] == '2'
    assert add[add.index('wifi-sec.key-mgmt') + 1] == 'wpa-psk'
    assert add[add.index('ipv4.method') + 1] == 'auto'
    assert '60초' in result['message']


def test_wpa3_only_uses_sae_and_enterprise_is_refused(tmp_path):
    nm = _Nm()
    WifiSettings(tmp_path, run=nm).connect('secure6', 'secret123', security='WPA3')
    [add] = nm.find(['nmcli', 'connection', 'add'])
    assert add[add.index('wifi-sec.key-mgmt') + 1] == 'sae'
    result = WifiSettings(tmp_path / 'b', run=_Nm()).connect('corp', 'secret123', security='WPA2 802.1X')
    assert result['success'] is False and '802.1X' in result['message']


def test_a_locked_network_needs_a_password(tmp_path):
    result = WifiSettings(tmp_path, run=_Nm()).connect('shop', '', security='WPA2')
    assert result['success'] is False and '비밀번호' in result['message']
    short = WifiSettings(tmp_path, run=_Nm()).connect('shop', '1234', security='WPA2')
    assert short['success'] is False and '8~63' in short['message']


def test_wrong_password_rolls_back_at_once(tmp_path):
    nm = _Nm(up_rc=4)
    result = WifiSettings(tmp_path, run=nm).connect('shop', 'wrongpass', security='WPA2')
    assert result['success'] is False
    assert '비밀번호가 맞지 않는' in result['message'] and '되돌렸습니다' in result['message']
    assert nm.find(['systemctl', '--user', 'stop'])
    assert ['nmcli', 'connection', 'up', 'old-home'] in nm.calls
    # 이전 연결을 다시 켠 **뒤** 새 설정을 지운다
    back = nm.calls.index(['nmcli', 'connection', 'up', 'old-home'])
    assert ['nmcli', 'connection', 'delete', 'robot-wifi-shop'] in nm.calls[back:]


def test_confirm_cancels_the_rollback_and_prefers_the_new_network(tmp_path):
    nm = _Nm()
    wifi = WifiSettings(tmp_path, run=nm, now=lambda: 1000.0)
    wifi.connect('shop', 'secret123', security='WPA2')
    assert wifi.status()['pending']['ssid'] == 'shop'

    result = wifi.confirm()

    assert result['success'] is True
    assert nm.timer_active is False
    assert ['nmcli', 'connection', 'modify', 'robot-wifi-shop', 'connection.autoconnect-priority', '10'] in nm.calls
    assert 'pending' not in wifi.status()


def test_static_ip_is_checked_and_written(tmp_path):
    nm = _Nm()
    wifi = WifiSettings(tmp_path, run=nm)
    bad = wifi.connect('shop', 'secret123', {'address': '192.168.0.13/24', 'gateway': '10.0.0.1'}, security='WPA2')
    assert bad['success'] is False and '게이트웨이' in bad['message']
    good = wifi.connect('shop', 'secret123', {'address': '192.168.0.13', 'gateway': '192.168.0.1'}, security='WPA2')
    assert good['success'] is True
    [add] = nm.find(['nmcli', 'connection', 'add'])
    assert add[add.index('ipv4.addresses') + 1] == '192.168.0.13/24'
    assert add[add.index('ipv4.dns') + 1] == '192.168.0.1'


def test_missing_permission_points_to_the_one_line_fix(tmp_path):
    nm = _Nm(add_err='Error: Insufficient privileges.')
    result = WifiSettings(tmp_path, run=nm).connect('shop', 'secret123', security='WPA2')
    assert result['success'] is False and 'allow_web_admin.sh' in result['message']


def test_playing_pc_refuses(tmp_path):
    result = WifiSettings(tmp_path, run=_Nm(), blocker=lambda: '재생 중').connect('shop', 'secret123', security='WPA2')
    assert result == {'success': False, 'message': '재생 중'}
