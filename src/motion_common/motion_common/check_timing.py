"""실행 준비 검사 단계별 시간 글 · motion_run_manager 로그와 브리지 준비 확인 로그가 같이 쓴다 · 수정 목록 174

검사 답(`check`)의 `timing_ms` 칸 · 단위 ms · 없는 단계는 빠진다.

    queued_ms       검사 작업 스레드 줄에서 기다린 시간(앞 검사가 길면)
    records_ms      모션 파일 읽기 · 조인트별 배열(캐시면 짧다)
    samples_ms      20 ms 재샘플 · 속도·가속 검사(다른 스레드가 짓는 중이면 기다린 시간 포함)
    samples_cached  재샘플을 이 검사가 새로 계산하지 않았다(캐시 · 미리 짓기 · 다른 스레드)
    build_ms        계획 짓기 전체
    records_from    파일 단계 출처 · 수정 목록 208 · memory(메모리) · artifact(변환본 · 디스크) ·
                    compiled(자식 프로세스가 변환) · parsed(이 프로세스에서 읽음) · file(변환본 자리 없음)
    samples_from    재샘플 단계 출처 · memory · artifact · compiled · computed(이 프로세스에서 계산)
"""

from __future__ import annotations

from typing import Any, Mapping

STAGES = (
    ('queued_ms', '대기'),
    ('records_ms', '파일'),
    ('samples_ms', '재샘플'),
    ('build_ms', '계획'),
)


#: 출처 글자 · 수정 목록 208 · 「파일 3(변환본) · 재샘플 2(변환본)」 · 출처가 없으면 옛 글자 그대로
RECORDS_SOURCE_LABELS = {'memory': '캐시', 'artifact': '변환본', 'compiled': '변환', 'parsed': '읽기'}
SAMPLES_SOURCE_LABELS = {'memory': '캐시', 'artifact': '변환본', 'compiled': '새로', 'computed': '새로'}


def stage_text(timing: Any) -> str:
    """「대기 0 · 파일 3200 · 재샘플 1800(새로) · 계획 5050」 · 단위 글자는 부르는 쪽이 · 없으면 빈 글자"""
    if not isinstance(timing, Mapping):
        return ''
    parts = []
    for key, label in STAGES:
        value = timing.get(key)
        if value is None:
            continue
        try:
            text = f'{label} {float(value):.0f}'
        except (TypeError, ValueError):
            continue
        if key == 'records_ms' and timing.get('records_from') in RECORDS_SOURCE_LABELS:
            text += f'({RECORDS_SOURCE_LABELS[timing["records_from"]]})'
        if key == 'samples_ms' and timing.get('samples_from') in SAMPLES_SOURCE_LABELS:
            text += f'({SAMPLES_SOURCE_LABELS[timing["samples_from"]]})'
        elif key == 'samples_ms' and 'samples_cached' in timing:
            text += '(캐시)' if timing.get('samples_cached') else '(새로)'
        parts.append(text)
    return ' · '.join(parts)
