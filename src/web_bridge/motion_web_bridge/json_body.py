"""큰 JSON 응답은 작업 스레드에서 · 잘게 나눠 글로 만든다 · 수정 목록 170

`async def` 길이 사전을 돌려주면 FastAPI 가 이벤트 루프에서 `jsonable_encoder` 로 통째로 한 번 베끼고
`json.dumps` 한다 · 920 s 애니 MuJoCo 미리보기(5.5만 프레임 × 30 칸)는 개발 PC 에서도 루프를 0.5 s ·
3D 「Blender 뷰」 조인트 값(46만 값)은 0.15 s 막았다 · 그 사이 연동 노드가 50 ms 마다 묻는
`/api/coordination/local-status`(0.25 s 제한)가 늦어 그룹이 「웹 서비스 끊김」 으로 섰다
(NY 2026-11-03 05:23 floating1 · 3D 를 켠 직후).

스레드로 옮기는 것만으로는 모자라다 · `json.dumps` 는 C 한 번이라 끝날 때까지 GIL 을 놓지 않는다
(13 MB 면 0.2 s 동안 루프가 못 돈다). 그래서 큰 목록은 `CHUNK_ITEMS` 개씩 나눠 따로 글로 만들고 잇는다 ·
사이사이 루프가 돈다. 글은 `JSONResponse` 와 같다(`ensure_ascii=False` · 구분자 공백 없음 · NaN 거절).
"""

import json
from typing import Any, List

from fastapi.responses import Response

#: 한 번에 글로 만들 목록 칸 수 · 프레임 행(30 칸) 1000 개면 몇 ms
CHUNK_ITEMS = 1000


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=None, separators=(',', ':'), default=str)


def _encode(value: Any, out: List[str]) -> None:
    if isinstance(value, list) and len(value) > CHUNK_ITEMS:
        out.append('[')
        for start in range(0, len(value), CHUNK_ITEMS):
            if start:
                out.append(',')
            out.append(_dumps(value[start:start + CHUNK_ITEMS])[1:-1])
        out.append(']')
        return
    if isinstance(value, dict) and value and all(isinstance(key, str) for key in value):
        out.append('{')
        for index, (key, item) in enumerate(value.items()):
            if index:
                out.append(',')
            out.append(_dumps(key))
            out.append(':')
            _encode(item, out)
        out.append('}')
        return
    out.append(_dumps(value))


def json_text(payload: Any) -> str:
    """`JSONResponse` 와 같은 글 · 큰 목록은 나눠서"""
    out: List[str] = []
    _encode(payload, out)
    return ''.join(out)


def json_response(payload: Any) -> Response:
    """작업 스레드에서 부른다 · 루프는 바이트만 보낸다"""
    return Response(content=json_text(payload).encode('utf-8'), media_type='application/json')
