"""뒤에서 계획을 짓는 스레드가 GIL 을 혼자 쥐지 않게 · 짧게 일하고 잠깐 쉰다 · 수정 목록 171

NY 실물 2026-11-03 · 그룹 시작에서 진행 PC(floating1)가 제 `start_at` 확인을 0.4 s 안에 못 해
그룹이 취소됐다 · 그때 같은 프로세스에서 재생 목록 2번(920 s × 20 조인트)을 뒤에서 짓고 있었다(164).

파이썬 스레드는 GIL 하나를 나눠 쓴다 · 계산만 하는 스레드가 있으면 다른 스레드(실행기 · 재생 틱)는
5 ms 마다 넘겨받기를 기다려야 한다 · 기다리는 스레드가 여럿이면 그마저 공평하지 않아 한 스레드가 수백 ms
굶는다(CPython GIL · 잰 값 · 데스크톱에서 920 s 파일을 짓는 1.2 s 동안 실행기 왕복 최대 0.15~0.42 s ·
20 ms 재생 틱 최대 0.2~0.35 s 늦음 · 미니 PC 는 약 두 배).

여기서는 **표시한 스레드만** `RUN_SEC` 일할 때마다 `REST_SEC` 잔다 · 자는 동안 GIL 이 풀려 기다리던
스레드가 바로 받는다 · 짓기는 그만큼(약 2 할) 느려진다.

쉴 자리 · GC 세대 0 수거가 끝날 때(`gc.callbacks`) · 계획 짓기는 사전 · 목록을 쉬지 않고 만들므로
초당 수천 번 온다 · 그래서 짓는 코드(파일 읽기 · 20 ms 재샘플 · 속도 검사)에 손대지 않는다.
할당 없이 계산만 하는 구간(정렬의 비교 단계 등 · 수십 ms)과 GC 세대 2 수거 자체(수십 ms)는 못 끊는다.
수거 도중이라 그 사이 다른 스레드의 할당은 수거를 건너뛴다(CPython `collecting`) · 잃는 것은 없다.

표시 · `pace_current_thread()` · 그 스레드가 끝날 때까지 · 재생 목록 짓기 스레드(`DeferredPlaylist`)와
준비 검사 작업 스레드(`check`)가 쓴다 · 재생 · 실행기 · 그룹 스레드는 표시하지 않는다.
"""

from __future__ import annotations

import gc
import threading
import time

#: 이만큼 일하면 쉰다
RUN_SEC = 0.010
#: 쉬는 시간 · 기다리던 스레드가 GIL 을 받기에 넉넉하다(받은 뒤 그 스레드는 제 일을 끝낼 때까지 쥔다)
REST_SEC = 0.002

_local = threading.local()
_install_lock = threading.Lock()
_installed = False


def _on_gc(phase: str, _info: dict) -> None:
    if phase != 'stop':
        return
    rest_at = getattr(_local, 'rest_at', None)
    if rest_at is None or time.monotonic() < rest_at:
        return
    time.sleep(REST_SEC)
    _local.rest_at = time.monotonic() + RUN_SEC


def pace_current_thread() -> None:
    """이 스레드는 뒤 일 · 끝날 때까지 `RUN_SEC` 마다 `REST_SEC` 쉰다 · 여러 번 불러도 같다"""
    global _installed
    with _install_lock:
        if not _installed:
            gc.callbacks.append(_on_gc)
            _installed = True
    if getattr(_local, 'rest_at', None) is None:
        _local.rest_at = time.monotonic() + RUN_SEC


def is_paced() -> bool:
    """이 스레드가 표시됐는가 · 시험용"""
    return getattr(_local, 'rest_at', None) is not None
