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
