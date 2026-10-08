"""시간대 · 웹에서 이 PC · 같은 망 로봇 PC 전부 · 수정 목록 79 (2026-10-08)"""

from types import SimpleNamespace

from motion_web_bridge import system_timezone
from motion_web_bridge.system_timezone import SystemTimezone

ZONES = ['Asia/Seoul', 'Europe/Paris']


class _Run:
    def __init__(self, rc=0, err=''):
        self.calls = []
        self.rc = rc
        self.err = err

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        if args[0] == 'timedatectl':
            return SimpleNamespace(returncode=self.rc, stdout='', stderr=self.err)
        return SimpleNamespace(returncode=0, stdout='', stderr='')


def _tz(run, current='Asia/Seoul', blocker=lambda: ''):
    return SystemTimezone(run=run, zones=lambda: ZONES, snapshot=lambda: {'timezone': current}, blocker=blocker)


def test_apply_sets_the_zone_without_sudo_then_restarts_the_web_service_later():
    run = _Run()
    result = _tz(run).apply('Europe/Paris')
    assert result['success'] is True and result['changed'] is True
    assert run.calls[0] == ['timedatectl', 'set-timezone', 'Europe/Paris']
    restart = run.calls[1]
    assert restart[:3] == ['systemd-run', '--user', '--on-active=2']
    assert restart[-4:] == ['systemctl', '--user', 'restart', 'motion-control.service']


def test_unknown_same_or_blocked_does_not_touch_the_clock():
    run = _Run()
    assert _tz(run).apply('Europe/Pari')['success'] is False
    assert _tz(run).apply('Asia/Seoul')['changed'] is False
    assert _tz(run, blocker=lambda: '재생 중').apply('Europe/Paris') == {'success': False, 'message': '재생 중'}
    assert _tz(run).apply('')['success'] is False
    assert run.calls == []


def test_missing_permission_points_to_the_one_line_fix():
    run = _Run(rc=1, err='Failed to set time zone: Interactive authentication required.')
    result = _tz(run).apply('Europe/Paris')
    assert result['success'] is False and 'allow_web_admin.sh' in result['message']
    assert len(run.calls) == 1, '실패하면 다시 띄우지 않는다'


def test_apply_all_does_every_online_robot_then_this_pc_and_skips_the_speaker():
    pcs = [
        {'pc_id': 'floating4', 'is_local': True, 'online': True, 'web_url': 'http://10.0.0.14:8000'},
        {'pc_id': 'floating1', 'online': True, 'web_url': 'http://10.0.0.11:8000'},
        {'pc_id': 'floating2', 'online': False, 'web_url': 'http://10.0.0.12:8000'},
        {'pc_id': 'speaker', 'role': 'speaker', 'online': True, 'web_url': 'http://10.0.0.20:8100'},
    ]
    sent = []

    def http(url, *, method='GET', timeout, body=None):
        sent.append((method, url, body))
        return {'success': True, 'message': 'ok'}

    result = system_timezone.apply_all(pcs, 'Europe/Paris', _tz(_Run()), http=http)

    assert sent == [('POST', 'http://10.0.0.11:8000/api/system/timezone', {'zone': 'Europe/Paris'})]
    assert [row['pc_id'] for row in result['pcs']][-1] == 'floating4'
    by_id = {row['pc_id']: row for row in result['pcs']}
    assert by_id['floating2']['success'] is False
    assert '무관' in by_id['speaker']['message']
    assert result['success'] is False, '끊긴 로봇 PC 가 있으면 전부 됨이 아니다'
