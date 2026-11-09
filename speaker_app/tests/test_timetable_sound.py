"""시간표 재생 · 스피커도 같은 시간표로 음원 · 수정 목록 186 (2026-11-09)"""
import json
import os
import sys
from datetime import datetime

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("yaml")

from timetable_follow import TimetableFollower, next_cycle, timeline  # noqa: E402
from test_motion_sound import FakeTimer, app  # noqa: E402,F401  (app = 픽스처)


def _ts(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp()


WINDOW = [_ts("2026-11-09 10:00:00"), _ts("2026-11-09 18:00:00")]


def _body(**fields):
    body = {
        "version": 3, "issued_by": "floating1", "mode": "clock", "auto_period_sec": 930.0,
        "start_lead_sec": 60.0, "schedule_enabled": True, "windows": [WINDOW],
        "playlist": ["a.json", "b.json"], "stop": {},
    }
    body.update(fields)
    return body


def test_the_speaker_computes_the_same_cycle_times_as_the_robots():
    now = _ts("2026-11-09 13:00:00")
    plan = timeline(_body(), now)
    assert plan[0] == "tt-s%d" % int(WINDOW[0]) and plan[1] == _ts("2026-11-09 10:01:00")
    cycle, start = next_cycle(plan, now)
    assert start == plan[1] + (cycle - 1) * 930.0 and start >= now


def test_signal_mode_and_a_stop_give_nothing_to_play():
    now = _ts("2026-11-09 13:00:00")
    assert timeline(_body(mode="lockstep"), now) is None
    plan_id = "tt-s%d" % int(WINDOW[0])
    assert timeline(_body(stop={"plan_id": plan_id, "mode": "now"}), now) == ("stopped", plan_id)


def test_with_the_master_in_manual_only_a_stop_now_is_followed(tmp_path):
    """마스터 수동 · 사람이 누른 그룹 재생은 신호 재생(start_at) · 시간표는 쉬고 눈금 잇기(178)가 맡는다 · 2026-11-09"""
    now = _ts("2026-11-09 13:00:00")
    assert timeline(_body(schedule_enabled=False), now) is None
    assert timeline(_body(schedule_enabled=False, stop={"plan_id": "tt-s5", "mode": "now"}), now) == ("stopped", "tt-s5")
    follower = TimetableFollower(str(tmp_path / "timetable.local.json"))
    follower.update(3, json.dumps(_body(schedule_enabled=False)), "floating1")
    assert follower.clock() and not follower.active(now)
    follower.update(4, json.dumps(_body(version=4)), "floating1")
    assert follower.active(now)


def test_the_follower_keeps_the_highest_version_on_disk(tmp_path):
    path = str(tmp_path / "timetable.local.json")
    follower = TimetableFollower(path)
    assert follower.update(3, json.dumps(_body()), "floating1")
    assert not follower.update(2, json.dumps(_body(version=2, period_sec=2000.0)), "floating1")
    assert TimetableFollower(path).snapshot()["version"] == 3, '다시 켜도 남는다'


def test_the_app_plays_the_cycle_sound_at_the_timetable_time(app, tmp_path):
    app.cfg["mode"] = "dds"
    app.upload("a.wav")
    app.timetable = TimetableFollower(str(tmp_path / "t.json"))
    app.timetable.update(3, json.dumps(_body()), "floating1")
    plan = timeline(_body(), _ts("2026-11-09 13:00:00"))
    cycle, start = next_cycle(plan, _ts("2026-11-09 13:00:00"))
    started = len(FakeTimer.started)
    assert app._timetable_tick(wall=start - 5.0) is True
    assert len(FakeTimer.started) == started, '아직 이르다'
    app._timetable_tick(wall=start - 1.0)
    assert len(FakeTimer.started) == started + 1
    assert FakeTimer.started[-1].delay == pytest.approx(1.0, abs=0.01)
    app._timetable_tick(wall=start - 0.5)
    assert len(FakeTimer.started) == started + 1, '같은 회차는 한 번만'
    assert app.last_trigger["motion_file_id"] == ["a.json", "b.json"][(cycle - 1) % 2]
    assert app.follower.snapshot() is None, '신호 재생 눈금 잇기에는 넣지 않는다'


def test_stop_now_silences_the_sound(app, tmp_path):
    app.cfg["mode"] = "dds"
    app.upload("a.wav")
    app.timetable = TimetableFollower(str(tmp_path / "t.json"))
    app.timetable.update(3, json.dumps(_body()), "floating1")
    plan = timeline(_body(), _ts("2026-11-09 13:00:00"))
    _cycle, start = next_cycle(plan, _ts("2026-11-09 13:00:00"))
    app._timetable_tick(wall=start - 1.0)
    FakeTimer.started[-1].fn(*FakeTimer.started[-1].args)
    assert app.player.is_active()
    app.timetable.update(4, json.dumps(_body(version=4, stop={"plan_id": plan[0], "mode": "now"})), "floating1")
    app._timetable_tick(wall=start + 10.0)
    assert not app.player.is_active()
