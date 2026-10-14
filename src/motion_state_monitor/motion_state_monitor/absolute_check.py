"""MINAS 앱솔루트 값 늘 알기 · 수정 목록 62 ①

연결된 MINAS 드라이브 **전부**의 Pr0.15(0x3015) · 오류(0x603F)를 SDO 로 읽어
motion_state 의 `minas_absolute` 로 싣는다 · 판정은 `motion_common.minas_absolute`.

언제 읽나
    버스에 보이는 슬레이브 구성(마스터 · 링 위치)이 바뀔 때마다 · 프로그램 기동 직후 포함 ·
    드라이브 전원을 껐다 켜면 슬레이브가 빠졌다 돌아오므로 그때 다시 읽는다 ·
    읽는 동안은 「확인 중」 → 막는다 · 다 읽으면 그 결과로 바꾼다.

왜 구성 변화에만 읽나
    Pr0.15 는 속성 C · 써도 전원 재투입 전에는 동작이 안 바뀌는데 되읽으면 새 값이 나온다
    (실물 2026-10-07 시험 51) · 그래서 재투입 전에 다시 읽으면 아직 인크리멘털인 드라이브를
    앱솔루트로 볼 수 있다 · 그래도 위치를 잃는 일은 없다 · 전원이 켜져 있는 동안은 두 방식의
    위치가 같고, 위치를 잃는 순간(전원 차단)은 구성 변화로 보여 재투입 뒤 실제 값으로 다시
    읽는다 · EEPROM 에 0 이 저장됐으면 그때 Err40 으로, 안 됐으면 Pr0.15 ≠ 0 으로 막힌다 ·
    모터 검색(`ethercat rescan`)으로 잠깐 슬레이브가 빠져 보여도 같은 이유로 문제없다.

보이지 않는 드라이브는 판정하지 않는다 · 버스가 끊긴 축은 다른 검사(`bus_down` ·
모터 상태 없음)가 막는다 · 다시 보이면 읽기 전까지 「확인 중」 으로 막는다.

`ethercat` 명령은 폴링 타이머를 막지 않게 따로 스레드에서 돈다.

게인 값도 같이 읽는다 · 수정 목록 108 (가) (2026-10-13)
    자동조정(Pr0.02) · 강성(Pr0.03) · 관성비(Pr0.04) · 추정 속도(Pr6.31) · 우리 부팅 목록에 없어 드라이브
    EEPROM 값이 그대로 쓰인다 · 벤치에서 꺼 둔 자동조정이 남아 축2 가 떨었다(108 경과) · 화면에 보이게 ·
    읽기 실패는 앱솔루트 판정과 상관없다(막지 않는다) · 관성비는 자동조정이 계속 바꾸므로 `GAIN_REFRESH_SEC`
    마다 게인만 다시 읽는다(Pr0.15 는 다시 안 읽는다 · 속성 C) · 다시 읽기도 버스가 자리 잡은 때만.

버스가 자리 잡은 뒤에 읽는다 · 수정 목록 110 (2026-10-12 floating4 재부팅)
    부팅 때 Motor Manager 가 드라이브를 PREOP → OP 로 올리는 동안 마스터가 같은 메일박스로
    설정 SDO 를 보낸다 · 그 사이 `ethercat upload` 가 끼면 「wrong SDO」 · 「No response」 로
    실패하고, 구성이 그대로라 다시 안 읽어 「확인 불가」 로 굳어 모든 동작이 막혔다 ·
    그래서 ① 슬레이브 상태(PREOP · SAFEOP · OP)가 `SETTLE_SEC` 동안 그대로일 때만 읽고 ·
    ② 「확인 불가」 가 남은 드라이브는 몇 초마다 다시 읽는다 (Pr0.15 ≠ 0 · Err40 은 다시 읽어도
    값이 같으니 그대로 막는다 · 읽기 실패만 다시).

마스터가 버스를 설정하는 동안엔 아예 안 읽는다 · 수정 목록 125 (실물 U-1 · 2026-10-13)
    상태가 그대로인지만 봐서는 부족했다 · PC 부팅 때 슬레이브는 마스터가 혼자 PREOP 로 올려 둔 채
    한참 그대로이고, 그 사이 모터 프로그램이 떠서 부팅 설정 SDO 를 쓰기 시작하면 우리 읽기와 엉켜
    「SDO configuration failed」 → PREOP + E 로 굳었다(PC 만 재부팅 2/2) · 그래서
    ① 모터 실행 스크립트가 세우는 「버스 설정 중」 표시(`motion_common.ethercat_mailbox`)가 있으면 안 읽고 ·
    ② 모터 프로그램이 마스터를 잡고 있는데(`ethercat master` Phase Operation · Active) OP 가 아닌 슬레이브가
       있으면 그 상태로 `STUCK_SEC` 그대로일 때만 읽는다(설정 실패 · 설정 안 된 슬레이브 · 그땐 마스터가 안 건드림) ·
       모터 프로그램이 없으면(검색 뒤 등) PREOP 그대로 `SETTLE_SEC` 이면 읽는다 · 모두 OP 여도 `SETTLE_SEC` ·
    ③ 읽는 중에 표시가 서면 남은 SDO 는 `ethercat_mailbox` 가 보내지 않는다 → 이번 읽기는 없던 것으로
       하고(「확인 중」 그대로) 자리 잡은 뒤 다시 · 게인 다시 읽기도 같은 규칙.
    SDO 는 모두 `ethercat_mailbox.run` 으로 · 웹 브리지와 한 번에 하나.

마스터가 스스로 SDO 사전을 읽는 동안도 피한다 · 수정 목록 134 (실물 S-4 · 2026-10-14)
    재투입으로 돌아온 드라이브는 OP 뒤 몇 초 동안 마스터가 SDO 사전 목록을 읽는다(우리 잠금 밖 · 표시도 없음) ·
    그 사이 게인 0x3002 읽기가 「SDO upload aborted」 · 「MBXERR_UNSUPPORTEDPROTOCOL」 과 겹쳤다 ·
    상태가 그대로여야 하는 시간 `SETTLE_SEC` 을 10 s 로 늘려 그 시간을 넘긴다(실패해도 2 s 뒤 다시 읽는 것은 그대로).

멈춘 메일박스를 알린다 · 수정 목록 139 ③ (실물 S 3회차 · 2026-10-14 · 안전망)
    SDO 충돌 뒤 드라이브 메일박스가 영구히 멈췄다 · OP · PDO 정상 · SDO 는 전부 「upload request … timeout」
    (SM0 쓰기 WKC 0 · 커널 로그) · 제어 전원 재투입으로만 풀린다 · 원인(IgH SDO 사전 자동 읽기)은 커널 패치로 없애지만
    다른 이유로 멈춰도 사람이 알아야 한다 · 그래서
    ① OP 인 슬레이브 하나가 응답 없음(CLI 는 EIO 「Input/output error」 · 우리 제한 시간 초과)을 `MAILBOX_STUCK_COUNT` 번 연속 ·
       첫 번째부터 `MAILBOX_STUCK_SPAN_SEC` 이상 · 그 사이 **다른 슬레이브는 답했으면** 그 드라이브 메일박스 멈춤 ·
       모두 답이 없으면 버스 문제다(다른 검사가 본다) · 이 경고 아님 · SDO abort 는 드라이브가 답한 것으로 본다
    ② 멈춘 동안 그 드라이브엔 SDO 를 보내지 않는다(계속 쏘지 않기) · `MAILBOX_PROBE_SEC` 마다 한 번만 떠본다 · PDO · 재생은 그대로
    ③ 풀림 · 떠본 읽기가 답을 받거나 · 그 슬레이브가 OP 를 벗어나거나(재스캔 · 재설정) · 슬레이브 구성이 바뀌면
    ④ motion_state 의 `minas_absolute.stuck_mailboxes` 로 싣는다 · 막지 않는다 · 화면 「확인할 일」 · 모터 기록은 받는 쪽
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from motion_common import ethercat_mailbox, minas_absolute

from .motor_values import parse_int

#: SDO 하나 읽기 제한 시간
UPLOAD_TIMEOUT_SEC = 2.0
#: `ethercat slaves -v` 제한 시간
SLAVES_TIMEOUT_SEC = 3.0

#: 슬레이브 상태가 이만큼 그대로여야 읽는다 · 부팅 때 PREOP → OP 전환 중엔 안 읽는다 ·
#: 2 → 5 s · 실물 U-1b(10-13) 드라이브 재투입 직후 OP 여도 메일박스 응답이 늦어 「wrong SDO」 13 건 ·
#: 5 → 10 s · 수정 목록 134 · 재투입·검색으로 다시 잡힌 슬레이브는 IgH 마스터가 스스로 SDO 사전을 읽는다(우리 잠금 밖) ·
#: 실물 V-18 OP 뒤 6~8 s(설정 끝 표시 뒤 4~6 s)까지 0x3015 ↔ 0x603F 충돌 · 대가는 부팅·재투입 뒤 「확인 중」(동작 막음)이 5 s 길어지는 것뿐
SETTLE_SEC = 10.0
#: 모터 프로그램이 마스터를 잡고 있는데 OP 가 아닌 슬레이브가 있을 때 · 이만큼 그대로여야 읽는다 · 125 ·
#: 설정 중이면 PREOP → SAFEOP → OP 로 몇 초 안에 바뀐다 · 이만큼 그대로면 설정 실패(E)나 설정 안 된 슬레이브
STUCK_SEC = 30.0
#: 「확인 불가」 다시 읽기 간격 · 처음 1 분은 짧게, 그 뒤엔 드물게
RETRY_FAST_SEC = 2.0
RETRY_FAST_WINDOW_SEC = 60.0
RETRY_SLOW_SEC = 10.0

#: 게인 · 이름 → (객체, 형식) · MINAS Pr X.YY = 0x3XYY · 10-07 · 10-12 실물에서 int16 으로 읽고 씀
GAIN_OBJECTS: Tuple[Tuple[str, int, str], ...] = (
    ('auto_tuning', 0x3002, 'int16'),
    ('stiffness', 0x3003, 'int16'),
    ('inertia_ratio', 0x3004, 'int16'),
    ('estimation_speed', 0x3631, 'int16'),
)
#: 게인만 다시 읽는 간격 · 읽기 실패가 있으면 짧게
GAIN_REFRESH_SEC = 60.0   # 화면에서 쓴 게인이 1 분 안에 표에 보이게 · 108 (다)
GAIN_RETRY_SEC = 15.0

#: 멈춘 메일박스 판정 · 139 ③ · 응답 없음 연속 횟수 · 첫 번째부터 걸린 시간 · 멈춘 동안 떠보는 간격
MAILBOX_STUCK_COUNT = 3
MAILBOX_STUCK_SPAN_SEC = 10.0
MAILBOX_PROBE_SEC = 30.0
MAILBOX_SKIPPED = '메일박스 응답 없음 · 읽기 쉼'

#: 응답이 없었다는 CLI 글 · IgH 1.6.9 는 upload request 시간 초과(SM0 쓰기 WKC 0)를 커널 로그에만 「timeout」 으로 적고
#: CLI 에는 「Failed to upload SDO: Input/output error」 (실물 S-4 · S 3회차) · 「wrong SDO」 도 같은 EIO 라 연속 횟수 · 시간으로 가른다
_NO_RESPONSE = re.compile(r'input/output error|timeout|timed out', re.IGNORECASE)
#: 드라이브가 abort 로 답함 · 메일박스는 살아 있다
_ANSWERED = re.compile(r'abort', re.IGNORECASE)

Signature = FrozenSet[Tuple[int, int]]
Slot = Tuple[int, int]
BusStates = FrozenSet[Tuple[int, int, str]]


def visible_slaves(
    masters: Dict[str, Dict[str, Any]], previous: Optional[Signature] = None,
) -> Signature:
    """`_poll_ethercat_bus_status` 의 마스터별 상태 → 보이는 (마스터, 링 위치) 집합

    마스터 조회가 실패한 폴링(`available` 거짓)은 「슬레이브 0개」 가 아니라 「모름」 이다 ·
    그 마스터는 직전 구성을 그대로 둔다 · 안 그러면 조회가 한 번 삐끗할 때 드라이브가
    사라진 것으로 보여 차단이 잠깐 풀린다 · 처음부터 조회가 안 되는 마스터(ethercat 없음)는
    본 적이 없으니 아무것도 없다.
    """
    seen = set()
    for key, status in (masters or {}).items():
        if not isinstance(status, dict):
            continue
        master = parse_int(status.get('master_index'))
        if master is None:
            master = parse_int(key)
        if master is None:
            continue
        if not status.get('available'):
            seen.update(item for item in (previous or ()) if item[0] == int(master))
            continue
        for position in (status.get('states_by_position') or {}):
            value = parse_int(position)
            if value is not None:
                seen.add((int(master), int(value)))
    return frozenset(seen)


def master_claimed(masters: Dict[str, Dict[str, Any]]) -> bool:
    """모터 프로그램이 마스터를 잡고 있나 · `ethercat master` 의 Phase: Operation 또는 Active: yes"""
    return any(
        isinstance(status, dict) and status.get('available') and (
            bool(status.get('master_active'))
            or str(status.get('phase') or '').strip().lower().startswith('operation')
        )
        for status in (masters or {}).values()
    )


def settle_needed(masters: Dict[str, Dict[str, Any]], states: BusStates) -> float:
    """읽기 전에 슬레이브 상태가 그대로여야 하는 시간 · 125"""
    if master_claimed(masters) and any(state != 'OP' for _m, _p, state in states):
        return STUCK_SEC
    return SETTLE_SEC


def mailbox_answered(detail: str) -> Optional[bool]:
    """실패한 `ethercat upload` 의 글 → 드라이브가 답했나 · True 답함(abort) · False 응답 없음 · None 모름 · 139 ③"""
    text = str(detail or '')
    if _ANSWERED.search(text):
        return True
    if _NO_RESPONSE.search(text):
        return False
    return None


def op_slaves(masters: Dict[str, Dict[str, Any]], previous: FrozenSet[Slot] = frozenset()) -> FrozenSet[Slot]:
    """OP 인 (마스터, 링 위치) · 조회가 실패한 마스터는 직전 그대로(`visible_slaves` 와 같은 규칙) · 139 ③"""
    found = set()
    for key, status in (masters or {}).items():
        if not isinstance(status, dict):
            continue
        master = parse_int(status.get('master_index'))
        if master is None:
            master = parse_int(key)
        if master is None:
            continue
        if not status.get('available'):
            found.update(item for item in previous if item[0] == int(master))
            continue
        for position, state in (status.get('states_by_position') or {}).items():
            value = parse_int(position)
            if value is not None and str(state or '').upper() == 'OP':
                found.add((int(master), int(value)))
    return frozenset(found)


class _BusBusy(Exception):
    """`ethercat_mailbox` 가 보내지 않음(버스 설정 중 · 잠금 못 잡음) · 이번 읽기는 없던 것으로"""


def bus_states(masters: Dict[str, Dict[str, Any]]) -> BusStates:
    """보이는 슬레이브의 (마스터, 링 위치, 상태) · 이게 바뀌는 동안은 마스터가 설정 중이다"""
    found = set()
    for key, status in (masters or {}).items():
        if not isinstance(status, dict) or not status.get('available'):
            continue
        master = parse_int(status.get('master_index'))
        if master is None:
            master = parse_int(key)
        if master is None:
            continue
        for position, state in (status.get('states_by_position') or {}).items():
            value = parse_int(position)
            if value is not None:
                found.add((int(master), int(value), str(state or '').upper()))
    return frozenset(found)


class MinasAbsoluteCheck:
    def __init__(
        self,
        *,
        parse_slaves: Callable[[str], List[Dict[str, Any]]],
        axis_for_slave: Callable[[int, int], Optional[int]],
        runner: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.time,
        spawn: Optional[Callable[[Callable[[], None]], None]] = None,
        log_warning: Callable[[str], None] = lambda _message: None,
        bus_configuring: Callable[[], bool] = ethercat_mailbox.configuring,
    ) -> None:
        self._parse_slaves = parse_slaves
        self._axis_for_slave = axis_for_slave
        # 부를 때 `subprocess.run` 을 찾는다 · 시험의 `mock.patch('subprocess.run')` 이 먹게
        self._runner = runner or (lambda *args, **kwargs: subprocess.run(*args, **kwargs))
        #: SDO 는 잠금 안에서 · 버스 설정 중이면 안 보냄 · 125
        self._sdo = ethercat_mailbox.guarded(self._runner)
        self._bus_configuring = bus_configuring
        self._clock = clock
        self._spawn = spawn or self._spawn_thread
        self._log_warning = log_warning
        self._lock = threading.Lock()
        #: 마지막으로 읽기 시작한 구성 · None = 아직 한 번도 안 봄
        self._signature: Optional[Signature] = None
        self._running = False
        #: 읽어야 하는데 버스가 자리 잡기를 기다리는 중
        self._pending = False
        #: 마지막으로 본 슬레이브 상태 · 그 상태가 된 때 · 읽기 전 그대로여야 하는 시간
        self._states: Optional[BusStates] = None
        self._states_since = 0.0
        self._settle_needed = SETTLE_SEC
        #: 「확인 불가」 다시 읽기 · 다음 때 · 처음 실패한 때
        self._retry_at: Optional[float] = None
        self._first_failure_at: Optional[float] = None
        #: 게인만 다시 읽을 때 · None = 잡히지 않음(앱솔루트 읽기가 끝나면 잡는다)
        self._gains_due: Optional[float] = None
        self._summary: Dict[str, Any] = minas_absolute.checking_summary()
        #: 멈춘 메일박스 · 139 ③ · OP 인 슬레이브 · 슬롯 → 응답 없음 연속(횟수 · 첫 때) · 마지막으로 답한 때 ·
        #: 멈춤(때 · 다음 떠보기)
        self._op: FrozenSet[Slot] = frozenset()
        self._no_answer: Dict[Slot, Dict[str, float]] = {}
        self._answered_at: Dict[Slot, float] = {}
        self._stuck: Dict[Slot, Dict[str, float]] = {}

    @staticmethod
    def _spawn_thread(target: Callable[[], None]) -> None:
        threading.Thread(target=target, name='minas-absolute-check', daemon=True).start()

    # -- 폴링에서 부른다 -------------------------------------------------- #

    def observe(self, masters: Dict[str, Dict[str, Any]]) -> None:
        now = self._clock()
        with self._lock:
            states = bus_states(masters)
            if states != self._states:
                self._states = states
                self._states_since = now
            self._settle_needed = settle_needed(masters, states)
            signature = visible_slaves(masters, self._signature)
            self._observe_mailboxes(masters, signature)
            if signature != self._signature:
                previous = list(self._summary.get('drives') or [])
                self._signature = signature
                self._retry_at = None
                self._first_failure_at = None
                if not signature:
                    self._summary = minas_absolute.summary([], checked_at=now)
                    self._pending = False
                    return
                self._summary = minas_absolute.checking_summary(previous)
                self._pending = True
            elif self._retry_at is not None and now >= self._retry_at:
                self._retry_at = None
                self._pending = True
            if self._running or now - self._states_since < self._settle_needed:
                # 도는 읽기가 끝나면 구성이 달라진 것을 보고 다시 읽는다 ·
                # 버스가 자리 잡기 전엔 안 읽는다(마스터가 드라이브를 설정 중 · 메일박스가 붐빈다 · 110)
                return
            gains_due = self._gains_due is not None and now >= self._gains_due
            if (self._pending or gains_due) and self._configuring():
                return          # 모터 프로그램이 버스를 설정 중 · 표시가 사라지면 다시 · 125
            if self._pending:
                self._pending = False
                self._running = True
                target = self._run
            elif self._gains_due is not None and now >= self._gains_due:
                self._gains_due = None
                self._running = True
                target = self._refresh_gains
            else:
                return
        self._spawn(target)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            summary = dict(self._summary)
            summary['drives'] = [dict(drive) for drive in summary.get('drives') or []]
            # 멈춘 메일박스 · 막지 않는다(PDO · 재생은 그대로) · 알리기만 · 139 ③
            summary['stuck_mailboxes'] = [
                self._stuck_entry(slot, info) for slot, info in sorted(self._stuck.items())
            ]
            return summary

    # -- 멈춘 메일박스 · 139 ③ ---------------------------------------------- #

    def _observe_mailboxes(self, masters: Dict[str, Dict[str, Any]], signature: Signature) -> None:
        """폴링마다 · 잠금 안에서 부른다 · OP 를 벗어난 슬레이브 · 구성 변화(재스캔)는 판정을 처음부터"""
        self._op = op_slaves(masters, self._op)
        if signature != self._signature:
            dropped = sorted(self._stuck)
            self._no_answer.clear()
            self._answered_at.clear()
        else:
            dropped = sorted(slot for slot in self._stuck if slot not in self._op)
            self._no_answer = {slot: streak for slot, streak in self._no_answer.items() if slot in self._op}
        for slot in dropped:
            self._stuck.pop(slot, None)
            self._log_warning(f'{self._slot_label(slot)} 드라이브 메일박스 멈춤 해제 · 슬레이브를 다시 잡음')

    def _mailbox_may_send(self, slot: Slot) -> bool:
        """멈춘 드라이브엔 안 보낸다 · `MAILBOX_PROBE_SEC` 마다 한 번만 떠본다"""
        with self._lock:
            stuck = self._stuck.get(slot)
            if stuck is None:
                return True
            now = self._clock()
            if now < stuck['probe_at']:
                return False
            stuck['probe_at'] = now + MAILBOX_PROBE_SEC
            return True

    def _note_mailbox(self, slot: Slot, answered: Optional[bool]) -> None:
        """SDO 하나의 결과 · True 답함 · False 응답 없음 · None 모름(판정에 안 씀)"""
        if answered is None:
            return
        now = self._clock()
        message = ''
        with self._lock:
            if answered:
                self._answered_at[slot] = now
                self._no_answer.pop(slot, None)
                if self._stuck.pop(slot, None) is not None:
                    message = f'{self._slot_label(slot)} 드라이브 메일박스 응답 돌아옴 · 멈춤 해제'
            elif slot in self._op:
                # OP 가 아니면 마스터가 설정 중일 수 있다 · 판정에 안 쓴다
                streak = self._no_answer.setdefault(slot, {'count': 0, 'first_at': now})
                streak['count'] += 1
                others_answered = any(
                    other != slot and at >= streak['first_at'] for other, at in self._answered_at.items()
                )
                if (
                    slot not in self._stuck
                    and streak['count'] >= MAILBOX_STUCK_COUNT
                    and now - streak['first_at'] >= MAILBOX_STUCK_SPAN_SEC
                    and others_answered
                ):
                    self._stuck[slot] = {'since': now, 'probe_at': now + MAILBOX_PROBE_SEC}
                    message = self._stuck_entry(slot, self._stuck[slot])['message']
        if message:
            self._log_warning(message)

    def _slot_label(self, slot: Slot) -> str:
        axis = self._axis_for_slave(*slot)
        return f'{int(axis)}번' if axis is not None else f'슬레이브 {slot[1]}'

    def _stuck_entry(self, slot: Slot, info: Dict[str, float]) -> Dict[str, Any]:
        axis = self._axis_for_slave(*slot)
        return {
            'master_index': slot[0],
            'slave_position': slot[1],
            'axis': axis,
            'since': info['since'],
            'message': f'{self._slot_label(slot)} 드라이브 메일박스 응답 없음 · 그 드라이브 제어 전원을 껐다 켜세요',
        }

    # -- 읽기 ------------------------------------------------------------- #

    def _run(self) -> None:
        while True:
            with self._lock:
                signature = self._signature
            try:
                drives = self._read(signature or frozenset())
            except _BusBusy:
                with self._lock:
                    # 이번 읽기는 없던 것으로 · 「확인 중」 그대로 · 버스가 자리 잡으면 다시 · 125
                    self._pending = True
                    self._running = False
                return
            except Exception as exc:  # noqa: BLE001 · 어떤 실패도 「확인 불가」 로
                self._log_warning(f'MINAS 앱솔루트 확인 실패: {exc}')
                drives = [
                    self._drive(master, position, read_error=str(exc))
                    for master, position in sorted(signature or ())
                ]
            with self._lock:
                if signature != self._signature:
                    continue                # 읽는 사이 구성이 바뀜 · 다시
                now = self._clock()
                if signature:
                    self._summary = minas_absolute.summary(drives, checked_at=now)
                self._schedule_retry(drives, now)
                self._schedule_gains(drives, now)
                self._running = False
                return

    def _schedule_gains(self, drives: List[Dict[str, Any]], now: float) -> None:
        """다음 게인 다시 읽기 · 잠금 안에서 부른다 · 읽기 실패가 있으면 짧게"""
        if not drives:
            self._gains_due = None
            return
        failed = any((drive.get('gains') or {}).get('error') for drive in drives)
        self._gains_due = now + (GAIN_RETRY_SEC if failed else GAIN_REFRESH_SEC)

    def _refresh_gains(self) -> None:
        """게인만 다시 읽어 지금 목록에 얹는다 · 앱솔루트 판정은 그대로"""
        with self._lock:
            signature = self._signature
            drives = [dict(drive) for drive in self._summary.get('drives') or []]
        try:
            for drive in drives:   # 목록은 MINAS 드라이브만 담는다
                drive['gains'] = self._read_gains(int(drive['master_index']), int(drive['slave_position']))
        except _BusBusy:
            with self._lock:
                # 지금 게인은 그대로 · 조금 뒤 다시 · 125
                self._gains_due = self._clock() + GAIN_RETRY_SEC
                self._running = False
            return
        with self._lock:
            now = self._clock()
            if signature == self._signature and self._summary.get('drives'):
                by_slot = {(d['master_index'], d['slave_position']): d.get('gains') for d in drives}
                self._summary = {
                    **self._summary,
                    'drives': [
                        {**drive, 'gains': by_slot.get((drive['master_index'], drive['slave_position']), drive.get('gains'))}
                        for drive in self._summary['drives']
                    ],
                }
                self._schedule_gains(self._summary['drives'], now)
            self._running = False

    def _read_gains(self, master: int, position: int) -> Dict[str, Any]:
        """자동조정 · 강성 · 관성비 · 추정 속도 · 하나라도 못 읽으면 error 에 이유(값은 읽은 것만)"""
        gains: Dict[str, Any] = {name: None for name, _index, _type in GAIN_OBJECTS}
        errors = []
        for name, index, data_type in GAIN_OBJECTS:
            value, error = self._upload(master, position, index, data_type)
            gains[name] = value
            if error:
                # 하나가 안 되면 그 드라이브엔 더 묻지 않는다 · 늦은 응답이 다음 요청의 답으로 섞인다(U-1b)
                errors.append(error)
                break
        gains['error'] = ' / '.join(errors)
        gains['read_at'] = self._clock()
        return gains

    def _schedule_retry(self, drives: List[Dict[str, Any]], now: float) -> None:
        """읽기 실패(「확인 불가」)가 남았으면 다음 읽기를 잡는다 · 잠금 안에서 부른다"""
        if not any(drive.get('status') == minas_absolute.DRIVE_UNKNOWN for drive in drives):
            self._retry_at = None
            self._first_failure_at = None
            return
        if self._first_failure_at is None:
            self._first_failure_at = now
        fast = now - self._first_failure_at < RETRY_FAST_WINDOW_SEC
        self._retry_at = now + (RETRY_FAST_SEC if fast else RETRY_SLOW_SEC)

    def _read(self, signature: Signature) -> List[Dict[str, Any]]:
        drives: List[Dict[str, Any]] = []
        for master in sorted({master for master, _position in signature}):
            positions = sorted(position for m, position in signature if m == master)
            vendors, list_error = self._vendors(master)
            for position in positions:
                if list_error or position not in vendors:
                    # 제조사를 모르면 MINAS 가 아니라고 단정하지 않는다 · 「확인 불가」
                    drives.append(self._drive(
                        master, position,
                        read_error=list_error or '슬레이브 정보(vendor) 없음',
                    ))
                    continue
                vendor, alias = vendors[position]
                if vendor != minas_absolute.MINAS_VENDOR_ID:
                    continue
                mode, mode_error = self._upload(master, position, 0x3015, 'int16')
                # 앞 읽기가 안 되면 같은 드라이브에 바로 더 묻지 않는다 · 막 켜진 드라이브는 응답이 늦고
                # 늦은 0x3015 응답이 다음 0x603F 요청의 답으로 섞인다(커널 「wrong SDO」 · 실물 U-1b 10-13) · 다음 다시 읽기에서
                code, code_error = (None, '') if mode_error else self._upload(master, position, 0x603F, 'uint16')
                drive = self._drive(
                    master, position,
                    alias=alias,
                    absolute_mode=mode,
                    error_code=code,
                    read_error=mode_error,
                    error_code_error=code_error,
                )
                if mode_error or code_error:
                    drive['gains'] = {name: None for name, _index, _type in GAIN_OBJECTS}
                    drive['gains'].update(error='앞 읽기 실패로 건너뜀', read_at=self._clock())
                else:
                    drive['gains'] = self._read_gains(master, position)   # 108 · 막지 않는다
                drives.append(drive)
        return drives

    def _configuring(self) -> bool:
        try:
            return bool(self._bus_configuring())
        except Exception:  # noqa: BLE001 · 표시를 못 읽으면 없는 것으로(예전처럼 상태로만 판단)
            return False

    def _vendors(self, master: int) -> Tuple[Dict[int, Tuple[Optional[int], Optional[int]]], str]:
        try:
            completed = self._runner(
                ['ethercat', 'slaves', '-m', str(master), '-v'],
                check=False, capture_output=True, text=True, timeout=SLAVES_TIMEOUT_SEC,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {}, f'ethercat slaves -v 실패: {exc}'
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip() or f'종료 코드 {completed.returncode}'
            return {}, f'ethercat slaves -v 실패: {detail}'
        vendors = {}
        for slave in self._parse_slaves(completed.stdout or ''):
            position = parse_int(slave.get('slave_position'))
            if position is None or parse_int(slave.get('master_index')) not in (None, master):
                continue
            vendors[int(position)] = (parse_int(slave.get('vendor_id')), parse_int(slave.get('ethercat_alias')))
        return vendors, ''

    def _upload(self, master: int, position: int, index: int, data_type: str) -> Tuple[Optional[int], str]:
        slot = (int(master), int(position))
        if not self._mailbox_may_send(slot):
            return None, f'0x{index:04X} {MAILBOX_SKIPPED}'     # 멈춘 메일박스 · 떠볼 때까지 안 보냄 · 139 ③
        try:
            completed = self._sdo(
                [
                    'ethercat', 'upload', '-m', str(master), '-p', str(position),
                    '-t', data_type, f'0x{index:04X}', '0',
                ],
                check=False, capture_output=True, text=True, timeout=UPLOAD_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            self._note_mailbox(slot, False)
            return None, f'0x{index:04X} {exc}'
        except OSError as exc:
            return None, f'0x{index:04X} {exc}'
        if ethercat_mailbox.is_refused(completed):
            raise _BusBusy((completed.stderr or '').strip())
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip() or 'unknown error'
            self._note_mailbox(slot, mailbox_answered(detail))
            return None, f'0x{index:04X} {detail}'
        self._note_mailbox(slot, True)
        parts = (completed.stdout or '').strip().split()
        # `0x0000 0` · 마지막 칸(10진) · 스캐너 `_read_drive_params` 와 같은 읽기
        value = parse_int(parts[-1]) if parts else None
        if value is None:
            return None, f'0x{index:04X} 응답을 읽지 못함: {(completed.stdout or "").strip()!r}'
        return value, ''

    def _drive(
        self,
        master: int,
        position: int,
        *,
        alias: Optional[int] = None,
        absolute_mode: Optional[int] = None,
        error_code: Optional[int] = None,
        read_error: str = '',
        error_code_error: str = '',
    ) -> Dict[str, Any]:
        drive = {
            'master_index': int(master),
            'slave_position': int(position),
            'ethercat_alias': alias,
            'axis': self._axis_for_slave(int(master), int(position)),
            'absolute_mode': absolute_mode,
            'error_code': error_code,
            # 오류 코드를 못 읽은 것만으로는 막지 않는다 · 알람은 모터 상태가 따로 본다
            'error': ' / '.join(item for item in (read_error, error_code_error) if item),
            'status': minas_absolute.classify_drive(absolute_mode, error_code, read_error),
        }
        # 화면은 이 글을 그대로 보여 준다 · 판정을 다시 하지 않는다
        drive['problem'] = minas_absolute.drive_problem(drive)
        return drive
