"""정지 신호 · 사건 이름 · 실행 번호 · 진행 PC 로 판정 · 수정 목록 146

실물 2026-10-15 floating4 (W-A5 · W-A10) · 그룹 즉시 정지에 소리가 안 멈추고, 다음 그룹 시작의 `ready`
사건에 실린 낡은 `state=stopped` 로 새 소리가 끊겼다 · 전에는 사건의 `state` 만 봤다.
"""
import os
import sys
from types import SimpleNamespace

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("yaml")

import dds_listener  # noqa: E402
from test_motion_sound import FakeTimer, app  # noqa: E402,F401  (app = 픽스처)


def _start_at(execution="exec-1", coordinator="floating4", cycle=1, motion="m"):
    return SimpleNamespace(cycle_number=cycle, motion_file_id=motion, start_delay_sec=0.0,
                           execution_id=execution, coordinator_id=coordinator)


def _event(event, execution="exec-1", pc="floating4", state=None, group="test1"):
    return SimpleNamespace(group_id=group, event=event, execution_id=execution, pc_id=pc,
                           state=event if state is None else state)


def _playing(app, **kwargs):
    app.upload("a.wav")
    app._on_trigger(_start_at(**kwargs))
    timer = FakeTimer.started[-1]
    timer.fn(*timer.args)          # 예약 시각이 됐다 · 재생
    assert app.player.is_active()


def _stopped_log(app):
    return [e["text"] for e in app.log.items() if "정지 신호 수신" in e["text"]]


class _Listener(dds_listener.DdsListener):
    def __init__(self):
        super().__init__(SimpleNamespace(add=lambda _text: None))
        self._group_id = "test1"
        self.passed = []
        self._on_stop = self.passed.append


# ---- 리스너 · 사건 이름만 거른다 ----------------------------------------------------------- #

def test_listener_decides_on_the_event_name_not_the_cached_state():
    listener = _Listener()
    listener._on_event(_event("ready", state="stopped"))        # 다음 실행 준비에 실린 낡은 상태
    listener._on_event(_event("armed", state="error"))
    listener._on_event(_event("motion_completed", state="stopped"))
    listener._on_event(_event("stopped", group="other"))
    assert listener.passed == []
    for name in ("stopped", "error", "solo_stopped"):
        listener._on_event(_event(name, state="running"))       # 사건이 정지면 상태 칸은 아무래도 좋다
    assert [m.event for m in listener.passed] == ["stopped", "error", "solo_stopped"]


# ---- 받는 쪽 · 지금 소리를 내는 실행의 정지만 ------------------------------------------------- #

def test_stale_stopped_state_on_the_next_ready_does_not_cut_the_new_sound(app):
    _playing(app, execution="exec-2")
    listener = _Listener()
    listener._on_stop = app._on_stop
    listener._on_event(_event("ready", execution="exec-2", state="stopped"))
    assert app.player.is_active()
    assert _stopped_log(app) == []


def test_a_late_stop_for_the_previous_execution_is_ignored(app):
    """W-A5 · 18:06 의 정지가 18:07 다음 시작 때 늦게 와서 새 소리를 끊었다"""
    _playing(app, execution="exec-2")
    app._on_stop(_event("stopped", execution="exec-1"))
    assert app.player.is_active()


def test_a_stop_for_another_execution_keeps_the_pending_start(app):
    """새 시작의 예약 타이머를 엉뚱한 정지가 지우지 않는다"""
    app.upload("a.wav")
    app._on_trigger(_start_at(execution="exec-2"))
    cancelled = []
    app._timer.cancel = lambda: cancelled.append(True)
    app._on_stop(_event("stopped", execution="exec-1"))
    assert cancelled == [] and app._timer is not None


def test_the_matching_stop_from_the_coordinator_stops_once(app):
    _playing(app, execution="exec-2")
    app._on_stop(_event("stopped", execution="exec-2"))
    assert not app.player.is_active()
    app.player.current_file = "x.wav"                              # 같은 정지가 또 와도(3대 · 진행 PC) 1회
    app._on_stop(_event("stopped", execution="exec-2"))
    assert app.player.is_active()
    assert _stopped_log(app) == ["모션 정지 신호 수신 (stopped) → 재생 정지"]


def test_an_error_event_of_that_execution_also_stops(app):
    _playing(app, execution="exec-2")
    app._on_stop(_event("error", execution="exec-2"))
    assert not app.player.is_active()


def test_a_matching_stop_before_the_sound_starts_cancels_the_pending_start(app):
    app.upload("a.wav")
    app._on_trigger(_start_at(execution="exec-2"))
    cancelled = []
    app._timer.cancel = lambda: cancelled.append(True)
    app._on_stop(_event("stopped", execution="exec-2"))
    assert cancelled == [True]
    assert _stopped_log(app) == ["모션 정지 신호 수신 (stopped) → 재생 예약 취소"]


def test_a_participant_dropping_out_does_not_stop_the_group_sound(app):
    """빠진 PC 의 풀기 답 · 복귀 실패도 같은 실행 번호로 `stopped` 를 낸다 · 나머지는 계속 돈다"""
    _playing(app, execution="exec-2", coordinator="floating4")
    app._on_stop(_event("stopped", execution="exec-2", pc="floating2"))
    app._on_stop(_event("error", execution="exec-2", pc="floating3"))
    assert app.player.is_active()


def test_solo_stopped_still_stops_a_single_pc_run(app):
    """PC 1대 재생 · 시작은 `solo-<pc>-<ms>` · 정지는 `solo-<pc>` (수정 목록 38-3)"""
    _playing(app, execution="solo-floating4-1760500000123", coordinator="floating4")
    app._on_stop(_event("solo_stopped", execution="solo-floating2", pc="floating2"))
    assert app.player.is_active(), "다른 PC 의 단독 정지"
    app._on_stop(_event("solo_stopped", execution="solo-floating4", pc="floating4", state="stopped"))
    assert not app.player.is_active()


def test_a_completed_cycle_keeps_the_sound(app):
    """정상 회차 끝은 소리를 그대로 둔다(DESIGN.md · 정지 신호 수신) · 다음 회차 start_at 이 처음부터"""
    _playing(app, execution="exec-2")
    listener = _Listener()
    listener._on_stop = app._on_stop
    listener._on_event(_event("motion_completed", execution="exec-2", state="completed"))
    listener._on_event(_event("cycle_initialized", execution="exec-2", state="stopped"))
    assert app.player.is_active()


def test_nothing_to_stop_before_any_start(app):
    app.upload("a.wav")
    app.test_play()
    app._on_stop(_event("stopped"))
    assert app.player.is_active(), "시작을 받은 적이 없으면 테스트 재생은 그대로"
