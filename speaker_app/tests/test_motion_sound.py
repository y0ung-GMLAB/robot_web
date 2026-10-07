"""애니메이션마다 다른 음원 · 시작까지 남은 초 · 수정 목록 38"""
import os
import sys
import wave
from types import SimpleNamespace

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("yaml")

import config  # noqa: E402
import state as state_module  # noqa: E402


class FakePlayer:
    def __init__(self, *_args):
        self.played = []
        self.current_file = ""
        self.state = "idle"

    def play(self, path, device):
        self.played.append(path)
        self.current_file = path
        return True

    def stop(self):
        self.current_file = ""

    def is_active(self):
        return bool(self.current_file)


class FakeTimer:
    started = []

    def __init__(self, delay, fn, args=()):
        self.delay, self.fn, self.args = delay, fn, args
        self.daemon = False

    def start(self):
        FakeTimer.started.append(self)

    def cancel(self):
        pass


def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0\0\0" * 80)


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

    def upload(name):
        tmp = sounds / ".upload.tmp"
        _wav(tmp)
        return app.add_sound(name, str(tmp))

    app.upload = upload
    return app


def _start_at(motion="", delay=0.0, cycle=1):
    return SimpleNamespace(cycle_number=cycle, motion_file_id=motion, start_delay_sec=delay)


def test_uploads_keep_every_file_and_the_first_becomes_default(app):
    assert app.upload("a.wav") == (True, "")
    assert app.upload("b.wav") == (True, "")
    assert config.list_sounds(app.cfg["audio"]["sounds_dir"]) == ["a.wav", "b.wav"]
    assert app.snapshot()["config"]["file_name"] == "a.wav"


def test_trigger_plays_the_sound_set_for_that_animation_or_the_default(app):
    app.upload("a.wav")
    app.upload("wave.wav")
    assert app.set_motion_sound("wave_01", "wave.wav") == (True, "")

    app._on_trigger(_start_at("wave_01"))
    app._on_trigger(_start_at("bow_02"))
    app._on_trigger(SimpleNamespace(cycle_number=3))        # 옛 로봇 PC(약속 번호 4) · 칸이 없다

    played = [os.path.basename(t.args[0]) for t in FakeTimer.started]
    assert played == ["wave.wav", "a.wav", "a.wav"]
    seen = [m["motion_file_id"] for m in app.snapshot()["seen_motions"]]
    assert sorted(seen) == ["bow_02", "wave_01"]


def test_start_delay_is_added_to_the_offset(app):
    app.upload("a.wav")
    app.cfg["trigger"]["offset_sec"] = 0.2
    app._on_trigger(_start_at("m", delay=1.5))
    app._on_trigger(_start_at("m", delay=-0.4, cycle=2))    # PC 1대 재생 · 이미 시작했다
    assert [round(t.delay, 2) for t in FakeTimer.started] == [1.7, 0.0]
    assert any("늦게 재생" in e["text"] for e in app.log.items())


def test_deleting_a_sound_sends_its_animations_back_to_default(app):
    app.upload("a.wav")
    app.upload("wave.wav")
    app.set_motion_sound("wave_01", "wave.wav")
    assert app.delete_sound("wave.wav") == (True, "")
    assert app.cfg["audio"]["by_motion"] == {}
    assert config.resolve_file(app.cfg, "wave_01").endswith("a.wav")
    assert app.set_motion_sound("x", "missing.wav")[0] is False
    assert app.set_default_sound("a.wav") == (True, "")


def test_mapping_survives_a_reload(app):
    app.upload("a.wav")
    app.set_motion_sound("wave_01", "a.wav")
    assert config.load()["audio"]["by_motion"] == {"wave_01": "a.wav"}


def test_presence_tells_robot_pcs_this_is_the_speaker(app):
    """같은 망 PC 표 · 스피커가 이름·주소·웹 주소를 알린다 · 핵심 요구 4"""
    import dds_listener

    class Msg:
        def __init__(self):
            self.sent_at = SimpleNamespace(sec=0, nanosec=0)

    sent = []
    listener = dds_listener.DdsListener(app.log)
    listener._presence = app._presence_info
    listener._presence_type = Msg
    listener._group_id = "test1"
    app.update_config({"pc_name": "speaker-1"})
    listener._publish_presence(SimpleNamespace(publish=sent.append), "192.168.0.20")
    msg = sent[0]
    assert (msg.pc_id, msg.role, msg.address) == ("speaker-1", "speaker", "192.168.0.20")
    assert msg.web_url == "http://192.168.0.20:8100" and msg.group_id == "test1"


def test_repo_defaults_with_relative_paths_and_local_overrides(tmp_path, monkeypatch):
    """저장소 기본값(상대 경로) 위에 이 PC 값 · 웹 저장은 local 에만 · 설치 위치와 무관"""
    (tmp_path / "speaker.yaml").write_text(
        "audio:\n  sounds_dir: sounds\n  file_path: a.wav\ndds:\n  group_id: g1\n", encoding="utf-8")
    (tmp_path / "speaker.local.yaml").write_text("dds:\n  group_id: g2\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", str(tmp_path / "speaker.yaml"))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "speaker.local.yaml"))
    cfg = config.load()
    assert cfg["audio"]["sounds_dir"] == os.path.join(config.APP_DIR, "sounds")
    assert cfg["audio"]["file_path"] == os.path.join(config.APP_DIR, "sounds", "a.wav")
    assert cfg["dds"]["group_id"] == "g2"
    config.save(cfg)
    assert "g1" in (tmp_path / "speaker.yaml").read_text(encoding="utf-8")
