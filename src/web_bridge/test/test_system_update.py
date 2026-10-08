"""웹에서 업데이트 · 이 PC · 같은 망 로봇 PC 전부 (2026-10-08)"""

from types import SimpleNamespace

from motion_web_bridge import system_update
from motion_web_bridge.system_update import SystemUpdate, blocker_from_run_status


class _Runner:
    """subprocess.run 대역 · 명령을 적어 두고 정해 둔 답을 돌려준다."""

    def __init__(self, active=True, systemd_rc=0):
        self.calls = []
        self.active = active
        self.systemd_rc = systemd_rc

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        if command[:2] == ['git', '-C']:
            return SimpleNamespace(returncode=0, stdout='abc1234\n', stderr='')
        if command[:3] == ['systemctl', '--user', 'is-active']:
            return SimpleNamespace(returncode=0 if self.active else 3, stdout='', stderr='')
        if command[0] == 'systemd-run':
            return SimpleNamespace(returncode=self.systemd_rc, stdout='', stderr='no user bus')
        raise AssertionError(command)


def test_start_runs_code_only_install_in_its_own_systemd_job(tmp_path):
    runner = _Runner()
    update = SystemUpdate(tmp_path, run=runner, now=lambda: 1_700_000_000.0)

    result = update.start()

    assert result['success'] is True and result['state'] == 'running'
    [launch] = [c for c in runner.calls if c[0] == 'systemd-run']
    assert launch[:3] == ['systemd-run', '--user', '--unit']
    assert launch[3].startswith('robot-web-update-')
    assert '--collect' in launch
    assert 'bash scripts/install.sh --code-only' in launch[-1]
    assert f'--working-directory={tmp_path}' in launch
    assert result['before_hash'] == 'abc1234'


def test_status_reads_the_exit_code_and_the_last_lines(tmp_path):
    runner = _Runner()
    update = SystemUpdate(tmp_path, run=runner, now=lambda: 1_700_000_000.0)
    update.start()
    state = update._read_state()
    open(state['log'], 'w', encoding='utf-8').write('== 2. Git\n원격과 같아졌습니다\n설치 완료\n')
    open(state['rc'], 'w', encoding='utf-8').write('0\n')

    status = update.status()

    assert status['state'] == 'done' and status['exit_code'] == 0
    assert status['tail'][-1] == '설치 완료'

    open(state['rc'], 'w', encoding='utf-8').write('1\n')
    assert update.status()['state'] == 'failed'


def test_a_job_that_vanished_without_a_result_is_failed(tmp_path):
    runner = _Runner(active=True)
    update = SystemUpdate(tmp_path, run=runner, now=lambda: 1_700_000_000.0)
    update.start()
    runner.active = False

    status = update.status()

    assert status['state'] == 'failed'
    assert '결과 없이' in status['message']


def test_running_or_blocked_does_not_start_again(tmp_path):
    runner = _Runner()
    update = SystemUpdate(tmp_path, run=runner, now=lambda: 1_700_000_000.0)
    update.start()
    again = update.start()
    assert again['message'] == '이미 업데이트 중입니다'
    assert sum(1 for c in runner.calls if c[0] == 'systemd-run') == 1

    blocked = SystemUpdate(tmp_path / 'other', run=_Runner(), blocker=lambda: '재생 중')
    result = blocked.start()
    assert result['success'] is False and result['message'] == '재생 중'


def test_systemd_run_failure_is_reported(tmp_path):
    update = SystemUpdate(tmp_path, run=_Runner(systemd_rc=1))
    result = update.start()
    assert result['success'] is False
    assert 'no user bus' in result['message']


def test_a_playing_pc_refuses():
    assert '재생 중' in blocker_from_run_status({'state': 'running'})
    assert '재생 중' in blocker_from_run_status({'state': 'initializing'})
    assert blocker_from_run_status({'state': 'idle'}) == ''
    assert blocker_from_run_status({}) == ''


PCS = [
    {'pc_id': 'floating4', 'role': 'robot', 'is_local': True, 'online': True, 'web_url': 'http://10.0.0.14:8000'},
    {'pc_id': 'floating1', 'role': 'robot', 'online': True, 'web_url': 'http://10.0.0.11:8000', 'git_hash': 'old'},
    {'pc_id': 'floating2', 'role': 'robot', 'online': False, 'web_url': 'http://10.0.0.12:8000', 'git_hash': 'old'},
    {'pc_id': 'speaker', 'role': 'speaker', 'online': True, 'web_url': 'http://10.0.0.20:8100'},
]


class _Local:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True
        return {'success': True, 'state': 'running', 'git_hash': 'old'}

    def status(self):
        return {'success': True, 'state': 'running', 'git_hash': 'old'}


def test_start_all_asks_each_online_robot_then_this_pc_last():
    calls = []

    def http(url, *, method='GET', timeout):
        calls.append((method, url))
        return {'success': True, 'state': 'running'}

    local = _Local()
    result = system_update.start_all(PCS, local, http=http)

    assert calls == [
        ('POST', 'http://10.0.0.20:8100/api/system/update'),   # 스피커도 같은 주소로 (2026-10-08)
        ('POST', 'http://10.0.0.11:8000/api/system/update'),
    ]
    assert local.started is True
    by_id = {row['pc_id']: row for row in result['pcs']}
    assert by_id['floating2']['state'] == 'offline'
    assert by_id['speaker']['state'] == 'running'
    assert [row['pc_id'] for row in result['pcs']][-1] == 'floating4', '이 PC 는 맨 뒤'
    assert result['success'] is True


def test_status_all_marks_a_restarting_pc_unreachable_not_failed():
    def http(url, *, method='GET', timeout):
        raise OSError('connection refused')

    result = system_update.status_all(PCS, _Local(), http=http)
    by_id = {row['pc_id']: row for row in result['pcs']}
    assert by_id['floating1']['state'] == 'unreachable'
    assert by_id['floating4']['state'] == 'running'
    assert by_id['speaker']['state'] == 'manual'


def test_status_all_reports_whether_robot_versions_match():
    def http(url, *, method='GET', timeout):
        return {'state': 'done', 'git_hash': 'new'}

    local = _Local()
    local.status = lambda: {'state': 'done', 'git_hash': 'new'}
    pcs = [pc for pc in PCS if pc['pc_id'] != 'floating2']
    assert system_update.status_all(pcs, local, http=http)['same_version'] is True
    local.status = lambda: {'state': 'done', 'git_hash': 'other'}
    assert system_update.status_all(pcs, local, http=http)['same_version'] is False


def test_an_old_speaker_app_without_the_endpoint_gets_the_terminal_hint():
    def http(url, *, method='GET', timeout):
        if ':8100/' in url:
            raise OSError('404')
        return {'success': True, 'state': 'running'}

    result = system_update.start_all(PCS, _Local(), http=http)
    speaker = next(row for row in result['pcs'] if row['pc_id'] == 'speaker')
    assert speaker['state'] == 'manual' and 'install_speaker.sh' in speaker['message']


def test_the_speaker_runs_its_own_installer(tmp_path):
    runner = _Runner()
    SystemUpdate(tmp_path, run=runner, command=system_update.SPEAKER_COMMAND).start()
    [launch] = [c for c in runner.calls if c[0] == 'systemd-run']
    assert 'bash scripts/install_speaker.sh --code-only' in launch[-1]
