"""진행 PC 가 안 보여도 회차 눈금대로 소리를 잇는다 · 수정 목록 178 (2026-11-08)

로봇은 2회차부터 「앞 시작 + 주기」(10 s 올림)에 시작하고, 진행 PC 가 안 보이면 참가 PC 가 같은 눈금으로
스스로 잇는다 · 스피커도 진행 PC 의 시작 둘로 주기를 알고, 진행 PC 하트비트가 끊기면 같은 시각에 튼다.
"""
import os
import sys
from types import SimpleNamespace

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("yaml")

from cycle_follow import MASTER_GONE_SEC, CycleFollower  # noqa: E402
from test_motion_sound import FakeTimer, app  # noqa: E402,F401  (app = 픽스처)


def _follower(period=930.0):
    follower = CycleFollower()
    context = {"motion_file_id": "m"}
    follower.record(execution_id="e", coordinator_id="f1", cycle=2, start=1000.0, context=context)
    follower.record(execution_id="e", coordinator_id="f1", cycle=3, start=1000.0 + period, context=context)
    return follower


def test_two_master_starts_teach_the_period():
    assert _follower().snapshot()["period"] == 930.0


def test_nothing_before_the_next_start_comes_near():
    follower = _follower()
    assert follower.due(now=2500.0, coordinator_age=None, others_running=True) is None


def test_while_the_master_is_seen_the_speaker_waits_for_its_command():
    follower = _follower()
    assert follower.due(now=2859.5, coordinator_age=0.4, others_running=True) is None


def test_with_the_master_gone_it_plays_on_the_grid():
    follower = _follower()
    cycle, start, context = follower.due(
        now=2859.5, coordinator_age=MASTER_GONE_SEC + 1.0, others_running=True,
    )
    assert (cycle, start, context["motion_file_id"]) == (4, 2860.0, "m")


def test_no_robot_left_playing_means_stop_following():
    follower = _follower()
    assert follower.due(now=2859.5, coordinator_age=None, others_running=False) is None
    assert follower.snapshot() is None


def test_an_autonomous_start_does_not_relearn_the_period():
    follower = _follower()
    follower.record(execution_id="e", coordinator_id="f1", cycle=4, start=1000.0 + 3 * 930.0,
                    context={}, learn=False)
    assert follower.snapshot()["period"] == 930.0


def test_a_new_execution_starts_over():
    follower = _follower()
    follower.record(execution_id="other", coordinator_id="f1", cycle=1, start=5000.0, context={})
    assert follower.snapshot()["period"] == 0.0


def test_the_app_plays_the_last_sound_when_the_master_disappears(app, monkeypatch):
    app.cfg["mode"] = "dds"
    app.upload("a.wav")
    app.dds.heartbeat_age = lambda _pc: None
    app.dds.execution_running_elsewhere = lambda _execution, _exclude: True
    base = 100.0
    for cycle, start in ((2, base), (3, base + 930.0)):
        app._on_trigger(SimpleNamespace(
            cycle_number=cycle, motion_file_id="m", start_delay_sec=0.0,
            execution_id="exec-1", coordinator_id="floating3",
        ), now=start)
    started = len(FakeTimer.started)

    app._follow_tick(now=base + 2 * 930.0 - 0.8)

    assert len(FakeTimer.started) == started + 1
    assert FakeTimer.started[-1].delay == pytest.approx(0.8, abs=0.01)
    assert any("진행 PC 안 보임 · 눈금대로 이어 감" in e["text"] for e in app.log.items())
    assert app.follower.snapshot()["period"] == 930.0


def test_a_stop_signal_forgets_the_grid(app):
    app.upload("a.wav")
    app._on_trigger(SimpleNamespace(cycle_number=2, motion_file_id="m", start_delay_sec=0.0,
                                    execution_id="exec-1", coordinator_id="floating3"))
    app._on_stop(SimpleNamespace(group_id="test1", event="stopped", execution_id="exec-1",
                                 pc_id="floating3", state="stopped"))
    assert app.follower.snapshot() is None
