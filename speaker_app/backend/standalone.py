"""단독 모드 반복 스케줄러. 재생이 끝나면 간격만큼 쉬고 다시 재생한다."""
import threading


class Standalone:
    def __init__(self, player, logbuf):
        self._player = player
        self._log = logbuf
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def is_running(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, file_path, device, repeat, dwell_sec):
        self.stop()
        self._stop = threading.Event()
        args = (file_path, device, int(repeat), float(dwell_sec), self._stop)
        with self._lock:
            self._thread = threading.Thread(target=self._run, args=args, daemon=True)
            self._thread.start()
        label = "무한 반복" if int(repeat) == 0 else "%d회 반복" % int(repeat)
        self._log.add("단독 재생 시작 (%s, 간격 %.1f초)" % (label, float(dwell_sec)))

    def stop(self):
        self._stop.set()
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    def _run(self, file_path, device, repeat, dwell_sec, stop_event):
        count = 0
        while not stop_event.is_set():
            if not self._player.play(file_path, device):
                break
            # 재생이 끝날 때까지 대기 (일시정지 중이면 계속 대기)
            while not stop_event.is_set() and self._player.is_active():
                stop_event.wait(0.1)
            if stop_event.is_set():
                break
            count += 1
            if repeat and count >= repeat:
                self._log.add("단독 재생 완료 (%d회)" % count)
                break
            if stop_event.wait(dwell_sec):
                break
