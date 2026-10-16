"""재생 전 음원 준비.

모노 wav를 plughw로 스테레오 장치에 보내면 한쪽 채널로만 나간다.
그래서 모노 파일은 좌우 동일한 스테레오로 변환한 캐시를 만들어 재생한다.
변환 결과는 원본 옆 숨김 폴더에 캐시되며, 원본은 건드리지 않는다.
"""
import os
import wave

try:
    import audioop
except ImportError:      # 3.13+ 대비
    audioop = None

CACHE_DIRNAME = ".stereo_cache"


def _cache_path(path):
    return os.path.join(os.path.dirname(path), CACHE_DIRNAME, os.path.basename(path))


def _to_stereo_bytes(frames, sampwidth):
    if audioop is not None:
        return audioop.tostereo(frames, sampwidth, 1, 1)
    out = bytearray()
    for i in range(0, len(frames), sampwidth):
        sample = frames[i:i + sampwidth]
        out += sample
        out += sample
    return bytes(out)


def channels_of(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnchannels()
    except Exception:
        return 0


def ensure_stereo(path, logbuf=None):
    """재생에 쓸 경로를 돌려준다. 모노면 변환 캐시 경로, 아니면 원본 경로."""
    if not path or not os.path.isfile(path):
        return path
    try:
        with wave.open(path, "rb") as w:
            if w.getnchannels() != 1:
                return path
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()
    except Exception:
        return path      # wav로 못 읽으면 원본 그대로 aplay에 맡긴다

    # 캐시가 최신이면 파일 본문을 읽지 않고 바로 돌려준다
    cached = _cache_path(path)
    try:
        if (os.path.isfile(cached)
                and os.path.getmtime(cached) >= os.path.getmtime(path)):
            return cached
        with wave.open(path, "rb") as w:
            frames = w.readframes(w.getnframes())
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        tmp = cached + ".tmp"
        with wave.open(tmp, "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(sampwidth)
            out.setframerate(framerate)
            out.writeframes(_to_stereo_bytes(frames, sampwidth))
        os.replace(tmp, cached)
        if logbuf is not None:
            logbuf.add("모노 음원을 스테레오로 변환했습니다 (양쪽 출력)")
        return cached
    except Exception as exc:
        if logbuf is not None:
            logbuf.add("스테레오 변환 실패, 원본으로 재생합니다: %s" % exc)
        return path


# ---- 구간 재생 ------------------------------------------------------
# 로봇 PC 가 「구간 1:20~1:45」 로 시작하면 음원도 그 시각부터 그 길이만큼 튼다 (2026-10-16).
# aplay 는 시작 위치를 고를 수 없다 → 그 구간만 담은 wav 를 만들어 aplay 에 그대로 준다 ·
# 파일 이름은 원본 그대로(재생 중 음원 판정이 이름을 본다) · 폴더가 구간마다 다르다 ·
# 마지막 구간 하나만 남긴다(디스크가 쌓이지 않게).
SEGMENT_DIRNAME = ".segment_cache"


def format_time(seconds):
    """`80` → `1:20` · `80.5` → `1:20.5` · 로봇 PC 화면 글과 같은 모양"""
    tenths = int(round(max(float(seconds or 0.0), 0.0) * 10.0))
    minutes, rest = divmod(tenths, 600)
    whole, tenth = divmod(rest, 10)
    return "%d:%02d%s" % (minutes, whole, (".%d" % tenth) if tenth else "")


def segment_label(start_sec, end_sec):
    """`구간 1:20~1:45` · 끝 0 = `구간 1:20~끝` · 구간이 없으면 빈 글자"""
    start = max(float(start_sec or 0.0), 0.0)
    end = max(float(end_sec or 0.0), 0.0)
    if start <= 0.0 and end <= 0.0:
        return ""
    return "구간 %s~%s" % (format_time(start), format_time(end) if end > 0.0 else "끝")


def _segment_root(path):
    folder = os.path.dirname(path)
    if os.path.basename(folder) == CACHE_DIRNAME:      # 스테레오 변환본이면 원래 음원 폴더
        folder = os.path.dirname(folder)
    return os.path.join(folder, SEGMENT_DIRNAME)


def _clear_other_segments(root, keep):
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        folder = os.path.join(root, name)
        if name == keep or not os.path.isdir(folder):
            continue
        try:
            items = os.listdir(folder)
        except OSError:
            continue
        for item in items:
            try:
                os.remove(os.path.join(folder, item))
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


def segment_path(path, start_sec, end_sec, logbuf=None):
    """구간만 담은 wav 경로 · 구간이 없으면 원본 · 못 만들면 빈 글자(재생하지 않음 · 처음부터 틀면 어긋난다)

    `start_sec` · 음원 시각(초) · `end_sec` · 0 이면 끝까지 · 음원이 구간 시작보다 짧으면 빈 글자.
    """
    start = max(float(start_sec or 0.0), 0.0)
    end = max(float(end_sec or 0.0), 0.0)
    if start <= 0.0 and end <= 0.0:
        return path
    if not path or not os.path.isfile(path):
        return path
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate() or 1
            total = w.getnframes()
            params = w.getparams()
            first = int(round(start * rate))
            last = total if end <= 0.0 else min(total, int(round(end * rate)))
            if first >= total or last <= first:
                if logbuf is not None:
                    logbuf.add("음원 %s 길이 %s 가 %s 보다 짧아 재생하지 않습니다"
                               % (os.path.basename(path), format_time(total / float(rate)),
                                  segment_label(start, end)))
                return ""
            key = "%d_%d" % (int(round(start * 1000)), int(round(end * 1000)))
            root = _segment_root(path)
            out = os.path.join(root, key, os.path.basename(path))
            if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(path):
                return out
            w.setpos(first)
            frames = w.readframes(last - first)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".tmp"
        with wave.open(tmp, "wb") as dst:
            dst.setnchannels(params.nchannels)
            dst.setsampwidth(params.sampwidth)
            dst.setframerate(params.framerate)
            dst.writeframes(frames)
        os.replace(tmp, out)
        _clear_other_segments(root, key)
        return out
    except Exception as exc:  # noqa: BLE001 · 깨진 wav · 디스크 · 무엇이든 틀지 않고 로그만(트리거 스레드가 죽지 않게)
        if logbuf is not None:
            logbuf.add("구간 음원 만들기 실패, 재생하지 않습니다: %s" % exc)
        return ""
