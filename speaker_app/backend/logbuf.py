"""최근 N건만 유지하는 로그 링버퍼. 메모리 방식이라 재시작하면 사라진다."""
import threading
import time
from collections import deque


class LogBuffer:
    def __init__(self, max_entries=100):
        self._buf = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def add(self, text):
        entry = {"at": time.strftime("%H:%M:%S"), "text": str(text)}
        with self._lock:
            self._buf.append(entry)

    def items(self):
        """최신순."""
        with self._lock:
            return list(reversed(self._buf))

    def clear(self):
        with self._lock:
            self._buf.clear()
