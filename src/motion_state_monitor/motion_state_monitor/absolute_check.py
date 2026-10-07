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
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from motion_common import minas_absolute

from .motor_values import parse_int

#: SDO 하나 읽기 제한 시간
UPLOAD_TIMEOUT_SEC = 2.0
#: `ethercat slaves -v` 제한 시간
SLAVES_TIMEOUT_SEC = 3.0

Signature = FrozenSet[Tuple[int, int]]


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
    ) -> None:
        self._parse_slaves = parse_slaves
        self._axis_for_slave = axis_for_slave
        # 부를 때 `subprocess.run` 을 찾는다 · 시험의 `mock.patch('subprocess.run')` 이 먹게
        self._runner = runner or (lambda *args, **kwargs: subprocess.run(*args, **kwargs))
        self._clock = clock
        self._spawn = spawn or self._spawn_thread
        self._log_warning = log_warning
        self._lock = threading.Lock()
        #: 마지막으로 읽기 시작한 구성 · None = 아직 한 번도 안 봄
        self._signature: Optional[Signature] = None
        self._running = False
        self._summary: Dict[str, Any] = minas_absolute.checking_summary()

    @staticmethod
    def _spawn_thread(target: Callable[[], None]) -> None:
        threading.Thread(target=target, name='minas-absolute-check', daemon=True).start()

    # -- 폴링에서 부른다 -------------------------------------------------- #

    def observe(self, masters: Dict[str, Dict[str, Any]]) -> None:
        with self._lock:
            signature = visible_slaves(masters, self._signature)
            if signature == self._signature:
                return
            previous = list(self._summary.get('drives') or [])
            self._signature = signature
            if not signature:
                self._summary = minas_absolute.summary([], checked_at=self._clock())
                return
            self._summary = minas_absolute.checking_summary(previous)
            if self._running:
                # 도는 읽기가 끝나면 구성이 달라진 것을 보고 다시 읽는다
                return
            self._running = True
        self._spawn(self._run)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            summary = dict(self._summary)
            summary['drives'] = [dict(drive) for drive in summary.get('drives') or []]
            return summary

    # -- 읽기 ------------------------------------------------------------- #

    def _run(self) -> None:
        while True:
            with self._lock:
                signature = self._signature
            try:
                drives = self._read(signature or frozenset())
            except Exception as exc:  # noqa: BLE001 · 어떤 실패도 「확인 불가」 로
                self._log_warning(f'MINAS 앱솔루트 확인 실패: {exc}')
                drives = [
                    self._drive(master, position, read_error=str(exc))
                    for master, position in sorted(signature or ())
                ]
            with self._lock:
                if signature != self._signature:
                    continue                # 읽는 사이 구성이 바뀜 · 다시
                if signature:
                    self._summary = minas_absolute.summary(drives, checked_at=self._clock())
                self._running = False
                return

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
                code, code_error = self._upload(master, position, 0x603F, 'uint16')
                drives.append(self._drive(
                    master, position,
                    alias=alias,
                    absolute_mode=mode,
                    error_code=code,
                    read_error=mode_error,
                    error_code_error=code_error,
                ))
        return drives

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
        try:
            completed = self._runner(
                [
                    'ethercat', 'upload', '-m', str(master), '-p', str(position),
                    '-t', data_type, f'0x{index:04X}', '0',
                ],
                check=False, capture_output=True, text=True, timeout=UPLOAD_TIMEOUT_SEC,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f'0x{index:04X} {exc}'
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip() or 'unknown error'
            return None, f'0x{index:04X} {detail}'
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
