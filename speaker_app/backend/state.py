"""앱 상태의 단일 소스. 각 모듈을 조립하고 스레드 간 공유 상태를 관리한다."""
import os
import shutil
import threading
import time
from collections import deque

import wave

import audio_prep
import config
import sysinfo
import volume
from dds_listener import DdsListener
from logbuf import LogBuffer
from player import Player
from standalone import Standalone

MODE_DDS = "dds"
MODE_STANDALONE = "standalone"


class AppState:
    def __init__(self):
        self.cfg = config.load()
        self.log = LogBuffer(self.cfg["log"]["max_entries"])
        self.player = Player(self.log)
        self.standalone = Standalone(self.player, self.log)
        self.dds = DdsListener(self.log)
        self.last_trigger = None
        self.started_at = time.time()
        self.trigger_count = 0
        self._trigger_times = deque(maxlen=20)
        self.system = sysinfo.collect(int(self.cfg["web"]["port"]))
        self._lock = threading.Lock()
        self._timer = None

    # ---- 수명주기 ---------------------------------------------------
    def startup(self):
        os.makedirs(self.cfg["audio"]["sounds_dir"], exist_ok=True)
        self.log.add("앱 시작")
        if self.cfg["mode"] == MODE_DDS:
            self._start_dds()

    def shutdown(self):
        self._cancel_timer()
        self.dds.stop()
        self.standalone.stop()
        self.player.stop()

    # ---- 모드 -------------------------------------------------------
    def set_mode(self, mode):
        if mode not in (MODE_DDS, MODE_STANDALONE):
            return False, "알 수 없는 모드입니다"
        if mode == self.cfg["mode"]:
            return True, ""
        self._cancel_timer()
        self.standalone.stop()
        self.player.stop()
        self.cfg["mode"] = mode
        config.save(self.cfg)
        if mode == MODE_DDS:
            self.log.add("연동 모드로 전환")
            self._start_dds()
        else:
            self.dds.stop()
            self.log.add("단독 모드로 전환")
        return True, ""

    def restart_dds(self):
        """웹에서 누르는 다시 연결. 부팅 시 랜이 늦어 실패한 경우의 복구 수단."""
        if self.cfg["mode"] != MODE_DDS:
            return False, "연동 모드에서만 사용할 수 있습니다"
        self.log.add("연동 다시 연결")
        self._start_dds()
        return True, ""

    # ---- 설정 -------------------------------------------------------
    def update_config(self, patch):
        cfg = self.cfg
        old_domain = cfg["dds"]["domain_id"]
        old_group = cfg["dds"]["group_id"]
        old_watch_stop = cfg["trigger"]["stop_on_motion_stop"]
        if "domain_id" in patch:
            cfg["dds"]["domain_id"] = patch["domain_id"]
        if "group_id" in patch:
            cfg["dds"]["group_id"] = patch["group_id"]
        if "offset_sec" in patch:
            cfg["trigger"]["offset_sec"] = patch["offset_sec"]
        if "stop_on_motion_stop" in patch:
            cfg["trigger"]["stop_on_motion_stop"] = patch["stop_on_motion_stop"]
        if "device" in patch:
            cfg["audio"]["device"] = patch["device"]
        if "file_name" in patch:
            name = str(patch["file_name"] or "")
            cfg["audio"]["file_path"] = (
                os.path.join(cfg["audio"]["sounds_dir"], name) if name else ""
            )
        if "repeat" in patch:
            cfg["standalone"]["repeat"] = patch["repeat"]
        if "dwell_sec" in patch:
            cfg["standalone"]["dwell_sec"] = patch["dwell_sec"]
        config.validate(cfg)
        config.save(cfg)

        if cfg["mode"] == MODE_DDS:
            if (cfg["dds"]["domain_id"] != old_domain
                    or cfg["trigger"]["stop_on_motion_stop"] != old_watch_stop):
                if cfg["dds"]["domain_id"] != old_domain:
                    self.log.add("도메인 변경 (%s → %s) — DDS 재시작"
                                 % (old_domain, cfg["dds"]["domain_id"]))
                else:
                    self.log.add("정지신호 수신 %s — DDS 재시작"
                                 % ("켜짐" if cfg["trigger"]["stop_on_motion_stop"] else "꺼짐"))
                self._start_dds()
            elif cfg["dds"]["group_id"] != old_group:
                self.dds.set_group_id(cfg["dds"]["group_id"])
                self.log.add("그룹 변경 (%s → %s)" % (old_group, cfg["dds"]["group_id"]))
        self.log.add("설정 저장")
        return True, ""

    # ---- 재생 -------------------------------------------------------
    def play_standalone(self):
        if self.cfg["mode"] != MODE_STANDALONE:
            return False, "단독 모드에서만 사용할 수 있습니다"
        path = config.resolve_file(self.cfg)
        if not path:
            return False, "sounds 폴더에 wav 파일이 없습니다"
        self.standalone.start(
            audio_prep.ensure_stereo(path, self.log),
            self.cfg["audio"]["device"],
            self.cfg["standalone"]["repeat"],
            self.cfg["standalone"]["dwell_sec"],
        )
        return True, ""

    def stop_playback(self):
        self._cancel_timer()
        self.standalone.stop()
        self.player.stop()
        return True, ""

    def pause(self):
        return (True, "") if self.player.pause() else (False, "재생 중이 아닙니다")

    def resume(self):
        return (True, "") if self.player.resume() else (False, "일시정지 상태가 아닙니다")

    def test_play(self):
        path = config.resolve_file(self.cfg)
        if not path:
            return False, "sounds 폴더에 wav 파일이 없습니다"
        self.standalone.stop()
        self.log.add("테스트 재생")
        if not self.player.play(audio_prep.ensure_stereo(path, self.log),
                                self.cfg["audio"]["device"]):
            return False, "재생에 실패했습니다 (로그 확인)"
        return True, ""

    def set_volume(self, percent):
        ok, message = volume.set_percent(self.cfg["audio"]["device"], percent)
        if ok:
            self.log.add("볼륨 %d%%" % int(percent))
        return ok, message

    # ---- 음원 파일 ---------------------------------------------------
    def _clear_sounds(self):
        """폴더에 파일 하나만 두는 규칙 — 기존 wav와 변환 캐시를 모두 지운다."""
        sounds_dir = self.cfg["audio"]["sounds_dir"]
        for name in config.list_sounds(sounds_dir):
            try:
                os.remove(os.path.join(sounds_dir, name))
            except OSError:
                pass
        shutil.rmtree(os.path.join(sounds_dir, audio_prep.CACHE_DIRNAME), ignore_errors=True)

    def replace_sound(self, name, tmp_path):
        try:
            with wave.open(tmp_path, "rb") as w:
                w.getnframes()
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False, "wav 파일이 아니거나 읽을 수 없습니다"
        self.stop_playback()
        self._clear_sounds()
        dest = os.path.join(self.cfg["audio"]["sounds_dir"], name)
        try:
            os.replace(tmp_path, dest)
        except OSError as exc:
            return False, "저장 실패: %s" % exc
        self.cfg["audio"]["file_path"] = dest
        config.save(self.cfg)
        self.log.add("음원 업로드: %s" % name)
        return True, ""

    def delete_sound(self):
        if not config.list_sounds(self.cfg["audio"]["sounds_dir"]):
            return False, "삭제할 음원이 없습니다"
        self.stop_playback()
        self._clear_sounds()
        self.cfg["audio"]["file_path"] = ""
        config.save(self.cfg)
        self.log.add("음원 삭제")
        return True, ""

    def sound_path(self):
        return config.resolve_file(self.cfg)

    # ---- 트리거 -----------------------------------------------------
    def _on_trigger(self, msg):
        cycle = int(msg.cycle_number)
        offset = float(self.cfg["trigger"]["offset_sec"])
        delay = max(0.0, offset)   # 수신보다 먼저 재생할 수는 없다
        self.last_trigger = {"cycle_number": cycle, "at": time.strftime("%H:%M:%S")}
        self.trigger_count += 1
        self._trigger_times.append(time.time())
        if delay > 0:
            self.log.add("start_at 수신 (cycle %d) → %.1f초 후 재생" % (cycle, delay))
        else:
            self.log.add("start_at 수신 (cycle %d) → 재생" % cycle)
        self._cancel_timer()
        timer = threading.Timer(delay, self._play_trigger)
        timer.daemon = True
        with self._lock:
            self._timer = timer
        timer.start()

    def _on_stop(self, msg):
        """모션 정지/오류 신호. 재생 중이었을 때만 멈춘다(3대가 보내므로 자연히 1회)."""
        self._cancel_timer()
        if not self.player.is_active():
            return
        self.player.stop()
        self.log.add("모션 정지 신호 수신 (%s) → 재생 정지" % msg.state)

    def _play_trigger(self):
        self.player.play(self._playable_path(), self.cfg["audio"]["device"])

    def _playable_path(self):
        """모노 음원은 스테레오 변환본으로 재생한다(양쪽 이어폰 출력)."""
        return audio_prep.ensure_stereo(config.resolve_file(self.cfg), self.log)

    def _cancel_timer(self):
        with self._lock:
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()

    def _start_dds(self):
        self.dds.start(
            self.cfg["dds"]["domain_id"],
            self.cfg["dds"]["group_id"],
            self._on_trigger,
            on_stop=self._on_stop,
            watch_stop=self.cfg["trigger"]["stop_on_motion_stop"],
        )

    def _stats(self):
        times = list(self._trigger_times)
        gaps = [b - a for a, b in zip(times, times[1:])]
        return {
            "uptime": sysinfo.format_duration(time.time() - self.started_at),
            "trigger_count": self.trigger_count,
            "avg_interval": round(sum(gaps) / len(gaps), 1) if gaps else None,
        }

    # ---- 스냅샷 -----------------------------------------------------
    def snapshot(self):
        cfg = self.cfg
        path = config.resolve_file(cfg)
        # 부팅 직후에는 랜이 늦게 올라와 기동 시 수집한 IP가 loopback으로 굳는다.
        # 화면에는 항상 현재 값을 보여준다.
        ip, iface = sysinfo.network()
        return {
            "mode": cfg["mode"],
            "dds_status": self.dds.status if cfg["mode"] == MODE_DDS else "off",
            "dds_error": self.dds.error,
            "dds_init": self.dds.init if cfg["mode"] == MODE_DDS else None,
            "playback": self.player.state,
            "standalone_running": self.standalone.is_running(),
            "config": {
                "domain_id": cfg["dds"]["domain_id"],
                "group_id": cfg["dds"]["group_id"],
                "offset_sec": cfg["trigger"]["offset_sec"],
                "stop_on_motion_stop": cfg["trigger"]["stop_on_motion_stop"],
                "device": cfg["audio"]["device"],
                "sounds_dir": cfg["audio"]["sounds_dir"],
                "file_name": os.path.basename(path) if path else "",
                "repeat": cfg["standalone"]["repeat"],
                "dwell_sec": cfg["standalone"]["dwell_sec"],
            },
            "files": config.list_sounds(cfg["audio"]["sounds_dir"]),
            "last_trigger": self.last_trigger,
            "system": {**self.system, "git_head": sysinfo.git_head(),
                       "ip": ip, "interface": iface,
                       "web_url": "http://%s:%d" % (ip, int(cfg["web"]["port"]))},
            "wav": sysinfo.wav_info(path),
            "stereo_converted": bool(path) and audio_prep.channels_of(path) == 1,
            "stats": self._stats(),
            "volume": volume.get(cfg["audio"]["device"]),
            "logs": self.log.items(),
        }
