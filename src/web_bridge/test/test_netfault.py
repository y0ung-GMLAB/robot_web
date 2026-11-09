"""자동 끊김 시험 · 2026-11-08 (scripts/netfault.py · 수정 목록 184)

실제 iptables · tc 없이 · 명령 문자열과 판정 함수만 본다.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('netfault', ROOT / 'scripts/netfault.py')
netfault = importlib.util.module_from_spec(spec)
sys.modules['netfault'] = netfault   # dataclass 가 제 모듈을 찾는다
spec.loader.exec_module(netfault)

IFACES = {
    'lo': {'mac': '00:00:00:00:00:00', 'wireless': False, 'up': True},
    'enp1s0': {'mac': 'aa:bb:cc:00:00:01', 'wireless': False, 'up': True},
    'wlo1': {'mac': 'aa:bb:cc:00:00:02', 'wireless': True, 'up': True},
    'enp2s0': {'mac': 'aa:bb:cc:00:00:03', 'wireless': False, 'up': False},
}
CONF = 'MASTER0_DEVICE="AA:BB:CC:00:00:01"\nDEVICE_MODULES="generic"\n'


def ethercat():
    return netfault.ethercat_ifaces(netfault.parse_ethercat_devices([CONF]), IFACES)


def test_ethercat_nic_is_found_by_mac_and_never_picked():
    assert ethercat() == {'enp1s0'}
    assert netfault.pick_iface('', IFACES, ethercat()) == 'wlo1'
    with pytest.raises(netfault.NetfaultError, match='EtherCAT'):
        netfault.pick_iface('enp1s0', IFACES, ethercat(), allow_wired=True)
    with pytest.raises(netfault.NetfaultError, match='lo'):
        netfault.pick_iface('lo', IFACES, ethercat(), allow_wired=True)


def test_wired_port_needs_explicit_flag_and_empty_conf_means_no_ethercat():
    with pytest.raises(netfault.NetfaultError, match='--allow-wired'):
        netfault.pick_iface('enp2s0', IFACES, ethercat())
    assert netfault.pick_iface('enp2s0', IFACES, ethercat(), allow_wired=True) == 'enp2s0'
    assert netfault.parse_ethercat_devices(['MASTER0_DEVICE=""\n']) == []


def test_auto_pick_refuses_when_wifi_is_ambiguous():
    two = dict(IFACES, wlp3s0={'mac': 'x', 'wireless': True, 'up': True})
    with pytest.raises(netfault.NetfaultError, match='--iface'):
        netfault.pick_iface('', two, ethercat())


def test_dds_ports_for_group_domain_21_leave_local_domain_22_alone():
    assert netfault.dds_port_range(21) == (12650, 12899)
    low22, _ = netfault.dds_port_range(22)
    assert low22 == 12900


def test_dds_cut_only_blocks_group_ports_on_wifi():
    commands = [' '.join(c) for c in netfault.cut_commands('wlo1', 'dds', (12650, 12899))]
    assert 'iptables -A RW_NETFAULT -p udp --dport 12650:12899 -j DROP' in commands
    assert 'iptables -I INPUT 1 -i wlo1 -j RW_NETFAULT' in commands
    assert 'iptables -I OUTPUT 1 -o wlo1 -j RW_NETFAULT' in commands
    assert not any('enp1s0' in c or ' lo ' in c for c in commands)
    everything = [' '.join(c) for c in netfault.cut_commands('wlo1', 'all', (12650, 12899))]
    assert 'iptables -A RW_NETFAULT -j DROP' in everything


def test_lag_marks_only_dds_and_netem_on_its_own_band():
    commands = [' '.join(c) for c in netfault.lag_commands(
        'wlo1', 'dds', (12650, 12899), delay_ms=200, jitter_ms=100, loss_pct=30,
    )]
    assert any('--dport 12650:12899 -j MARK --set-mark 0x2a' in c for c in commands)
    assert 'tc qdisc add dev wlo1 parent 77:4 handle 78: netem delay 200ms 100ms loss 30%' in commands
    assert any(c.endswith('handle 0x2a fw flowid 77:4') for c in commands)


def test_restore_removes_everything_it_added_and_only_our_qdisc():
    restore = [' '.join(c) for c in netfault.restore_commands('wlo1')]
    for added in netfault.cut_commands('wlo1', 'dds', (1, 2)) + netfault.lag_commands(
        'wlo1', 'dds', (1, 2), delay_ms=1, jitter_ms=0, loss_pct=0,
    ):
        text = ' '.join(added)
        if text.startswith('iptables') and (' -I ' in text):
            removal = text.replace(' -I INPUT 1 ', ' -D INPUT ').replace(' -I OUTPUT 1 ', ' -D OUTPUT ')
            assert removal in restore, removal
    assert 'iptables -X RW_NETFAULT' in restore and 'iptables -t mangle -X RW_NETFAULT_MARK' in restore
    assert any('qdisc prio 77:' in c and 'tc qdisc del dev wlo1 root' in c for c in restore)


def test_restore_is_scheduled_before_the_fault_with_grace():
    command = netfault.schedule_restore_command('/x/netfault.py', 'wlo1', 150 + netfault.RESTORE_GRACE_SEC)
    text = ' '.join(command)
    assert text.startswith('systemd-run --unit=rw-netfault-restore --on-active=180s')
    assert text.endswith('/x/netfault.py restore --iface wlo1 --from-timer')


def test_fault_schedules_restore_first_and_lifts_on_exit():
    runner = netfault.Runner(dry_run=True)
    with netfault.Fault(runner, 'wlo1', '/x/netfault.py') as fault:
        fault.inject(netfault.cut_commands('wlo1', 'dds', (12650, 12899)), 20)
    lines = runner.lines
    timer = next(i for i, line in enumerate(lines) if line.startswith('systemd-run'))
    first_drop = next(i for i, line in enumerate(lines) if '-j DROP' in line)
    assert timer < first_drop, '원복 예약이 먼저'
    assert lines[-1].startswith('systemctl reset-failed'), '끝나면 예약 취소'
    assert any(line == 'iptables -X RW_NETFAULT' for line in lines[first_drop:])


def row(phase='running', execution='ex1', cycle=3, failure_at=0.0, failure=''):
    return {
        'pc_id': '', 'phase': phase, 'execution_id': execution, 'cycle': cycle,
        'elapsed': 10.0, 'duration': 920.0, 'start_failure_at': failure_at, 'start_failure': failure,
    }


def samples_from(timeline):
    """[(t, {pc: row|None}), ...] → 표본"""
    return [{'t': t, 'pcs': pcs} for t, pcs in timeline]


PCS = ['f1', 'f2', 'f3', 'f4']


def all_running(**override):
    rows = {pc: row() for pc in PCS}
    rows.update(override)
    return rows


def test_2b_passes_when_everyone_keeps_playing_and_ends_together():
    timeline = [(t, all_running()) for t in range(100, 400)]
    timeline[150] = (250, all_running(f1=None))      # 끊긴 마스터를 잠깐 못 읽음 = 모름
    verdict = netfault.judge(netfault.SCENARIOS['2b'], samples_from(timeline), PCS, 'f1',
                             fault_start=100, fault_end=250, end=399)
    assert verdict.ok, verdict.reasons
    assert '합격 · 2b' in verdict.line('2b')


def test_2b_fails_when_a_slave_stands_or_start_fails():
    timeline = [(t, all_running()) for t in range(100, 400)]
    for t in range(200, 230):
        timeline[t - 100] = (t, all_running(f3=row(phase='stopped', execution='')))
    timeline[-1] = (399, all_running(f2=row(failure_at=300.0, failure='트리거가 이미 지났습니다')))
    verdict = netfault.judge(netfault.SCENARIOS['2b'], samples_from(timeline), PCS, 'f1',
                             fault_start=100, fault_end=250, end=399)
    assert not verdict.ok
    assert any('f3' in r and '서 있음' in r for r in verdict.reasons)
    assert any('f2 시작 실패' in r for r in verdict.reasons)


def test_short_gap_at_cycle_change_is_tolerated():
    timeline = [(t, all_running()) for t in range(100, 200)]
    timeline[50] = (150, all_running(f2=row(phase='completed')))
    timeline[51] = (151, all_running(f2=row(phase='completed')))
    verdict = netfault.judge(netfault.SCENARIOS['lag'], samples_from(timeline), PCS, 'f2',
                             fault_start=100, fault_end=180, end=199)
    assert verdict.ok, verdict.reasons


def test_3b_fails_when_slave_ends_outside_master_execution_or_log_shows_drop():
    timeline = [(t, all_running()) for t in range(100, 300)]
    timeline[-1] = (299, all_running(f3=row(phase='stopped', execution='')))
    verdict = netfault.judge(netfault.SCENARIOS['3b'], samples_from(timeline), PCS, 'f3',
                             fault_start=100, fault_end=120, end=299,
                             log_text='정지된 그룹 실행의 지연 명령을 폐기했습니다\n')
    assert not verdict.ok
    assert any('실행이 갈림' in r for r in verdict.reasons)
    assert any('지연 명령을 폐기' in r for r in verdict.reasons)


def test_3b_allows_the_cut_slave_to_wait_but_not_the_others():
    timeline = [(t, all_running()) for t in range(100, 300)]
    for t in range(130, 200):
        timeline[t - 100] = (t, all_running(f3=row(phase='stopped', execution='')))
    verdict = netfault.judge(netfault.SCENARIOS['3b'], samples_from(timeline), PCS, 'f3',
                             fault_start=100, fault_end=120, end=299,
                             log_text='빠졌던 그룹 실행으로 복귀 권유 받음 · ex1\n그룹 복귀 · f3 · 5회차부터 합류\n')
    assert verdict.ok, verdict.reasons
    assert any('f3(끊긴 PC) 가장 길게 선 시간 70 s' in n for n in verdict.notes)


def stopped():
    return row(phase='stopped', execution='')


def test_4_passes_when_others_stop_at_once_and_cut_pc_stops_after_reconnect():
    timeline = []
    for t in range(100, 300):
        rows = all_running()
        if t >= 142:
            rows.update(f1=stopped(), f3=stopped(), f4=stopped())
        if t >= 226:
            rows['f2'] = stopped()
        timeline.append((t, rows))
    verdict = netfault.judge(netfault.SCENARIOS['4'], samples_from(timeline), PCS, 'f2',
                             fault_start=100, fault_end=220, end=299, stop_sent_at=140.5)
    assert verdict.ok, verdict.reasons
    assert any('6.0 s 뒤 섬' in n for n in verdict.notes)


def test_4_fails_when_cut_pc_keeps_playing_old_execution():
    timeline = []
    for t in range(100, 300):
        rows = all_running()
        if t >= 142:
            rows.update(f1=stopped(), f3=stopped(), f4=stopped())
        timeline.append((t, rows))
    verdict = netfault.judge(netfault.SCENARIOS['4'], samples_from(timeline), PCS, 'f2',
                             fault_start=100, fault_end=220, end=299, stop_sent_at=140.5)
    assert not verdict.ok
    assert any('f2(끊긴 PC)' in r for r in verdict.reasons)


def test_summarize_reads_the_coordination_snapshot_fields():
    snapshot = {'runtime': {
        'config': {'pc_id': 'f2', 'dds_domain_id': 21},
        'local': {'pc_id': 'f2', 'motion_phase': 'running', 'current_cycle': 4,
                  'motion_elapsed_sec': 900.0, 'motion_duration_sec': 920.0},
        'execution': {'execution_id': 'ex1', 'coordinator_id': 'f1', 'participants': ['f1', 'f2'],
                      'lost': {'f3': 12.0}},
        'last_start_failure': {'message': 'x', 'at': 5.0},
        'peers': [{'pc_id': 'f1', 'web_url': 'http://192.168.50.11:8000'}, {'pc_id': 'spk'}],
    }}
    summary = netfault.summarize(snapshot)
    assert summary['pc_id'] == 'f2' and summary['domain'] == 21 and summary['coordinator_id'] == 'f1'
    assert netfault.remaining_sec(summary) == pytest.approx(20.0)
    assert netfault.remaining_sec(dict(summary, phase='initializing')) is None
    assert netfault.discover_pcs(snapshot) == {'f2': netfault.LOCAL_URL, 'f1': 'http://192.168.50.11:8000'}


def test_dry_run_scenario_prints_plan_without_root_or_web(monkeypatch, capsys):
    def no_web(*_args, **_kwargs):
        raise OSError('웹 없음')

    monkeypatch.setattr(netfault, 'http_json', no_web)
    monkeypatch.setattr(netfault, 'read_ifaces', lambda: IFACES)
    monkeypatch.setattr(netfault, 'read_ethercat_devices', lambda: netfault.parse_ethercat_devices([CONF]))
    assert netfault.main(['scenario', '2b', '--dry-run']) == 0
    out = capsys.readouterr().out
    assert '랜카드 wlo1' in out and '12650:12899' in out and 'systemd-run' in out
    assert 'enp1s0' not in out


def test_mode_all_needs_explicit_remote_cut_confirmation(capsys):
    assert netfault.main(['cut', '--mode', 'all', '--dry-run']) == 2
    assert 'AnyDesk' in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# 시간표 재생 · 수정 목록 186 · 끊긴 PC 도 계속 재생 · 회차를 쉰 PC 가 없어야
# --------------------------------------------------------------------------- #

def _clock_samples(standing=None, note=None):
    samples = []
    for step in range(0, 200, 5):
        pcs = {}
        for pc_id in PCS:
            stand = standing and pc_id == standing[0] and standing[1] <= step <= standing[2]
            pcs[pc_id] = {
                'phase': 'idle' if stand else 'running', 'execution_id': '' if stand else 'tt-s100',
                'sync_mode': 'clock', 'tt_note': note[1] if note and pc_id == note[0] else '',
            }
        samples.append({'t': float(step), 'pcs': pcs})
    return samples


def test_clock_mode_is_detected_and_the_cut_pc_must_keep_playing_too():
    verdict = netfault.judge(netfault.SCENARIOS['3b'], _clock_samples(), PCS, 'f3',
                             fault_start=10.0, fault_end=30.0, end=190.0, log_text='시간표 재생 · tt-s100 · 4회차 준비 · 시작까지 40 s')
    assert verdict.ok, verdict.reasons
    assert '재생 방식 · 시간표 재생' in verdict.notes
    stood = netfault.judge(netfault.SCENARIOS['3b'], _clock_samples(standing=('f3', 40, 120)), PCS, 'f3',
                           fault_start=10.0, fault_end=30.0, end=190.0)
    assert not stood.ok and any('f3' in reason for reason in stood.reasons), '시간표 재생은 끊긴 PC 도 서면 안 됨'


def test_clock_mode_fails_on_a_skipped_cycle():
    log = '[WARN] 시간표 재생 · 5회차 초기 이동 시각을 놓침 · 다음 경계\n[INFO] 시간표 재생 · tt-s100 · 5회차 준비'
    verdict = netfault.judge(netfault.SCENARIOS['2b'], _clock_samples(note=('f2', '5회차 쉼 · 다른 재생 중')), PCS, 'f1',
                             fault_start=10.0, fault_end=160.0, end=190.0, log_text=log)
    assert not verdict.ok
    assert any('놓침' in reason for reason in verdict.reasons)
    assert any('f2' in reason for reason in verdict.reasons)


def test_summarize_reads_the_timetable_mode():
    row = netfault.summarize({'runtime': {'local': {'pc_id': 'f1'}, 'timetable': {
        'mode': 'clock', 'local': {'note': 'x', 'plan_id': 'tt-s1'}}}})
    assert row['sync_mode'] == 'clock' and row['tt_note'] == 'x'
    signal = netfault.summarize({'runtime': {'local': {'pc_id': 'f1'}, 'timetable': {
        'mode': 'clock', 'local': {'note': '마스터 스케줄 꺼짐', 'plan_id': ''}}}})
    assert signal['sync_mode'] == 'lockstep', '시간표 설정이어도 사람이 누른 그룹(신호 재생)은 신호 재생 기준 · 188'
    assert netfault.summarize({'runtime': {}})['sync_mode'] == 'lockstep', '옛 서버 · 칸 없음'
