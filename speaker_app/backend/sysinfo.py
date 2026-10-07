"""시스템 기본 정보 수집. 웹 UI 표시용이며 앱 동작에는 관여하지 않는다."""
import os
import platform
import socket
import subprocess
import time
import wave

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lan_ip():
    """기본 경로로 나가는 인터페이스의 주소. 실제 패킷은 보내지 않는다."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _iface():
    try:
        out = subprocess.run(["ip", "route", "get", "8.8.8.8"],
                             capture_output=True, text=True, timeout=2).stdout
        parts = out.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    except Exception:
        pass
    return "-"


_net_cache = {"at": 0.0, "value": ("127.0.0.1", "-")}
NET_CACHE_SEC = 5.0


def network(force=False):
    """현재 기본 경로의 (IP, 인터페이스). 없으면 ("127.0.0.1", "-").

    상태 폴링이 1초 주기이므로 ip 명령을 매번 띄우지 않도록 잠깐 캐시한다.
    """
    now = time.time()
    if not force and now - _net_cache["at"] < NET_CACHE_SEC:
        return _net_cache["value"]
    value = (_lan_ip(), _iface())
    _net_cache["at"] = now
    _net_cache["value"] = value
    return value


def network_ready(force=False):
    """DDS가 붙을 수 있는 네트워크가 있는지. loopback만 있으면 False."""
    ip, iface = network(force)
    return iface != "-" and not ip.startswith("127.")


def _git_url():
    """저장소 원격 주소. 앱 동작에는 관여하지 않으며 표시용이다."""
    try:
        out = subprocess.run(["git", "-C", APP_DIR, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=2)
        if out.returncode != 0:
            return "-"
        url = out.stdout.strip()
    except Exception:
        return "-"
    if not url:
        return "-"
    # SSH 형식(git@host:owner/repo)을 브라우저로 열 수 있는 형태로 바꾼다
    if url.startswith("git@"):
        host, _, path = url[4:].partition(":")
        url = "https://%s/%s" % (host, path)
    if url.endswith(".git"):
        url = url[:-4]
    return url


def _git_head():
    """현재 체크아웃된 커밋. 배포된 버전을 확인할 때 쓴다."""
    try:
        out = subprocess.run(["git", "-C", APP_DIR, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=2)
        if out.returncode != 0:
            return "-"
        head = out.stdout.strip()
        if not head:
            return "-"
        dirty = subprocess.run(["git", "-C", APP_DIR, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=3)
        if dirty.returncode == 0 and dirty.stdout.strip():
            head += " (커밋 안 된 수정 있음)"
        return head
    except Exception:
        return "-"


_head_cache = {"value": None}


def git_head():
    """커밋 해시. 값은 캐시하고, 페이지를 새로 열 때만 다시 읽는다.
    프론트가 1초마다 폴링하므로 매번 git을 부르지 않는다."""
    if _head_cache["value"] is None:
        _head_cache["value"] = _git_head()
    return _head_cache["value"]


def invalidate_head():
    """다음 조회 때 커밋 해시를 다시 읽게 한다. 페이지 로드 시 호출된다."""
    _head_cache["value"] = None


def _format_duration(seconds):
    seconds = int(seconds)
    if seconds >= 3600:
        return "%d시간 %d분 %d초" % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    if seconds >= 60:
        return "%d분 %d초" % (seconds // 60, seconds % 60)
    return "%d초" % seconds


def format_duration(seconds):
    return _format_duration(seconds)


def wav_info(path):
    """음원 길이/포맷. 사이클 주기와 비교할 때 쓰인다."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with wave.open(path, "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 1
            info = {
                "duration_sec": frames / float(rate),
                "duration_text": _format_duration(frames / float(rate)),
                "sample_rate": rate,
                "channels": w.getnchannels(),
                "bit_depth": w.getsampwidth() * 8,
            }
    except Exception as exc:
        return {"error": str(exc)}
    try:
        info["size_mb"] = round(os.path.getsize(path) / (1024 * 1024), 1)
    except OSError:
        info["size_mb"] = 0
    return info


def collect(port):
    """앱 기동 시 한 번만 모으면 되는 정보."""
    ip = _lan_ip()
    return {
        "hostname": socket.gethostname(),
        "web_url": "http://%s:%d" % (ip, port),
        "ip": ip,
        "interface": _iface(),
        "app_dir": APP_DIR,
        "config_path": os.path.join(APP_DIR, "config", "speaker.yaml"),
        "sounds_dir": os.path.join(APP_DIR, "sounds"),
        "ros_workspace": os.path.expanduser("~/ros2_ws"),
        "ros_distro": os.environ.get("ROS_DISTRO", "-"),
        "rmw": os.environ.get("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp (기본값)"),
        "os": "%s %s" % (platform.system(), platform.release()),
        "python": platform.python_version(),
        "git_url": _git_url(),
        "git_head": git_head(),
        "subscribe": "/motion_group/command, /motion_group/event",
        "publish": "없음 (구독 전용)",
    }
