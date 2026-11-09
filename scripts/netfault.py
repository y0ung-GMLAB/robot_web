#!/usr/bin/env python3
"""자동 끊김 시험 · 로봇 PC 한 대의 Wi-Fi 에만 끊김·지연을 넣고 그룹 재생이 버티는지 판정 · 2026-11-08 (수정 목록 184)

사람이 손으로 하던 끊김 시험(②b · ③b · ④)을 회차 경계 시각에 맞춰 스크립트가 한다 ·
**끊을 PC 에서** sudo 로 돌린다 · 같은 망 PC 들 웹(`/api/coordination`)을 1 s 마다 읽어 기록하고 판정한다.

    sudo python3 scripts/netfault.py scenario 2b           마스터에서 · 회차 끝 30 s 전 150 s 끊기
    sudo python3 scripts/netfault.py scenario 3b           슬레이브에서 · 회차 끝 30 s 전 20 s 끊기
    sudo python3 scripts/netfault.py scenario 4            슬레이브에서 · 120 s 끊고 40 s 뒤 마스터에 즉시 정지
    sudo python3 scripts/netfault.py scenario lag          지연 200±100 ms + 손실 30 % · 5분
    sudo python3 scripts/netfault.py cut --sec 60          손으로 · 60 s 끊기만(판정 없음)
    sudo python3 scripts/netfault.py restore               남은 규칙 모두 지우기(언제든)
    python3 scripts/netfault.py scenario 2b --dry-run      명령만 보기(sudo 불필요 · 아무것도 안 바꿈)

끊는 방식
- 기본 `--mode dds` · 그룹 DDS 포트(도메인 21 → UDP 12650~12899)만 막는다 · 웹(8000) · SSH · AnyDesk 는 그대로 ·
  그룹 연동은 이 포트만 쓰므로 연동 쪽에선 Wi-Fi 가 끊긴 것과 같다 · 끊긴 동안에도 다른 PC 웹을 읽어 판정한다
- `--mode all --yes-cut-remote` · 그 Wi-Fi 의 모든 통신을 막는다 · AnyDesk · SSH 도 끊긴다(자동 원복 뒤 돌아옴) ·
  끊긴 동안 다른 PC 는 못 읽어 「모름」 · ④ 는 마스터에 정지를 못 보내 안 됨
- 지연·손실(`lag`)은 이 PC 가 **보내는** DDS 패킷에만(tc netem) · 양쪽 다 늦추려면 상대 PC 에서도 돌린다

안전장치
- EtherCAT 랜카드(`/usr/local/etc/ethercat.conf` · `/etc/ethercat.conf` 의 MASTER0_DEVICE) · `lo` 는 고를 수 없다 ·
  유선 포트는 `--allow-wired` 일 때만(벤치)
- 넣기 **전에** 원복을 systemd 타이머로 예약(지속 + 30 s 뒤 · `rw-netfault-restore`) · 스크립트가 죽어도 풀린다
- Ctrl+C · 종료 · 오류 때도 원복 · `restore` 는 몇 번을 돌려도 같다

결과 · 마지막 줄 「합격 · …」 / 「불합격 · …」 + `log/netfault/<시각>_<시나리오>.json`(1 s 기록 · 판정 근거)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / 'log' / 'netfault'
LOCAL_URL = 'http://127.0.0.1:8000'

CHAIN = 'RW_NETFAULT'              # filter 표 · 막기
MARK_CHAIN = 'RW_NETFAULT_MARK'    # mangle 표 · 늦출 패킷 표시
MARK = '0x2a'
QDISC_HANDLE = '77:'               # 우리가 넣은 prio · 원복 때 이 번호만 지운다
NETEM_HANDLE = '78:'
RESTORE_UNIT = 'rw-netfault-restore'
RESTORE_GRACE_SEC = 30.0
ETHERCAT_CONFS = ('/usr/local/etc/ethercat.conf', '/etc/ethercat.conf')
DEFAULT_DOMAIN = 21

# 「서 있음」 · 재생도 회차 사이 준비도 아닌 것 · 회차 사이 초기화·대기 단계는 정상
STAND_PHASES = frozenset({'idle', 'stopped', 'stopping', 'completed', 'error'})
STAND_TOL_SEC = 2.0                # 회차가 바뀌는 순간 읽기 어긋남은 봐줌

# 이 PC 연동 노드 로그(journal)에서 찾는 말 · coordination_node.py 의 실제 문구
FAIL_PHRASES = (
    '스스로 잇기 · 시작 예약 실패',
    '스스로 잇기 · 회차 초기화 예약 실패',
    '스스로 잇기 실패',
    '트리거가 이미 지났습니다',
)
# 시간표 재생(clock) · 이 PC 시간표 구동(`clock_driver.py`)의 실제 문구 · 그 PC 가 회차를 쉬었다 · 수정 목록 186
# 「시간표 재생 · 」 로 시작하는 줄 = 쉼 · 놓침 · 늦음 · 예약 실패 · 로컬 실행 끝남 · 아래 정상 문구가 든 줄은 뺀다
CLOCK_OK_PHRASES = (
    '회차 준비',
    '남아 있던 실행 이어받음',
    '운영시간 끝',
    '즉시 정지',
    '회차 후 정지',
    '버전 ',                   # 재생 방식 바뀜 · 설정 버전 알림
)
INFO_PHRASES = (
    '눈금대로 스스로 이어 감',
    '빠졌던 그룹 실행으로 복귀 권유 받음',
    '그룹 복귀 ·',
    '진행 PC 를 따름',
    '연락 끊김',
    '자체 멈춤',
    '정지된 그룹 실행의 지연 명령을 폐기했습니다',
    '시간표 설정 버전',
    '남아 있던 실행 이어받음',
)


class NetfaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    kind: str                      # cut · lag
    fault_sec: float
    before_end_sec: Optional[float]  # 회차 끝 몇 초 전에 시작 · None = 바로
    boundaries_after: int          # 원복 뒤 회차 경계를 몇 번 더 지켜보나
    settle_sec: float              # 마지막 경계(또는 원복) 뒤 더 지켜보는 시간
    stop_now_at: Optional[float] = None  # 끊긴 지 몇 초 뒤 마스터에 즉시 정지
    fail_phrases: Tuple[str, ...] = FAIL_PHRASES


SCENARIOS: Dict[str, Scenario] = {
    '2b': Scenario('2b', '마스터를 회차 경계 넘어 끊기', 'cut', 150.0, 30.0, 1, 60.0),
    '3b': Scenario(
        '3b', '슬레이브가 회차 끝 직후 복귀', 'cut', 20.0, 30.0, 2, 60.0,
        fail_phrases=FAIL_PHRASES + ('정지된 그룹 실행의 지연 명령을 폐기했습니다',),
    ),
    '4': Scenario('4', '끊긴 동안 전체 즉시 정지', 'cut', 120.0, None, 0, 60.0, stop_now_at=40.0),
    'lag': Scenario('lag', '지연 200±100 ms · 손실 30 %', 'lag', 300.0, None, 0, 60.0),
}


# ---------------------------------------------------------------- 랜카드 고르기

def parse_ethercat_devices(texts: Iterable[str]) -> List[str]:
    """ethercat.conf 의 MASTER0_DEVICE 값들(MAC 또는 이름) · 빈 값 · 「none」 표시는 뺀다"""
    found: List[str] = []
    for text in texts:
        for line in (text or '').splitlines():
            match = re.match(r'^\s*MASTER\d+_DEVICE="([^"]+)"', line)
            if match and match.group(1).strip():
                found.append(match.group(1).strip().lower())
    return found


def ethercat_ifaces(devices: Sequence[str], ifaces: Mapping[str, Mapping[str, Any]]) -> set:
    names = set()
    for name, info in ifaces.items():
        mac = str(info.get('mac') or '').lower()
        if name.lower() in devices or (mac and mac in devices):
            names.add(name)
    return names


def pick_iface(
    requested: str,
    ifaces: Mapping[str, Mapping[str, Any]],
    ethercat: set,
    *,
    allow_wired: bool = False,
) -> str:
    """끊을 랜카드 · EtherCAT · lo 는 절대 안 됨 · 유선은 `allow_wired` 일 때만"""
    if requested:
        if requested == 'lo':
            raise NetfaultError('lo 는 끊을 수 없습니다(PC 안쪽 DDS · 웹이 이것을 씀)')
        if requested in ethercat:
            raise NetfaultError(f'{requested} 는 EtherCAT 랜카드입니다 · 모터가 끊기므로 거부')
        if requested not in ifaces:
            raise NetfaultError(f'{requested} 라는 랜카드가 없습니다 · 있는 것 {", ".join(sorted(ifaces))}')
        if not ifaces[requested].get('wireless') and not allow_wired:
            raise NetfaultError(f'{requested} 는 Wi-Fi 가 아닙니다 · 벤치 유선이면 --allow-wired')
        return requested
    candidates = [
        name for name, info in sorted(ifaces.items())
        if name != 'lo' and name not in ethercat and info.get('wireless') and info.get('up')
    ]
    if len(candidates) != 1:
        raise NetfaultError(
            f'켜진 Wi-Fi 랜카드가 {len(candidates)}개입니다({", ".join(candidates) or "없음"}) · --iface 로 고르세요'
        )
    return candidates[0]


def read_ifaces(sys_net: Path = Path('/sys/class/net')) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    if not sys_net.is_dir():
        return result
    for path in sys_net.iterdir():
        def read(name: str) -> str:
            try:
                return (path / name).read_text(encoding='utf-8').strip()
            except OSError:
                return ''
        result[path.name] = {
            'mac': read('address'),
            'wireless': (path / 'wireless').exists() or (path / 'phy80211').exists(),
            'up': read('operstate') == 'up',
        }
    return result


def read_ethercat_devices() -> List[str]:
    texts = []
    for conf in ETHERCAT_CONFS:
        try:
            texts.append(Path(conf).read_text(encoding='utf-8'))
        except OSError:
            continue
    return parse_ethercat_devices(texts)


# ---------------------------------------------------------------- 명령 만들기

def dds_port_range(domain: int) -> Tuple[int, int]:
    """RTPS 기본 포트 규칙 · 7400 + 250 × 도메인 · 그 도메인이 쓰는 250개(발견 · 사용자 · 참가자별 유니캐스트)"""
    if not 0 <= int(domain) <= 232:
        raise NetfaultError(f'DDS 도메인 {domain} 은 범위 밖입니다')
    base = 7400 + 250 * int(domain)
    return base, base + 249


def cut_commands(iface: str, mode: str, ports: Tuple[int, int]) -> List[List[str]]:
    rule = ['-j', 'DROP'] if mode == 'all' else [
        '-p', 'udp', '--dport', f'{ports[0]}:{ports[1]}', '-j', 'DROP',
    ]
    return [
        ['iptables', '-N', CHAIN],
        ['iptables', '-A', CHAIN, *rule],
        ['iptables', '-I', 'INPUT', '1', '-i', iface, '-j', CHAIN],
        ['iptables', '-I', 'OUTPUT', '1', '-o', iface, '-j', CHAIN],
    ]


def lag_commands(
    iface: str, mode: str, ports: Tuple[int, int],
    *, delay_ms: float, jitter_ms: float, loss_pct: float,
) -> List[List[str]]:
    match = [] if mode == 'all' else ['-p', 'udp', '--dport', f'{ports[0]}:{ports[1]}']
    netem = ['delay', f'{delay_ms:g}ms']
    if jitter_ms > 0:
        netem.append(f'{jitter_ms:g}ms')
    if loss_pct > 0:
        netem += ['loss', f'{loss_pct:g}%']
    return [
        ['iptables', '-t', 'mangle', '-N', MARK_CHAIN],
        ['iptables', '-t', 'mangle', '-A', MARK_CHAIN, *match, '-j', 'MARK', '--set-mark', MARK],
        ['iptables', '-t', 'mangle', '-I', 'OUTPUT', '1', '-o', iface, '-j', MARK_CHAIN],
        # 표시 안 된 패킷은 기본 우선순위 표대로 1~3 번 칸 · 표시된 것만 4 번 칸(netem)
        ['tc', 'qdisc', 'add', 'dev', iface, 'root', 'handle', QDISC_HANDLE, 'prio', 'bands', '4'],
        ['tc', 'qdisc', 'add', 'dev', iface, 'parent', f'{QDISC_HANDLE}4', 'handle', NETEM_HANDLE, 'netem', *netem],
        ['tc', 'filter', 'add', 'dev', iface, 'parent', QDISC_HANDLE, 'protocol', 'ip', 'prio', '1',
         'handle', MARK, 'fw', 'flowid', f'{QDISC_HANDLE}4'],
    ]


def restore_commands(iface: str) -> List[List[str]]:
    """지우기 · 없는 규칙이면 실패해도 그만 · 같은 줄이 두 번 들어갔을 수 있어 두 번씩"""
    commands: List[List[str]] = []
    for _ in range(2):
        commands += [
            ['iptables', '-D', 'INPUT', '-i', iface, '-j', CHAIN],
            ['iptables', '-D', 'OUTPUT', '-o', iface, '-j', CHAIN],
            ['iptables', '-t', 'mangle', '-D', 'OUTPUT', '-o', iface, '-j', MARK_CHAIN],
        ]
    commands += [
        ['iptables', '-F', CHAIN],
        ['iptables', '-X', CHAIN],
        ['iptables', '-t', 'mangle', '-F', MARK_CHAIN],
        ['iptables', '-t', 'mangle', '-X', MARK_CHAIN],
        # 우리 prio(77:) 일 때만 · 원래 루트(mq 등)를 지우면 기본으로 돌아가 문제는 없지만 남의 설정은 안 건드림
        ['sh', '-c', f'tc qdisc show dev {iface} | grep -q "qdisc prio {QDISC_HANDLE}" && tc qdisc del dev {iface} root || true'],
    ]
    return commands


def schedule_restore_command(script: str, iface: str, after_sec: float) -> List[str]:
    return [
        'systemd-run', f'--unit={RESTORE_UNIT}', f'--on-active={int(round(after_sec))}s',
        '--timer-property=AccuracySec=1s',
        sys.executable or 'python3', script, 'restore', '--iface', iface, '--from-timer',
    ]


def cancel_restore_commands() -> List[List[str]]:
    return [
        ['systemctl', 'stop', f'{RESTORE_UNIT}.timer'],
        ['systemctl', 'reset-failed', f'{RESTORE_UNIT}.service', f'{RESTORE_UNIT}.timer'],
    ]


# ---------------------------------------------------------------- 실행

class Runner:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.lines: List[str] = []

    def run(self, command: Sequence[str], *, check: bool = True) -> int:
        text = ' '.join(command)
        self.lines.append(text)
        if self.dry_run:
            print(f'  (보기만) {text}')
            return 0
        result = subprocess.run(list(command), capture_output=True, text=True)
        if result.returncode != 0 and check:
            raise NetfaultError(f'명령 실패 · {text} · {result.stderr.strip() or result.stdout.strip()}')
        return result.returncode


class Fault:
    """넣기 → 원복 예약 · 나갈 때 꼭 원복 · `with` 로 쓴다"""

    def __init__(self, runner: Runner, iface: str, script: str) -> None:
        self.runner = runner
        self.iface = iface
        self.script = script
        self.active = False

    def inject(self, commands: List[List[str]], fault_sec: float) -> None:
        for command in cancel_restore_commands():
            self.runner.run(command, check=False)
        restore(self.runner, self.iface)          # 지난 시험 찌꺼기
        self.runner.run(schedule_restore_command(self.script, self.iface, fault_sec + RESTORE_GRACE_SEC))
        self.active = True
        for command in commands:
            self.runner.run(command)

    def lift(self) -> None:
        if not self.active:
            return
        restore(self.runner, self.iface)
        for command in cancel_restore_commands():
            self.runner.run(command, check=False)
        self.active = False

    def __enter__(self) -> 'Fault':
        self._old_handlers = {}
        for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
            sig = getattr(signal, name, None)
            if sig is not None:
                self._old_handlers[sig] = signal.signal(sig, self._on_signal)
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.lift()
        finally:
            for sig, handler in getattr(self, '_old_handlers', {}).items():
                signal.signal(sig, handler)

    def _on_signal(self, signum: int, _frame: Any) -> None:
        self.lift()
        raise SystemExit(f'신호 {signum} · 원복하고 끝냄')


def restore(runner: Runner, iface: str) -> None:
    for command in restore_commands(iface):
        runner.run(command, check=False)


# ---------------------------------------------------------------- 웹 읽기

def http_json(url: str, payload: Optional[Mapping[str, Any]] = None, timeout: float = 2.0) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def base_url(url: str) -> str:
    match = re.match(r'^(https?://[^/]+)', str(url or '').strip())
    return match.group(1) if match else ''


def summarize(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """`/api/coordination` 한 장에서 판정에 쓰는 칸만"""
    runtime = snapshot.get('runtime') if isinstance(snapshot.get('runtime'), Mapping) else {}
    local = runtime.get('local') if isinstance(runtime.get('local'), Mapping) else {}
    execution = runtime.get('execution') if isinstance(runtime.get('execution'), Mapping) else {}
    failure = runtime.get('last_start_failure') if isinstance(runtime.get('last_start_failure'), Mapping) else {}
    timetable = runtime.get('timetable') if isinstance(runtime.get('timetable'), Mapping) else {}
    local_tt = timetable.get('local') if isinstance(timetable.get('local'), Mapping) else {}
    config = runtime.get('config') if isinstance(runtime.get('config'), Mapping) else {}
    return {
        'pc_id': str(local.get('pc_id') or config.get('pc_id') or ''),
        'phase': str(local.get('motion_phase') or ''),
        'state': str(execution.get('state') or ''),
        'execution_id': str(execution.get('execution_id') or ''),
        'coordinator_id': str(execution.get('coordinator_id') or ''),
        'participants': list(execution.get('participants') or []),
        'cycle': int(local.get('current_cycle') or execution.get('cycle_number') or 0),
        'elapsed': float(local.get('motion_elapsed_sec') or 0.0),
        'duration': float(local.get('motion_duration_sec') or 0.0),
        'lost': dict(execution.get('lost') or {}),
        'joining': dict(execution.get('joining') or {}),
        'start_failure_at': float(failure.get('at') or 0.0),
        'start_failure': str(failure.get('message') or ''),
        'domain': int(config.get('dds_domain_id') or 0),
        # 재생 방식 · 시간표 재생이면 판정이 다르다(끊긴 PC 도 계속 재생) · 옛 서버는 칸 없음 = 신호 재생 · 186
        'sync_mode': 'clock' if timetable.get('mode') == 'clock' else 'lockstep',
        'tt_note': str(local_tt.get('note') or ''),
    }


def discover_pcs(local_snapshot: Mapping[str, Any]) -> Dict[str, str]:
    """이 PC + 하트비트로 보이는 로봇 PC 들의 웹 주소 · pc_id → URL"""
    runtime = local_snapshot.get('runtime') if isinstance(local_snapshot.get('runtime'), Mapping) else {}
    local = runtime.get('local') if isinstance(runtime.get('local'), Mapping) else {}
    pcs = {str(local.get('pc_id') or 'local'): LOCAL_URL}
    for peer in runtime.get('peers') or []:
        if not isinstance(peer, Mapping):
            continue
        pc_id = str(peer.get('pc_id') or '')
        url = base_url(peer.get('web_url'))
        if pc_id and url and pc_id not in pcs:
            pcs[pc_id] = url
    return pcs


def remaining_sec(row: Mapping[str, Any]) -> Optional[float]:
    if row.get('phase') != 'running' or float(row.get('duration') or 0.0) <= 0.0:
        return None
    return max(float(row['duration']) - float(row.get('elapsed') or 0.0), 0.0)


# ---------------------------------------------------------------- 판정 (순수 함수 · 시험 대상)

def is_standing(row: Optional[Mapping[str, Any]]) -> Optional[bool]:
    """None = 못 읽음(모름)"""
    if row is None:
        return None
    return row.get('phase') in STAND_PHASES or not row.get('execution_id')


def stand_spans(samples: Sequence[Mapping[str, Any]], pc_id: str, t0: float, t1: float) -> List[Tuple[float, float]]:
    """[t0, t1] 안에서 그 PC 가 서 있던 구간들 · 못 읽은 표본은 앞 상태를 이어 본다"""
    spans: List[Tuple[float, float]] = []
    start: Optional[float] = None
    last_t = t0
    for sample in samples:
        t = float(sample['t'])
        if t < t0 or t > t1:
            continue
        standing = is_standing((sample.get('pcs') or {}).get(pc_id))
        if standing is None:
            last_t = t
            continue
        if standing and start is None:
            start = t
        elif not standing and start is not None:
            spans.append((start, t))
            start = None
        last_t = t
    if start is not None:
        spans.append((start, last_t))
    return spans


def longest_stand(samples: Sequence[Mapping[str, Any]], pc_id: str, t0: float, t1: float) -> float:
    return max((end - begin for begin, end in stand_spans(samples, pc_id, t0, t1)), default=0.0)


def first_stand_at(samples: Sequence[Mapping[str, Any]], pc_id: str, after: float) -> Optional[float]:
    for sample in samples:
        if float(sample['t']) >= after and is_standing((sample.get('pcs') or {}).get(pc_id)):
            return float(sample['t'])
    return None


def last_row(samples: Sequence[Mapping[str, Any]], pc_id: str) -> Optional[Mapping[str, Any]]:
    for sample in reversed(samples):
        row = (sample.get('pcs') or {}).get(pc_id)
        if row is not None:
            return row
    return None


def new_start_failures(samples: Sequence[Mapping[str, Any]], t0: float) -> Dict[str, str]:
    """시험 중에 새로 생긴 「시작 실패」 · PC → 메시지"""
    found: Dict[str, str] = {}
    for sample in samples:
        for pc_id, row in (sample.get('pcs') or {}).items():
            if row and float(row.get('start_failure_at') or 0.0) >= t0 and row.get('start_failure'):
                found[pc_id] = str(row['start_failure'])
    return found


@dataclass
class Verdict:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def line(self, key: str) -> str:
        head = '합격' if self.ok else '불합격'
        body = ' · '.join(self.reasons if not self.ok else self.notes) or '이상 없음'
        return f'{head} · {key} · {body}'


def _common_checks(
    verdict: Verdict, samples: Sequence[Mapping[str, Any]], pcs: Sequence[str],
    t0: float, t1: float, *, keep_playing: Sequence[str], log_text: str, fail_phrases: Sequence[str],
) -> None:
    for pc_id in keep_playing:
        worst = longest_stand(samples, pc_id, t0, t1)
        if worst > STAND_TOL_SEC:
            verdict.ok = False
            verdict.reasons.append(f'{pc_id} {worst:.0f} s 서 있음')
    for pc_id, message in new_start_failures(samples, t0).items():
        verdict.ok = False
        verdict.reasons.append(f'{pc_id} 시작 실패 「{message}」')
    for phrase in fail_phrases:
        count = log_text.count(phrase)
        if count:
            verdict.ok = False
            verdict.reasons.append(f'이 PC 로그 「{phrase}」 {count}번')
    for phrase in INFO_PHRASES:
        count = log_text.count(phrase)
        if count:
            verdict.notes.append(f'로그 「{phrase.strip(" ·")}」 {count}번')


def clock_failures(log_text: str) -> Dict[str, int]:
    """시간표 재생 로그에서 「쉼」 쪽 줄만 · 정상 문구(준비 · 이어받음 · 운영 끝 · 정지)는 뺀다"""
    found: Dict[str, int] = {}
    for line in log_text.splitlines():
        if '시간표 재생 · ' not in line or any(ok in line for ok in CLOCK_OK_PHRASES):
            continue
        text = line.split('시간표 재생 · ', 1)[1].strip()[:60]
        found[text] = found.get(text, 0) + 1
    return found


def held_notes(samples: Sequence[Mapping[str, Any]], pcs: Sequence[str], t0: float) -> Dict[str, str]:
    """시간표 재생 · 시험 중 PC 가 화면에 낸 쉬는 이유(`tt_note`) · PC → 마지막 이유"""
    found: Dict[str, str] = {}
    for sample in samples:
        if float(sample['t']) < t0:
            continue
        for pc_id, row in (sample.get('pcs') or {}).items():
            note = str((row or {}).get('tt_note') or '')
            if pc_id in pcs and note and note not in {'정지됨', '시간표 끝'}:
                found[pc_id] = note
    return found


def detect_mode(samples: Sequence[Mapping[str, Any]]) -> str:
    """재생 방식 · 표본에 시간표 재생 PC 가 하나라도 있으면 clock"""
    for sample in samples:
        for row in (sample.get('pcs') or {}).values():
            if (row or {}).get('sync_mode') == 'clock':
                return 'clock'
    return 'lockstep'


def _same_execution_at_end(verdict: Verdict, samples: Sequence[Mapping[str, Any]], pcs: Sequence[str]) -> None:
    ids = {}
    for pc_id in pcs:
        row = last_row(samples, pc_id)
        ids[pc_id] = (row or {}).get('execution_id') or ''
    if len(set(ids.values())) != 1 or not next(iter(ids.values()), ''):
        verdict.ok = False
        verdict.reasons.append('끝에 실행이 갈림 · ' + ' · '.join(f'{k}={v or "없음"}' for k, v in ids.items()))
    else:
        verdict.notes.append(f'끝에 {len(ids)}대 같은 실행')


def judge(
    scenario: Scenario, samples: Sequence[Mapping[str, Any]], pcs: Sequence[str], me: str,
    *, fault_start: float, fault_end: float, end: float, stop_sent_at: Optional[float] = None,
    log_text: str = '', stop_within_sec: float = 5.0, stop_after_restore_sec: float = 20.0,
) -> Verdict:
    verdict = Verdict(ok=True)
    others = [pc for pc in pcs if pc != me]
    mode = detect_mode(samples)
    verdict.notes.append('재생 방식 · ' + ('시간표 재생' if mode == 'clock' else '신호 재생'))
    if mode == 'clock' and scenario.key != '4':
        # 시간표 재생 · 끊긴 PC 를 포함해 모두 계속 재생 · 회차를 쉰 PC 가 없어야 · 끝에 같은 시간표
        _common_checks(verdict, samples, pcs, fault_start, end, keep_playing=pcs, log_text=log_text,
                       fail_phrases=())
        for text, count in clock_failures(log_text).items():
            verdict.ok = False
            verdict.reasons.append(f'이 PC 로그 「{text}」 {count}번')
        for pc_id, note in held_notes(samples, pcs, fault_start).items():
            verdict.ok = False
            verdict.reasons.append(f'{pc_id} 「{note}」')
        _same_execution_at_end(verdict, samples, pcs)
        return verdict
    if scenario.key == '4':
        if stop_sent_at is None:
            return Verdict(False, ['마스터에 즉시 정지를 못 보냄'])
        for pc_id in others:
            at = first_stand_at(samples, pc_id, stop_sent_at)
            if at is None or at - stop_sent_at > stop_within_sec:
                verdict.ok = False
                verdict.reasons.append(f'{pc_id} 정지 뒤 {stop_within_sec:g} s 안에 안 섬')
        at = first_stand_at(samples, me, fault_end)
        if is_standing(_row_at(samples, me, fault_end)):
            verdict.notes.append(f'{me} 원복 때 이미 서 있음')
        elif at is None or at - fault_end > stop_after_restore_sec:
            verdict.ok = False
            verdict.reasons.append(f'{me}(끊긴 PC) 다시 붙은 뒤 {stop_after_restore_sec:g} s 안에 안 섬')
        else:
            verdict.notes.append(f'{me} 다시 붙고 {at - fault_end:.1f} s 뒤 섬')
        _common_checks(verdict, samples, pcs, fault_start, end, keep_playing=(), log_text=log_text,
                       fail_phrases=() if mode == 'clock' else scenario.fail_phrases)
        return verdict
    keep = pcs if scenario.key in ('2b', 'lag') else others
    _common_checks(verdict, samples, pcs, fault_start, end, keep_playing=keep, log_text=log_text,
                   fail_phrases=scenario.fail_phrases)
    if scenario.key == '3b':
        worst = longest_stand(samples, me, fault_start, end)
        verdict.notes.append(f'{me}(끊긴 PC) 가장 길게 선 시간 {worst:.0f} s')
    _same_execution_at_end(verdict, samples, pcs)
    return verdict


def _row_at(samples: Sequence[Mapping[str, Any]], pc_id: str, t: float) -> Optional[Mapping[str, Any]]:
    best = None
    for sample in samples:
        if float(sample['t']) > t:
            break
        row = (sample.get('pcs') or {}).get(pc_id)
        if row is not None:
            best = row
    return best


# ---------------------------------------------------------------- 시나리오 진행

class Recorder:
    def __init__(self, pcs: Mapping[str, str]) -> None:
        self.pcs = dict(pcs)
        self.samples: List[Dict[str, Any]] = []

    def poll(self) -> Dict[str, Any]:
        # 동시에 읽는다 · 끊긴 PC 하나가 1.5 s 를 다 써도 1 s 간격이 덜 밀리게
        def read(url: str) -> Optional[Dict[str, Any]]:
            try:
                return summarize(http_json(f'{url}/api/coordination', timeout=1.5))
            except (OSError, ValueError, urllib.error.URLError):
                return None
        with ThreadPoolExecutor(max_workers=max(len(self.pcs), 1)) as pool:
            results = dict(zip(self.pcs, pool.map(read, self.pcs.values())))
        rows: Dict[str, Optional[Dict[str, Any]]] = results
        sample = {'t': time.time(), 'pcs': rows}
        self.samples.append(sample)
        return sample

    def watch_until(self, deadline: float, period: float = 1.0) -> None:
        while time.time() < deadline:
            started = time.time()
            self.poll()
            time.sleep(max(period - (time.time() - started), 0.05))

    def max_cycle(self) -> int:
        cycles = [row['cycle'] for row in (self.samples[-1]['pcs'] if self.samples else {}).values() if row]
        return max(cycles, default=0)


def wait_for_boundary(recorder: Recorder, me: str, before_sec: float, limit_sec: float) -> None:
    """이 PC 가 재생 중이고 회차 끝까지 `before_sec` 남은 때까지 · 너무 늦었으면 다음 회차"""
    deadline = time.time() + limit_sec
    while time.time() < deadline:
        row = recorder.poll()['pcs'].get(me)
        left = remaining_sec(row or {})
        if left is not None and left >= before_sec + 3.0:
            wait = left - before_sec
            print(f'회차 끝까지 {left:.0f} s · {wait:.0f} s 뒤 시작')
            recorder.watch_until(time.time() + wait - 1.0)
            while True:   # 마지막 1 s 는 촘촘히
                left = remaining_sec(recorder.poll()['pcs'].get(me) or {})
                if left is None or left <= before_sec:
                    return
                time.sleep(0.2)
        time.sleep(1.0)
    raise NetfaultError(f'{limit_sec:.0f} s 기다렸지만 회차 끝 {before_sec:g} s 전을 못 잡음(재생 중이 아님?)')


def journal_text(since: float) -> str:
    try:
        result = subprocess.run(
            ['journalctl', '_SYSTEMD_USER_UNIT=motion-coordination.service', '--since', f'@{int(since)}',
             '-o', 'cat', '--no-pager'],
            capture_output=True, text=True, timeout=20,
        )
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def precheck(recorder: Recorder, me: str) -> List[str]:
    sample = recorder.poll()
    problems = []
    rows = sample['pcs']
    for pc_id, row in list(rows.items()):
        if row is None:
            # 스피커처럼 로봇 웹이 아닌 PC · 꺼진 로봇 PC 도 여기 · 지켜볼 목록에서 뺀다
            print(f'참고 · {pc_id} 웹({recorder.pcs[pc_id]}) 을 못 읽어 지켜볼 목록에서 뺌')
            del recorder.pcs[pc_id]
            del rows[pc_id]
        elif is_standing(row):
            problems.append(f'{pc_id} 그룹 재생 중이 아님({row.get("phase") or "?"})')
    ids = {row['execution_id'] for row in rows.values() if row}
    if len(ids) > 1:
        problems.append('PC 들이 다른 실행을 쥐고 있음')
    if me not in rows:
        problems.append('이 PC 를 못 읽음')
    return problems


def save_result(name: str, payload: Mapping[str, Any]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f'{time.strftime("%Y%m%d_%H%M%S")}_{name}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if uid and gid:   # sudo 로 돌려도 파일 주인은 사람 계정
        for target in (LOG_DIR.parent, LOG_DIR, path):
            try:
                os.chown(target, int(uid), int(gid))
            except OSError:
                pass
    return path


def run_scenario(args: argparse.Namespace) -> int:
    scenario = SCENARIOS[args.name]
    fault_sec = float(args.sec or scenario.fault_sec)
    before = scenario.before_end_sec if args.before is None else float(args.before)
    runner = Runner(args.dry_run)
    try:
        local_snapshot = http_json(f'{LOCAL_URL}/api/coordination')
    except (OSError, ValueError) as exc:
        if not args.dry_run:
            raise NetfaultError(f'이 PC 웹({LOCAL_URL}) 을 못 읽음 · {exc}') from exc
        local_snapshot = {}
    me = summarize(local_snapshot)['pc_id'] or 'local'
    domain = int(args.domain or summarize(local_snapshot)['domain'] or DEFAULT_DOMAIN)
    ports = dds_port_range(domain)
    iface = pick_iface(args.iface, read_ifaces(), ethercat_ifaces(read_ethercat_devices(), read_ifaces()),
                       allow_wired=args.allow_wired)
    pcs = discover_pcs(local_snapshot)
    if args.pcs:
        pcs = {me: LOCAL_URL}
        for url in args.pcs:
            try:
                pcs[summarize(http_json(f'{base_url(url) or url}/api/coordination'))['pc_id'] or url] = base_url(url) or url
            except (OSError, ValueError) as exc:
                raise NetfaultError(f'{url} 웹을 못 읽음 · {exc}') from exc
    mode = args.mode
    if scenario.key == '4' and mode == 'all':
        raise NetfaultError('④ 는 끊긴 동안 마스터 웹에 정지를 보내야 해서 --mode dds 만 됩니다')
    if scenario.kind == 'lag':
        commands = lag_commands(iface, mode, ports, delay_ms=args.delay, jitter_ms=args.jitter, loss_pct=args.loss)
    else:
        commands = cut_commands(iface, mode, ports)
    print(f'{scenario.key} · {scenario.title} · 이 PC {me} · 랜카드 {iface} · 방식 {mode} · 포트 {ports[0]}~{ports[1]} · '
          f'{fault_sec:g} s · 지켜볼 PC {", ".join(pcs)}')
    if args.dry_run:
        Fault(runner, iface, str(Path(__file__).resolve())).inject(commands, fault_sec)
        print('보기만 · 원복 명령')
        restore(runner, iface)
        return 0
    recorder = Recorder(pcs)
    problems = precheck(recorder, me)
    if problems and not args.force:
        raise NetfaultError('시작 전 확인 실패 · ' + ' · '.join(problems) + ' · 그래도 하려면 --force')
    master = summarize(local_snapshot)['coordinator_id']
    if before is not None:
        wait_for_boundary(recorder, me, before, args.max_wait)
    stop_sent_at: Optional[float] = None
    with Fault(runner, iface, str(Path(__file__).resolve())) as fault:
        fault_start = time.time()
        fault.inject(commands, fault_sec)
        print(f'{time.strftime("%H:%M:%S")} 넣음 · {fault_sec:g} s')
        if scenario.stop_now_at is not None:
            recorder.watch_until(fault_start + scenario.stop_now_at)
            url = pcs.get(master)
            if not url or master == me:
                raise NetfaultError('마스터 웹 주소를 모름(또는 이 PC 가 마스터) · ④ 는 슬레이브에서 돌리세요')
            http_json(f'{url}/api/coordination/control', {'command': 'stop_now'}, timeout=5.0)
            stop_sent_at = time.time()
            print(f'{time.strftime("%H:%M:%S")} 마스터 {master} 에 즉시 정지 보냄')
        recorder.watch_until(fault_start + fault_sec)
        fault.lift()
        fault_end = time.time()
        print(f'{time.strftime("%H:%M:%S")} 원복')
    end_limit = fault_end + args.max_watch
    cycle_at_end = recorder.max_cycle()
    for _ in range(scenario.boundaries_after):
        target = cycle_at_end + 1
        while time.time() < end_limit and recorder.max_cycle() < target:
            recorder.watch_until(time.time() + 1.0)
        cycle_at_end = target
    recorder.watch_until(min(time.time() + scenario.settle_sec, end_limit))
    end = time.time()
    log_text = journal_text(fault_start - 5.0)
    verdict = judge(
        scenario, recorder.samples, list(pcs), me, fault_start=fault_start, fault_end=fault_end,
        end=end, stop_sent_at=stop_sent_at, log_text=log_text,
    )
    line = verdict.line(scenario.key)
    path = save_result(scenario.key, {
        'scenario': scenario.key, 'title': scenario.title, 'me': me, 'iface': iface, 'mode': mode,
        'ports': ports, 'fault_start': fault_start, 'fault_end': fault_end, 'end': end,
        'stop_sent_at': stop_sent_at, 'ok': verdict.ok, 'reasons': verdict.reasons, 'notes': verdict.notes,
        'commands': runner.lines, 'samples': recorder.samples,
    })
    print(line)
    print(f'기록 · {path}')
    return 0 if verdict.ok else 1


def run_manual(args: argparse.Namespace) -> int:
    runner = Runner(args.dry_run)
    ifaces = read_ifaces()
    if args.command == 'restore':
        # 지우기는 고르기 검사 없이 · 랜카드를 안 주면 lo 빼고 전부(없는 규칙 지우기는 실패해도 그만)
        targets = [args.iface] if args.iface else [name for name in sorted(ifaces) if name != 'lo']
        for name in targets:
            restore(runner, name)
        if not args.from_timer:
            for command in cancel_restore_commands():
                runner.run(command, check=False)
        print(f'원복 · {", ".join(targets) or "랜카드 없음"}')
        return 0
    iface = pick_iface(args.iface, ifaces, ethercat_ifaces(read_ethercat_devices(), ifaces),
                       allow_wired=args.allow_wired)
    ports = dds_port_range(int(args.domain or DEFAULT_DOMAIN))
    if args.command == 'lag':
        commands = lag_commands(iface, args.mode, ports, delay_ms=args.delay, jitter_ms=args.jitter, loss_pct=args.loss)
    else:
        commands = cut_commands(iface, args.mode, ports)
    with Fault(runner, iface, str(Path(__file__).resolve())) as fault:
        fault.inject(commands, args.sec)
        print(f'{time.strftime("%H:%M:%S")} {args.command} · {iface} · {args.sec:g} s')
        if not args.dry_run:
            time.sleep(args.sec)
    print(f'{time.strftime("%H:%M:%S")} 원복')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='자동 끊김 시험 · Wi-Fi 에만 · EtherCAT 은 안 건드림')
    sub = parser.add_subparsers(dest='command', required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument('--iface', default='', help='끊을 랜카드 · 없으면 켜진 Wi-Fi 하나')
        p.add_argument('--allow-wired', action='store_true', help='벤치 유선 포트 허용(EtherCAT 은 그래도 거부)')
        p.add_argument('--dry-run', action='store_true', help='명령만 보이고 아무것도 안 바꿈')
        p.add_argument('--domain', type=int, default=0, help=f'그룹 DDS 도메인 · 없으면 웹에서(보통 {DEFAULT_DOMAIN})')

    def fault_opts(p: argparse.ArgumentParser, *, sec: Optional[float]) -> None:
        p.add_argument('--sec', type=float, default=sec, help='지속 초')
        p.add_argument('--mode', choices=('dds', 'all'), default='dds')
        p.add_argument('--yes-cut-remote', action='store_true', help='--mode all 확인(AnyDesk · SSH 도 끊김)')
        p.add_argument('--delay', type=float, default=200.0, help='lag · 지연 ms')
        p.add_argument('--jitter', type=float, default=100.0, help='lag · 흔들림 ms')
        p.add_argument('--loss', type=float, default=30.0, help='lag · 손실 %%')

    scenario = sub.add_parser('scenario', help='시나리오 · 기다림 → 넣기 → 지켜보기 → 판정')
    scenario.add_argument('name', choices=sorted(SCENARIOS))
    common(scenario)
    fault_opts(scenario, sec=None)
    scenario.add_argument('--before', type=float, default=None, help='회차 끝 몇 초 전에 시작(2b · 3b)')
    scenario.add_argument('--pcs', nargs='*', default=None, help='지켜볼 PC 웹 주소 · 없으면 하트비트로 찾음')
    scenario.add_argument('--force', action='store_true', help='시작 전 확인이 실패해도 진행')
    scenario.add_argument('--max-wait', type=float, default=1500.0, help='회차 끝을 기다리는 최대 초')
    scenario.add_argument('--max-watch', type=float, default=2400.0, help='원복 뒤 지켜보는 최대 초')
    for name in ('cut', 'lag'):
        p = sub.add_parser(name, help='손으로 · 넣고 그 시간 뒤 원복(판정 없음)')
        common(p)
        fault_opts(p, sec=60.0)
    restore_parser = sub.add_parser('restore', help='남은 규칙 지우기')
    common(restore_parser)
    restore_parser.add_argument('--from-timer', action='store_true', help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, 'mode', 'dds') == 'all' and not args.yes_cut_remote and args.command != 'restore':
            raise NetfaultError('--mode all 은 AnyDesk · SSH 도 끊습니다 · 알고 하려면 --yes-cut-remote')
        if not args.dry_run and getattr(os, 'geteuid', lambda: 0)() != 0:
            raise NetfaultError('sudo 로 돌리세요(iptables · tc) · 명령만 보려면 --dry-run')
        if args.command == 'scenario':
            return run_scenario(args)
        return run_manual(args)
    except NetfaultError as exc:
        print(f'중단 · {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
