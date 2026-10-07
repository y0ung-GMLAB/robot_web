"""설정 로드/저장. 앱의 유일한 영속 상태.

두 파일 · `config/speaker.yaml`(저장소 · 기본값) 위에 `config/speaker.local.yaml`(이 PC · 저장소 밖)을 덮는다 ·
웹에서 바꾼 값은 local 에만 쓴다 · 그래서 `git pull` 이 이 PC 설정과 부딪히지 않는다.
경로는 상대로 적어도 된다 · sounds_dir 는 앱 폴더 기준 · file_path 는 sounds_dir 기준.
"""
import copy
import os
import threading

import yaml

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(APP_DIR, "config", "speaker.yaml")
CONFIG_PATH = os.path.join(APP_DIR, "config", "speaker.local.yaml")
SOUNDS_DIR = os.path.join(APP_DIR, "sounds")

DEFAULTS = {
    "mode": "dds",                      # dds | standalone
    # pc_name · 로봇 PC 화면 「같은 망 PC」 표에 보이는 이름
    "dds": {"domain_id": 21, "group_id": "test1", "pc_name": "speaker"},
    "audio": {
        "device": "plughw:1,0",
        "sounds_dir": SOUNDS_DIR,
        "file_path": "",                # 기본 음원 · 비어 있으면 sounds 폴더에서 자동 선택
        "by_motion": {},                # 애니메이션(motion_file_id) → 음원 파일 이름 · 없으면 기본 음원
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
    name = str(cfg["dds"].get("pc_name") or "").strip()[:64]
    cfg["dds"]["pc_name"] = name or "speaker"
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
    sounds_dir = str(cfg["audio"].get("sounds_dir") or SOUNDS_DIR)
    cfg["audio"]["sounds_dir"] = os.path.normpath(os.path.join(APP_DIR, sounds_dir))
    file_path = str(cfg["audio"].get("file_path") or "")
    cfg["audio"]["file_path"] = (
        os.path.join(cfg["audio"]["sounds_dir"], file_path) if file_path else "")
    by_motion = cfg["audio"].get("by_motion")
    cfg["audio"]["by_motion"] = {
        str(motion): os.path.basename(str(name))
        for motion, name in (by_motion.items() if isinstance(by_motion, dict) else [])
        if str(motion) and str(name or "")
    }
    return cfg


def _read(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def load():
    with _lock:
        merged = _merge(_merge(DEFAULTS, _read(DEFAULT_CONFIG_PATH)), _read(CONFIG_PATH))
        return validate(merged)


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


def resolve_file(cfg, motion_file_id=""):
    """실제로 재생할 파일 경로.

    애니메이션에 정해 둔 음원이 있으면 그것 · 없거나 사라졌으면 기본 음원 ·
    기본도 없으면 폴더에서 이름순 첫 파일.
    """
    sounds_dir = cfg["audio"]["sounds_dir"]
    mapped = cfg["audio"].get("by_motion", {}).get(str(motion_file_id or ""), "")
    if mapped:
        mapped_path = os.path.join(sounds_dir, mapped)
        if os.path.isfile(mapped_path):
            return mapped_path
    path = cfg["audio"]["file_path"]
    if path and os.path.isfile(path):
        return path
    names = list_sounds(sounds_dir)
    if len(names) >= 1:
        return os.path.join(sounds_dir, names[0])
    return ""
