"""재생 엔진. aplay 서브프로세스를 신호로 제어한다.

ROS와 무관하다 — 이 파일은 rclpy를 import하지 않는다.
"""
import os
import signal
import subprocess
import threading
import time

IDLE = "idle"
PLAYING = "playing"
PAUSED = "paused"


class Player:
    def __init__(self, logbuf):
        self._log = logbuf
        self._lock = threading.RLock()
        self._proc = None
        self._state = IDLE
        self._file = ""
        threading.Thread(target=self._watch, daemon=True).start()

    # ---- 조회 -------------------------------------------------------
    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def current_file(self):
        with self._lock:
            return self._file

    def is_active(self):
        return self.state in (PLAYING, PAUSED)

    # ---- 제어 -------------------------------------------------------
    def play(self, file_path, device):
        """재생 시작. 이미 재생 중이면 정리하고 처음부터 다시 시작한다."""
        with self._lock:
            self._kill_locked()
            if not file_path:
                self._log.add("재생 실패: 음성 파일이 지정되지 않았습니다")
                return False
            if not os.path.isfile(file_path):
                self._log.add("재생 실패: 파일을 찾을 수 없습니다 (%s)" % file_path)
                return False
            try:
                self._proc = subprocess.Popen(
                    ["aplay", "-q", "-D", device, file_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except FileNotFoundError:
                self._log.add("재생 실패: aplay 명령을 찾을 수 없습니다")
                return False
            except Exception as exc:
                self._log.add("재생 실패: %s" % exc)
                return False
            self._file = file_path
            self._state = PLAYING
            return True

    def pause(self):
        with self._lock:
            if self._proc is not None and self._state == PLAYING:
                try:
                    os.kill(self._proc.pid, signal.SIGSTOP)
                except OSError:
                    return False
                self._state = PAUSED
                self._log.add("일시정지")
                return True
        return False

    def resume(self):
        with self._lock:
            if self._proc is not None and self._state == PAUSED:
                try:
                    os.kill(self._proc.pid, signal.SIGCONT)
                except OSError:
                    return False
                self._state = PLAYING
                self._log.add("재개")
                return True
        return False

    def stop(self):
        with self._lock:
            active = self._proc is not None
            self._kill_locked()
        if active:
            self._log.add("정지")
        return active

    # ---- 내부 -------------------------------------------------------
    def _kill_locked(self):
        proc = self._proc
        self._proc = None
        self._state = IDLE
        if proc is None:
            return
        try:
            # 일시정지 상태면 먼저 깨워야 SIGTERM이 처리된다
            try:
                os.kill(proc.pid, signal.SIGCONT)
            except OSError:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        except Exception:
            pass
        finally:
            try:
                if proc.stderr:
                    proc.stderr.close()
            except Exception:
                pass

    def _watch(self):
        """자연 종료를 감지해 상태를 idle로 되돌린다."""
        while True:
            time.sleep(0.2)
            with self._lock:
                proc = self._proc
                if proc is None or proc.poll() is None:
                    continue
                rc = proc.returncode
                err = ""
                try:
                    if proc.stderr:
                        err = proc.stderr.read().decode("utf-8", "replace").strip()
                        proc.stderr.close()
                except Exception:
                    pass
                self._proc = None
                self._state = IDLE
            if rc != 0:
                self._log.add("재생 종료(코드 %s) %s" % (rc, err[:150]))
