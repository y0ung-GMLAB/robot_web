"""진입점 — 설정 로드 → 앱 조립 → uvicorn 기동."""
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import uvicorn  # noqa: E402

from api import create_app  # noqa: E402
from state import AppState  # noqa: E402


def main():
    state = AppState()
    app = create_app(state)
    host = state.cfg["web"]["host"]
    port = int(state.cfg["web"]["port"])
    state.startup()
    print("스피커 트리거 앱 실행 중 → http://%s:%d" % (host, port))
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        state.shutdown()


if __name__ == "__main__":
    main()
