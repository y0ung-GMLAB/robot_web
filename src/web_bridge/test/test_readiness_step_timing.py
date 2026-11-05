"""준비 확인 단계별 시간 · 느리거나 거절이면 로그 한 줄 · 느린 거절은 사유에도 · 수정 목록 174

NY 실물 2026-11-05 · 재부팅 뒤 첫 그룹 시작 · 진행 PC 로그 「준비 거절 · 로컬 Web Bridge 응답 없음: timed out」 ·
어느 단계(실행 컨텍스트 · 재생 파일 · 실행 준비 검사 · 그 안의 파일 읽기 · 재샘플)가 느렸는지 기록이 없었다.
"""

import threading
import time
from types import SimpleNamespace
from unittest import mock

from motion_web_bridge import coordination_bridge
from motion_web_bridge.coordination_bridge import local_motion_readiness, readiness_timing_text


class _ReadyContext:
    def reconcile_blocking(self, timeout_sec):
        return {'ready': True}


def _bridge(check, *, logger=None, context_delay=0.0):
    context = _ReadyContext()
    if context_delay:
        def slow(timeout_sec):
            time.sleep(context_delay)
            return {'ready': True}
        context.reconcile_blocking = slow
    bridge = SimpleNamespace(
        _execution_context=context,
        _motion_run_lock=threading.Lock(), _motion_run_status={'state': 'idle'},
        _safety_status_lock=threading.Lock(), _safety_status={},
        motion_run_check=check,
    )
    if logger is not None:
        bridge.get_logger = lambda: logger
    return bridge


def _selection(monkeypatch):
    monkeypatch.setattr(
        coordination_bridge, '_local_motion_selection',
        lambda _bridge: {'motion_file_id': 'a.json', 'mapping_file_id': 'map.yaml'},
    )


def test_a_slow_readiness_logs_each_step_and_the_check_stages(monkeypatch):
    _selection(monkeypatch)
    monkeypatch.setattr(coordination_bridge, 'READINESS_SLOW_LOG_MS', 0.0)
    logger = mock.Mock()
    check_timing = {
        'queued_ms': 0.4, 'records_ms': 3210.0, 'samples_ms': 1820.0,
        'samples_cached': False, 'build_ms': 5060.0,
    }
    bridge = _bridge(lambda payload, timeout_sec=None: {
        'success': True, 'message': 'motion run check complete', 'timing_ms': check_timing,
    }, logger=logger)

    result = local_motion_readiness(bridge, {'budget_sec': 6.0})

    assert result['success'] is True
    assert result['message'] == 'motion run check complete', '성공 답의 글은 그대로'
    (line,), _ = logger.warning.call_args
    assert line.startswith('[준비 확인 시간] 합계 ')
    assert '(예산 6.0 s)' in line
    for label in ('실행 컨텍스트 ', '재생 파일 ', '실행 준비 검사 왕복 '):
        assert label in line, line
    assert '[대기 0 · 파일 3210 · 재샘플 1820(새로) · 계획 5060] ms' in line
    assert '거절' not in line


def test_a_fast_ready_answer_logs_nothing(monkeypatch):
    _selection(monkeypatch)
    logger = mock.Mock()
    bridge = _bridge(lambda payload, timeout_sec=None: {'success': True, 'message': 'ok'}, logger=logger)

    assert local_motion_readiness(bridge, {'budget_sec': 6.0}) == {'success': True, 'message': 'ok'}
    logger.warning.assert_not_called()


def test_a_refusal_is_always_logged_but_a_fast_one_keeps_its_reason(monkeypatch):
    _selection(monkeypatch)
    logger = mock.Mock()
    bridge = _bridge(
        lambda payload, timeout_sec=None: {'success': False, 'message': 'motion_run_manager response timeout'},
        logger=logger,
    )

    result = local_motion_readiness(bridge, {'budget_sec': 6.0})

    assert result == {'success': False, 'message': 'motion_run_manager response timeout'}
    (line,), _ = logger.warning.call_args
    assert '실행 준비 검사 왕복 ' in line and line.endswith('거절: motion_run_manager response timeout')


def test_a_slow_refusal_carries_the_steps_in_its_reason(monkeypatch):
    _selection(monkeypatch)
    monkeypatch.setattr(coordination_bridge, 'READINESS_SLOW_LOG_MS', 50.0)
    bridge = _bridge(
        lambda payload, timeout_sec=None: {'success': False, 'message': 'motion_run_manager response timeout'},
        context_delay=0.08,
    )

    result = local_motion_readiness(bridge, {'budget_sec': 6.0})

    assert result['success'] is False
    assert result['message'].startswith('motion_run_manager response timeout · 합계 ')
    assert '실행 컨텍스트 ' in result['message'] and result['message'].endswith(' ms')


def test_a_bridge_without_a_logger_still_answers(monkeypatch):
    """시험 대역 · 로거 없는 브리지 · 답은 그대로"""
    _selection(monkeypatch)
    bridge = _bridge(lambda payload, timeout_sec=None: {'success': False, 'message': 'x'})
    assert local_motion_readiness(bridge, {'budget_sec': 6.0}) == {'success': False, 'message': 'x'}


def test_the_text_leaves_out_steps_that_did_not_run():
    line = readiness_timing_text(5230.4, 6.0, {'context_ms': 5200.0})
    assert line == '합계 5230 ms(예산 6.0 s) · 실행 컨텍스트 5200 ms'
    cached = readiness_timing_text(
        900.0, 6.0, {'check_ms': 850.0}, {'samples_ms': 3.0, 'samples_cached': True},
    )
    assert cached.endswith('실행 준비 검사 왕복 850 [재샘플 3(캐시)] ms')
