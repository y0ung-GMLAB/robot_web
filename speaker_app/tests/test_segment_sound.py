"""구간 재생 · 로봇이 애니메이션 1:20 부터 돌면 음원도 1:20 부터 · 끝이 있으면 그 길이만큼 (약속 번호 10 · 2026-10-16)"""
import os
import struct
import sys
import wave
from types import SimpleNamespace

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("yaml")

import audio_prep  # noqa: E402
import config  # noqa: E402
import state as state_module  # noqa: E402
from test_motion_sound import FakePlayer, FakeTimer  # noqa: E402

RATE = 100   # 1 초 = 100 프레임 · 프레임 값 = 번호(16비트 스테레오 양쪽)


def _counting_wav(path, seconds=5, channels=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<" + "h" * channels, *([i] * channels))
                               for i in range(seconds * RATE)))


def _frames(path):
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        data = w.readframes(w.getnframes())
    values = struct.unpack("<%dh" % (len(data) // 2), data)
    return list(values[::channels])


def test_no_segment_keeps_the_original_file(tmp_path):
    src = tmp_path / "a.wav"
    _counting_wav(src)
    assert audio_prep.segment_path(str(src), 0, 0) == str(src)


def test_segment_file_starts_at_the_offset_and_stops_at_the_end(tmp_path):
    src = tmp_path / "a.wav"
    _counting_wav(src)
    out = audio_prep.segment_path(str(src), 1.2, 2.5)
    assert os.path.basename(out) == "a.wav", "재생 중 음원 판정이 이름을 본다"
    assert os.path.dirname(os.path.dirname(out)) == str(tmp_path / audio_prep.SEGMENT_DIRNAME)
    frames = _frames(out)
    assert frames[0] == 120 and frames[-1] == 249 and len(frames) == 130

    to_end = _frames(audio_prep.segment_path(str(src), 4.0, 0))
    assert to_end[0] == 400 and to_end[-1] == 499
    longer = _frames(audio_prep.segment_path(str(src), 4.0, 9.0))
    assert longer == to_end, "끝이 음원보다 길면 끝까지"


def test_only_the_last_segment_stays_on_disk(tmp_path):
    src = tmp_path / "a.wav"
    _counting_wav(src)
    first = audio_prep.segment_path(str(src), 1.0, 2.0)
    second = audio_prep.segment_path(str(src), 2.0, 3.0)
    assert not os.path.exists(first) and os.path.exists(second)
    assert audio_prep.segment_path(str(src), 2.0, 3.0) == second   # 같은 구간이면 다시 만들지 않는다


def test_stereo_cache_input_goes_to_the_sounds_folder(tmp_path):
    src = tmp_path / "m.wav"
    _counting_wav(src, channels=1)
    stereo = audio_prep.ensure_stereo(str(src))
    out = audio_prep.segment_path(stereo, 1.0, 0)
    assert out.startswith(str(tmp_path / audio_prep.SEGMENT_DIRNAME))
    assert _frames(out)[0] == 100


def test_a_sound_shorter_than_the_segment_start_is_not_played(tmp_path):
    src = tmp_path / "a.wav"
    _counting_wav(src, seconds=2)
    logs = []
    log = SimpleNamespace(add=logs.append)
    assert audio_prep.segment_path(str(src), 3.0, 0, log) == ""
    assert "짧아 재생하지 않습니다" in logs[0] and "구간 0:03~끝" in logs[0]


def test_labels_match_the_robot_screen():
    assert audio_prep.segment_label(80, 105) == "구간 1:20~1:45"
    assert audio_prep.segment_label(80.5, 0) == "구간 1:20.5~끝"
    assert audio_prep.segment_label(0, 0) == ""


@pytest.fixture
def app(tmp_path, monkeypatch):
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "speaker.local.yaml"))
    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", str(tmp_path / "speaker.yaml"))
    monkeypatch.setitem(config.DEFAULTS["audio"], "sounds_dir", str(sounds))
    monkeypatch.setattr(state_module, "Player", FakePlayer)
    monkeypatch.setattr(state_module.sysinfo, "collect", lambda _port: {})
    monkeypatch.setattr(state_module.threading, "Timer", FakeTimer)
    FakeTimer.started = []
    app = state_module.AppState()
    tmp = sounds / ".upload.tmp"
    _counting_wav(tmp)
    assert app.add_sound("show.wav", str(tmp)) == (True, "")
    return app


def _start_at(delay=1.5, **segment):
    return SimpleNamespace(cycle_number=1, motion_file_id="show_a", start_delay_sec=delay, **segment)


def test_trigger_with_a_segment_plays_from_the_offset_at_the_same_moment(app):
    app.cfg["trigger"]["offset_sec"] = 0.2
    app._on_trigger(_start_at(segment_start_sec=1.0, segment_end_sec=2.0))
    [timer] = FakeTimer.started
    assert round(timer.delay, 2) == 1.7, "시작 시각 계산은 그대로(start_delay + 오프셋)"
    frames = _frames(timer.args[0])
    assert frames[0] == 100 and len(frames) == 100, "1 초 뒤 멈춘다(끝 − 시작)"
    assert any("구간 0:01~0:02" in entry["text"] for entry in app.log.items())
    assert app.snapshot()["last_trigger"]["segment"] == "구간 0:01~0:02"

    timer.fn(*timer.args)          # 시각이 되면 그 파일을 그대로 튼다
    assert os.path.basename(app.player.played[-1]) == "show.wav"
    assert _frames(app.player.played[-1])[0] == 100


def test_old_robot_pcs_without_the_fields_play_the_whole_sound(app):
    app._on_trigger(_start_at())
    [timer] = FakeTimer.started
    assert timer.args[0].endswith(os.path.join("sounds", "show.wav"))


def test_a_segment_past_the_sound_end_plays_nothing(app):
    app._on_trigger(_start_at(segment_start_sec=30.0, segment_end_sec=0.0))
    assert FakeTimer.started == []
    assert any("짧아 재생하지 않습니다" in entry["text"] for entry in app.log.items())
