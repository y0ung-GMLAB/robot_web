"""설정 로드/저장. 앱의 유일한 영속 상태."""
import copy
import os
import threading

import yaml

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(APP_DIR, "config", "speaker.yaml")
SOUNDS_DIR = os.path.join(APP_DIR, "sounds")

DEFAULTS = {
    "mode": "dds",                      # dds | standalone
    "dds": {"domain_id": 21, "group_id": "test1"},
    "audio": {
        "device": "plughw:1,0",
        "sounds_dir": SOUNDS_DIR,
        "file_path": "",                # 비어 있으면 sounds 폴더에서 자동 선택
    },
    "trigger": {"offset_sec": 0.0, "stop_on_motion_stop": True},
    "standalone": {"repeat": 0, "dwell_sec": 2.0},
    "web": {"host": "0.0.0.0", "port": 8100},
    "log": {"max_entries": 100},
}

_lock = threading.Lock()


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def validate(cfg):
    """범위를 벗어난 값을 바로잡는다. 잘못된 설정으로 앱이 죽지 않게 한다."""
    if cfg.get("mode") not in ("dds", "standalone"):
        cfg["mode"] = "dds"
    try:
        cfg["dds"]["domain_id"] = _clamp(int(cfg["dds"]["domain_id"]), 0, 232)
    except (TypeError, ValueError):
        cfg["dds"]["domain_id"] = DEFAULTS["dds"]["domain_id"]
    cfg["dds"]["group_id"] = str(cfg["dds"].get("group_id") or "")
    try:
        cfg["trigger"]["offset_sec"] = _clamp(float(cfg["trigger"]["offset_sec"]), -10.0, 10.0)
    except (TypeError, ValueError):
        cfg["trigger"]["offset_sec"] = 0.0
    cfg["trigger"]["stop_on_motion_stop"] = bool(cfg["trigger"].get("stop_on_motion_stop", True))
    try:
        cfg["standalone"]["repeat"] = max(0, int(cfg["standalone"]["repeat"]))
    except (TypeError, ValueError):
        cfg["standalone"]["repeat"] = 0
    try:
        cfg["standalone"]["dwell_sec"] = _clamp(float(cfg["standalone"]["dwell_sec"]), 0.0, 3600.0)
    except (TypeError, ValueError):
        cfg["standalone"]["dwell_sec"] = 2.0
    try:
        cfg["log"]["max_entries"] = _clamp(int(cfg["log"]["max_entries"]), 10, 1000)
    except (TypeError, ValueError):
        cfg["log"]["max_entries"] = 100
    cfg["audio"]["device"] = str(cfg["audio"].get("device") or DEFAULTS["audio"]["device"])
    cfg["audio"]["sounds_dir"] = str(cfg["audio"].get("sounds_dir") or SOUNDS_DIR)
    cfg["audio"]["file_path"] = str(cfg["audio"].get("file_path") or "")
    return cfg


def load():
    with _lock:
        raw = {}
        if os.path.isfile(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            except Exception:
                raw = {}
        return validate(_merge(DEFAULTS, raw))


def save(cfg):
    with _lock:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, CONFIG_PATH)


def list_sounds(sounds_dir):
    """폴더 안의 wav 파일 목록 (이름순)."""
    try:
        names = [n for n in os.listdir(sounds_dir) if n.lower().endswith(".wav")]
    except OSError:
        return []
    return sorted(names)


def resolve_file(cfg):
    """실제로 재생할 파일 경로. 지정이 없거나 사라졌으면 폴더에서 자동 선택."""
    sounds_dir = cfg["audio"]["sounds_dir"]
    path = cfg["audio"]["file_path"]
    if path and os.path.isfile(path):
        return path
    names = list_sounds(sounds_dir)
    if len(names) >= 1:
        return os.path.join(sounds_dir, names[0])
    return ""
