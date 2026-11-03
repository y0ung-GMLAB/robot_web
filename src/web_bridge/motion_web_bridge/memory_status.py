"""이 PC 메모리 · 스왑 · 「메모리 부족」 알림 · 수정 목록 170

NY 실물 2026-11-03 · floating4(메모리 4.7 GB)가 920 s 애니 + Firefox 3D 화면으로 스왑 1.25 GB 까지
가서 실행기가 멈췄다 · 화면에는 아무 표시가 없었다. 이제 `/proc/meminfo` · `/proc/vmstat` 을 읽어
스케줄 상태(`/api/schedule/status` · 화면이 5 초마다 부른다)에 싣는다 · 다른 PC 것은 「PC 현황」 이
그 PC 웹에 같은 주소로 물어 받는다(그룹 연동 메시지는 그대로).

판정(기본값 · 아래 상수) · 둘 중 하나면 `low`:

    남은 메모리(MemAvailable) < 600 MB        새 프로그램 · 큰 파일 · 브라우저 탭 하나에 모자라다
    스왑 사용 ≥ 1024 MB                       재시작 직후 600 MB 정도는 남아 있다(실물) · 그 위로
    스왑 읽기(pswpin) ≥ 256 쪽/초(1 MB/s)    지금 스왑에서 읽어 들이는 중 · 실제로 느려지는 때

읽기는 파일 두 개 · 5 초 캐시 · 리눅스가 아니면(개발 PC) `available: False`.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

LOW_AVAILABLE_MB = 600
HIGH_SWAP_USED_MB = 1024
#: 쪽 = 4 KB · 256 쪽/초 = 1 MB/s
SWAP_IN_PAGES_PER_SEC = 256
CACHE_SEC = 5.0

MEMINFO = Path('/proc/meminfo')
VMSTAT = Path('/proc/vmstat')

_lock = threading.Lock()
_cache: Dict[str, Any] = {}
_last_swapin: Optional[tuple] = None


def parse_meminfo(text: str) -> Dict[str, int]:
    """`MemTotal:  4812345 kB` → {'MemTotal': 4812345} (kB)"""
    values: Dict[str, int] = {}
    for line in str(text or '').splitlines():
        name, _, rest = line.partition(':')
        parts = rest.split()
        if name and parts:
            try:
                values[name.strip()] = int(parts[0])
            except ValueError:
                continue
    return values


def parse_vmstat(text: str) -> Dict[str, int]:
    values: Dict[str, int] = {}
    for line in str(text or '').splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                values[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return values


def evaluate(meminfo: Mapping[str, int], swapin_rate: Optional[float] = None) -> Dict[str, Any]:
    """kB 값 → 화면 칸 · MB 는 정수"""
    total = int(meminfo.get('MemTotal') or 0) // 1024
    available = int(meminfo.get('MemAvailable', meminfo.get('MemFree', 0)) or 0) // 1024
    swap_total = int(meminfo.get('SwapTotal') or 0) // 1024
    swap_used = max(swap_total - int(meminfo.get('SwapFree') or 0) // 1024, 0)
    reasons = []
    if available < LOW_AVAILABLE_MB:
        reasons.append(f'남은 메모리 {available} MB')
    if swap_used >= HIGH_SWAP_USED_MB:
        reasons.append(f'스왑 {swap_used} MB')
    if swapin_rate is not None and swapin_rate >= SWAP_IN_PAGES_PER_SEC:
        reasons.append(f'스왑 읽는 중 {swapin_rate * 4 / 1024:.1f} MB/s')
    return {
        'available': True,
        'total_mb': total,
        'available_mb': available,
        'swap_total_mb': swap_total,
        'swap_used_mb': swap_used,
        'swap_in_pages_per_sec': None if swapin_rate is None else round(swapin_rate, 1),
        'low': bool(reasons),
        'reasons': reasons,
        'thresholds': {
            'available_mb': LOW_AVAILABLE_MB,
            'swap_used_mb': HIGH_SWAP_USED_MB,
            'swap_in_pages_per_sec': SWAP_IN_PAGES_PER_SEC,
        },
    }


def snapshot(*, now: Optional[float] = None, meminfo_path: Path = MEMINFO, vmstat_path: Path = VMSTAT) -> Dict[str, Any]:
    """이 PC 메모리 상태 · 5 초 캐시 · 못 읽으면 `available: False`"""
    global _last_swapin
    now = time.monotonic() if now is None else now
    with _lock:
        if _cache and now - _cache.get('_at', -1e9) < CACHE_SEC:
            return {key: value for key, value in _cache.items() if key != '_at'}
    try:
        meminfo = parse_meminfo(Path(meminfo_path).read_text(encoding='ascii', errors='replace'))
    except OSError:
        return {'available': False, 'low': False, 'reasons': []}
    rate = None
    try:
        swapin = parse_vmstat(Path(vmstat_path).read_text(encoding='ascii', errors='replace')).get('pswpin')
    except OSError:
        swapin = None
    with _lock:
        if swapin is not None:
            if _last_swapin is not None and now > _last_swapin[0]:
                rate = max(swapin - _last_swapin[1], 0) / (now - _last_swapin[0])
            _last_swapin = (now, swapin)
        result = evaluate(meminfo, rate)
        _cache.clear()
        _cache.update(result, _at=now)
    return result


def reset_cache() -> None:
    """시험용"""
    global _last_swapin
    with _lock:
        _cache.clear()
        _last_swapin = None
