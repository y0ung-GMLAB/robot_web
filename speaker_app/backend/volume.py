"""출력 볼륨 제어. ALSA 믹서(Master)를 직접 조작한다.

재생을 plughw로 하기 때문에 PulseAudio가 아니라 ALSA 믹서가 실제 음량을 결정한다.
"""
import re
import subprocess

CONTROL = "Master"


def _card(device):
    match = re.search(r"hw:(\d+)", device or "")
    return match.group(1) if match else "1"


def get(device):
    try:
        out = subprocess.run(["amixer", "-c", _card(device), "sget", CONTROL],
                             capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return None
    match = re.search(r"\[(\d+)%\]", out)
    if not match:
        return None
    return {"percent": int(match.group(1)), "muted": "[off]" in out}


def set_percent(device, percent):
    try:
        percent = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        return False, "볼륨 값이 올바르지 않습니다"
    try:
        result = subprocess.run(
            ["amixer", "-c", _card(device), "sset", CONTROL, "%d%%" % percent, "unmute"],
            capture_output=True, text=True, timeout=3)
    except Exception as exc:
        return False, "볼륨 조절 실패: %s" % exc
    if result.returncode != 0:
        return False, "볼륨 조절 실패: %s" % result.stderr.strip()[:100]
    return True, ""
