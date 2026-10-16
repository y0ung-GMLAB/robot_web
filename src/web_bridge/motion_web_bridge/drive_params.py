"""MINAS 드라이브 파라미터 · 고급 보기·쓰기 · 수정 목록 109 · 114 (2026-10-13)

드라이브에 지금 들어 있는 값(RAM) · 부팅 때 우리가 쓸 값 · 팩토리값을 한 표에 · 다르면 표시.

    드라이브 현재값   `ethercat upload` · Motor Manager 를 멈추지 않는다
    부팅 시 적용값   **지금 도는** 모터 프로그램이 켜질 때 쓴 값(`boot_params` · 세션 기록) · 여기서 다른
                    값을 써도 재시작하면 돌아간다 · 지금 설정(플랫폼 기반 → 현장 공통 설정 → 모터별 칸)과
                    다르면 `boot_next` 에 「적용하면」 값 · 수정 목록 116 (전엔 지금 설정으로 계산해 보여 줘
                    적용 안 한 새 공통 값이 드라이브에 있는 줄 알았다)
    팩토리값          A6B 레퍼런스 SX-DSV03190 R11.0 부록(파라미터 · 객체 기본값) · A~C 프레임

쓰기는 RAM 에만 · Motor Manager 를 멈추지 않는다 · 되읽어 같은지 본다 · 모터가 움직이는 동안 거절 ·
드라이브 동작을 직접 바꾸는 객체(제어 워드 · 목표 · 운전 모드 · PDO 배선 · EEPROM 저장 · 다회전 클리어 ·
앱솔루트 방식 · 토크 오프셋 0x60B2(사용자 결정 2026-10-13 · 안 씀))는 여기서 못 쓴다 · 전용 버튼이 있다.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

from motion_common import ethercat_mailbox

TYPE_RANGES = {
    'int8': (-128, 127), 'uint8': (0, 255),
    'int16': (-32768, 32767), 'uint16': (0, 65535),
    'int32': (-2147483648, 2147483647), 'uint32': (0, 4294967295),
}

#: (묶음, 이름, 번호, index, subindex, 형식, 팩토리값, 단위, 메모)
#: 메모 · C = 전원 재투입 때 반영(속성 C) · auto = 모터 설정에서 계산해 부팅 때 씀
CATALOG: List[Tuple[str, str, str, int, int, str, Optional[int], str, str]] = [
    ('게인', '자동조정', 'Pr0.02', 0x3002, 0, 'int16', 1, '', ''),
    ('게인', '강성', 'Pr0.03', 0x3003, 0, 'int16', 13, '', ''),
    ('게인', '관성비', 'Pr0.04', 0x3004, 0, 'int16', 250, '%', '자동조정이 바꿈'),
    ('게인', '관성비 추정 속도', 'Pr6.31', 0x3631, 0, 'int16', 1, '', ''),
    # 지령 필터 · 「드라이브 게인」 칸에서도 쓴다 · 2026-10-16 · Pr2.22 팩토리값은 프레임마다 다름(A~C 92 · D~H 139)
    ('지령 필터', '지령 스무딩 필터', 'Pr2.22', 0x3222, 0, 'int16', 92, '× 0.1 ms', 'D~H 프레임 팩토리값 139'),
    ('지령 필터', '지령 FIR 필터', 'Pr2.23', 0x3223, 0, 'int16', 10, '× 0.1 ms', '모터가 멈췄을 때만 바꿈'),
    ('앱솔루트 · 리밋', '앱솔루트 방식', 'Pr0.15', 0x3015, 0, 'int16', 1, '', 'C'),
    ('앱솔루트 · 리밋', '토크 한계', 'Pr0.13', 0x3013, 0, 'int16', 500, '%', ''),
    ('앱솔루트 · 리밋', '위치 편차 과대 기준', 'Pr0.14', 0x3014, 0, 'int32', 83886080, 'pulse', ''),
    ('앱솔루트 · 리밋', '리밋 스위치(구동 금지 입력) 설정', 'Pr5.04', 0x3504, 0, 'int16', 1, '', ''),
    ('앱솔루트 · 리밋', '과속도 기준', 'Pr5.13', 0x3513, 0, 'int16', 0, 'r/min', ''),
    ('앱솔루트 · 리밋', '모터 가동 범위', 'Pr5.14', 0x3514, 0, 'int16', 10, '× 0.1회전', ''),
    ('브레이크 · 정지', '브레이크 지연 · 멈춰 있을 때', 'Pr4.37', 0x3437, 0, 'int16', 0, 'ms', ''),
    ('브레이크 · 정지', '브레이크 지연 · 움직이는 중', 'Pr4.38', 0x3438, 0, 'int16', 0, 'ms', ''),
    ('브레이크 · 정지', '브레이크 해제 속도', 'Pr4.39', 0x3439, 0, 'int16', 30, 'r/min', ''),
    ('브레이크 · 정지', '서보 OFF 때 멈추는 방법', 'Pr5.06', 0x3506, 0, 'int16', 0, '', 'A6B 는 605B/605C 가 0 일 때만'),
    ('브레이크 · 정지', '알람 때 멈추는 방법', 'Pr5.10', 0x3510, 0, 'int16', 0, '', ''),
    ('브레이크 · 정지', '즉시 정지 토크', 'Pr5.11', 0x3511, 0, 'int16', 0, '%', ''),
    ('브레이크 · 정지', '과부하 알람 기준', 'Pr5.12', 0x3512, 0, 'int16', 0, '%', ''),
    ('브레이크 · 정지', '알람 때 모터 힘으로 세우는 최대 시간', 'Pr6.14', 0x3614, 0, 'int16', 200, 'ms', ''),
    ('입력 핀', 'SI1 입력 선택', 'Pr4.00', 0x3400, 0, 'uint32', 3289650, '', ''),
    ('입력 핀', 'SI2 입력 선택', 'Pr4.01', 0x3401, 0, 'uint32', 8487297, '', ''),
    ('입력 핀', 'SI3 입력 선택', 'Pr4.02', 0x3402, 0, 'uint32', 8553090, '', ''),
    ('입력 핀', 'SI4 입력 선택', 'Pr4.03', 0x3403, 0, 'uint32', 2236962, '', ''),
    ('입력 핀', 'SI5 입력 선택', 'Pr4.04', 0x3404, 0, 'uint32', 2105376, '', ''),
    ('입력 핀', 'SI6 입력 선택', 'Pr4.05', 0x3405, 0, 'uint32', 2171169, '', ''),
    ('입력 핀', 'SI7 입력 선택', 'Pr4.06', 0x3406, 0, 'uint32', 3158064, '', ''),
    ('입력 핀', 'SI8 입력 선택', 'Pr4.07', 0x3407, 0, 'uint32', 3223857, '', ''),
    ('CiA402', '최대 토크', '0x6072', 0x6072, 0, 'uint16', 5000, '× 0.1 %', 'auto'),
    ('CiA402', '소프트 리밋 하한', '0x607D:1', 0x607D, 1, 'int32', 0, 'pulse', 'auto'),
    ('CiA402', '소프트 리밋 상한', '0x607D:2', 0x607D, 2, 'int32', 0, 'pulse', 'auto'),
    ('CiA402', '최대 프로파일 속도', '0x607F', 0x607F, 0, 'uint32', 838860800, 'pulse/s', 'auto'),
    ('CiA402', '프로파일 가속', '0x6083', 0x6083, 0, 'uint32', 1000000, 'pulse/s²', 'auto'),
    ('CiA402', '프로파일 감속', '0x6084', 0x6084, 0, 'uint32', 1000000, 'pulse/s²', 'auto'),
    ('CiA402', '빠른 정지 감속', '0x6085', 0x6085, 0, 'uint32', 1000000, 'pulse/s²', ''),
    ('CiA402', '위치 편차 허용(따라오기 오차)', '0x6065', 0x6065, 0, 'uint32', 100000, 'pulse', ''),
    ('CiA402', '빠른 정지 방법', '0x605A', 0x605A, 0, 'int16', 2, '', ''),
    ('CiA402', 'Shutdown 때 방법', '0x605B', 0x605B, 0, 'int16', 1, '', ''),
    ('CiA402', 'Disable operation 때 방법', '0x605C', 0x605C, 0, 'int16', 1, '', ''),
    ('CiA402', '통신 알람 때 방법', '0x605E', 0x605E, 0, 'int16', 2, '', ''),
]

#: 여기서 못 쓰는 객체 · 이유
WRITE_BLOCKED: Dict[int, str] = {
    0x1010: 'EEPROM 저장은 「드라이브 저장(EEPROM)」 버튼으로',
    0x3015: '앱솔루트 방식은 「앱솔루트 설정」 버튼으로(전원 재투입 · 다회전 클리어 순서가 있다)',
    0x4D00: '다회전 클리어는 전용 버튼으로', 0x4D01: '다회전 클리어는 전용 버튼으로',
    0x6040: '제어 워드는 모터 프로그램이 쓴다', 0x6060: '운전 모드는 모터 프로그램이 정한다',
    0x607A: '목표 위치는 모터 프로그램이 쓴다', 0x60FF: '목표 속도는 모터 프로그램이 쓴다',
    0x6071: '목표 토크는 모터 프로그램이 쓴다',
    0x60B2: '토크 오프셋(중력 보정)은 쓰지 않기로 했다(사용자 결정 2026-10-13)',
}
#: PDO 배선 · 동기 관리자 · 통신 설정
WRITE_BLOCKED_RANGES = [(0x1600, 0x17FF, 'PDO 배선'), (0x1A00, 0x1BFF, 'PDO 배선'), (0x1C00, 0x1CFF, '통신 설정')]


def parse_object(text: Any) -> Tuple[int, int]:
    """「Pr5.04」 · 「5.04」 · 「0x3504」 · 「0x607D:2」 → (index, subindex)"""
    raw = str(text or '').strip().replace(' ', '')
    # Pr X.YY → 0x3XYY · YY 는 10진 번호를 그대로 16진 두 자리로 적는다(Pr5.12 → 0x3512 · Pr6.31 → 0x3631)
    match = re.fullmatch(r'(?:[Pp][Rr])?(\d)\.(\d{1,2})', raw)
    if match:
        return 0x3000 + int(match.group(1)) * 0x100 + int(match.group(2).zfill(2), 16), 0
    match = re.fullmatch(r'(?:0[xX])?([0-9a-fA-F]{4})[hH]?(?::(\d{1,3}|0[xX][0-9a-fA-F]{1,2}))?', raw)
    if not match:
        raise ValueError(f'객체를 알아보지 못했습니다: {text} (예 Pr5.04 · 0x3504 · 0x607D:2)')
    return int(match.group(1), 16), int(match.group(2), 0) if match.group(2) else 0


def write_block_reason(index: int) -> str:
    if index in WRITE_BLOCKED:
        return WRITE_BLOCKED[index]
    for low, high, name in WRITE_BLOCKED_RANGES:
        if low <= index <= high:
            return f'{name}는 여기서 바꾸지 않습니다'
    return ''


def parse_value(text: str) -> Optional[int]:
    """`ethercat upload -t T` 출력 마지막 칸(10진) · 못 읽으면 None"""
    tokens = str(text or '').split()
    if not tokens:
        return None
    try:
        return int(tokens[-1], 0)
    except ValueError:
        return None


class DriveParams:
    def __init__(
        self,
        *,
        runner: Callable[..., Any] = subprocess.run,
        target: Callable[[int], Dict[str, int]],
        boot_values: Callable[[int], Dict[Tuple[int, int], int]],
        safety_blocker: Callable[[], str],
        record: Callable[[Dict[str, Any]], None],
        timeout_sec: float = 5.0,
        boot_next: Optional[Callable[[int], Optional[Dict[Tuple[int, int], int]]]] = None,
        boot_stale: Optional[Callable[[], str]] = None,
    ) -> None:
        # SDO 는 다른 프로세스와 한 번에 하나 · 버스 설정 중이면 안 보냄 · 수정 목록 125
        self._runner = ethercat_mailbox.guarded(runner)
        self._target = target
        #: 지금 도는 모터 프로그램이 부팅 때 쓴 값 · 수정 목록 116
        self._boot_values = boot_values
        #: 「장비에 적용」 하면 쓸 값(지금 설정) · 다를 때만 표에 · 없으면 안 봄
        self._boot_next = boot_next
        #: 둘이 다르면 그 한 줄(「설정 적용 필요 · …」) · 표 위에
        self._boot_stale = boot_stale
        self._safety_blocker = safety_blocker
        self._record = record
        self._timeout = timeout_sec

    def _upload(self, target: Dict[str, int], index: int, sub: int, data_type: str) -> Tuple[Optional[int], str]:
        command = ['ethercat', 'upload', '-m', str(target['master']), '-p', str(target['position']),
                   '-t', data_type, f'0x{index:04X}', str(sub)]
        try:
            done = self._runner(command, check=False, capture_output=True, text=True, timeout=self._timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, str(exc)
        if done.returncode != 0:
            return None, (done.stderr or done.stdout or '').strip() or f'종료 코드 {done.returncode}'
        value = parse_value(done.stdout)
        return value, '' if value is not None else f'응답을 읽지 못함: {(done.stdout or "").strip()!r}'

    def table(self, axis: int) -> Dict[str, Any]:
        """자주 보는 객체 표 · 드라이브 현재값 · 부팅 시 적용값 · 팩토리값"""
        try:
            target = self._target(int(axis))
        except (TypeError, ValueError) as exc:
            return {'success': False, 'message': str(exc)}
        boot = self._boot_values(int(axis)) or {}
        upcoming = (self._boot_next(int(axis)) if self._boot_next else None) or {}
        rows = []
        for group, label, number, index, sub, data_type, factory, unit, memo in CATALOG:
            value, error = self._upload(target, index, sub, data_type)
            boot_value = 'auto' if memo == 'auto' else boot.get((index, sub))
            next_value = upcoming.get((index, sub)) if memo != 'auto' and upcoming else None
            rows.append({
                'group': group, 'label': label, 'number': number, 'index': index, 'subindex': sub,
                'type': data_type, 'unit': unit, 'memo': memo, 'factory': factory,
                'drive': value, 'error': error, 'boot': boot_value,
                # 적용하면 바뀔 값 · 지금 도는 세션의 부팅 값과 다를 때만 · 수정 목록 116
                'boot_next': next_value if next_value is not None and next_value != boot_value else None,
                'differs_factory': value is not None and factory is not None and value != factory,
                'differs_boot': value is not None and isinstance(boot_value, int) and value != boot_value,
                'writable': not write_block_reason(index),
            })
        return {'success': True, 'axis': int(axis), 'rows': rows,
                'boot_stale': (self._boot_stale() if self._boot_stale else '') or ''}

    def read(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            axis = int(payload.get('axis'))
            index, sub = parse_object(payload.get('object'))
            data_type = str(payload.get('type') or 'int16')
            if data_type not in TYPE_RANGES:
                raise ValueError(f'형식은 {", ".join(TYPE_RANGES)} 중 하나')
            target = self._target(axis)
        except (TypeError, ValueError) as exc:
            return {'success': False, 'message': str(exc)}
        value, error = self._upload(target, index, sub, data_type)
        boot = (self._boot_values(axis) or {}).get((index, sub))
        return {'success': not error, 'message': error or '읽었습니다', 'index': index, 'subindex': sub,
                'type': data_type, 'value': value, 'boot': boot}

    def write(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get('confirmed') is not True:
            return {'success': False, 'message': '쓰기 · 확인이 필요합니다'}
        try:
            axis = int(payload.get('axis'))
            index, sub = parse_object(payload.get('object'))
            data_type = str(payload.get('type') or 'int16')
            if data_type not in TYPE_RANGES:
                raise ValueError(f'형식은 {", ".join(TYPE_RANGES)} 중 하나')
            value = int(str(payload.get('value')).strip(), 0)
            low, high = TYPE_RANGES[data_type]
            if not low <= value <= high:
                raise ValueError(f'{data_type} 범위({low}~{high}) 밖입니다')
            reason = write_block_reason(index)
            if reason:
                raise ValueError(reason)
            target = self._target(axis)
        except (TypeError, ValueError) as exc:
            return {'success': False, 'message': f'쓰기 불가 · {exc}'}
        blocker = self._safety_blocker()
        if blocker:
            return {'success': False, 'message': f'쓰기 불가 · {blocker}'}
        before, _ = self._upload(target, index, sub, data_type)
        command = ['ethercat', 'download', '-m', str(target['master']), '-p', str(target['position']),
                   '-t', data_type, f'0x{index:04X}', str(sub), str(value)]
        try:
            done = self._runner(command, check=False, capture_output=True, text=True, timeout=self._timeout)
            error = '' if done.returncode == 0 else (done.stderr or done.stdout or '').strip() or f'종료 코드 {done.returncode}'
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = str(exc)
        after, read_error = self._upload(target, index, sub, data_type) if not error else (None, '')
        if not error and after != value:
            error = f'되읽기 {after} ≠ {value}{f" · {read_error}" if read_error else ""}'
        boot = (self._boot_values(axis) or {}).get((index, sub))
        notes = []
        if isinstance(boot, int) and boot != value:
            notes.append(f'부팅 때 {boot} 로 다시 씁니다(재시작하면 돌아감 · 남기려면 공통 설정이나 모터 칸에서)')
        record = {'event_type': 'minas_param_write', 'axis': axis, 'index': f'0x{index:04X}', 'subindex': sub,
                  'type': data_type, 'before': before, 'value': value, 'after': after, 'success': not error,
                  'message': error or '썼습니다(드라이브 RAM)'}
        self._record(record)
        return {
            'success': not error,
            'message': (f'0x{index:04X}:{sub} {before} → {after} · 지금부터 적용(전원을 끄면 사라짐 · 남기려면 「드라이브 저장(EEPROM)」)'
                        if not error else f'쓰기 실패 · {error}'),
            'notes': notes, 'before': before, 'after': after,
        }
