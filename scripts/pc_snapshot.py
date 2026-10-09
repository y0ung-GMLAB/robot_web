#!/usr/bin/env python3
"""PC 설정 사진 찍기 · 껐다 켜기 전후 비교 · 2026-10-09

같은 망의 노트북에서 로봇 PC·스피커 PC 웹에 **읽기만** 해서 설정을 JSON 으로 남기고,
나중에 찍은 것과 비교해 바뀐 칸만 보여 준다 · 아무것도 바꾸지 않는다 (GET 만).

    python scripts/pc_snapshot.py save before 172.16.8.21 172.16.8.22 172.16.8.24 172.16.8.30:8100
    (전원 껐다 켜기)
    python scripts/pc_snapshot.py save after  172.16.8.21 172.16.8.22 172.16.8.24 172.16.8.30:8100
    python scripts/pc_snapshot.py diff before after

주소에 포트가 없으면 8000(로봇 웹) · 스피커는 `:8100` 을 붙인다 · 결과는
`log/pc_snapshot/<이름>.json` · 파이썬 기본 모듈만 쓴다(노트북에 설치할 것 없음).

비교에서 빼는 것 · 시각 · 경과 시간 · 위치값 · 통신 상태처럼 늘 바뀌는 칸
(`VOLATILE_KEYS` · `VOLATILE_SUFFIXES`) · 설정이 남았는지만 본다.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROBOT_ENDPOINTS = (
    '/api/system/version',
    '/api/system/update',
    '/api/system/time',
    '/api/system/wifi',
    '/api/coordination',
    '/api/schedule/status',
    '/api/schedule/list',
    '/api/motion-mappings',
    '/api/motor-config',
    '/api/motor-config/absolute-setup',
    '/api/robot-pack',
    '/api/motion-files',
    '/api/motion-run/status',
)
SPEAKER_ENDPOINTS = (
    '/api/system/update',
    '/api/status',
)

#: 늘 바뀌는 칸 · 이름 그대로
VOLATILE_KEYS = {
    'tail', 'log', 'rc', 'unit', 'message', 'status_age_sec', 'boot_id', 'received_monotonic',
    'now', 'server_time', 'uptime_sec', 'position_deg', 'position_rad', 'velocity', 'torque',
    'actual', 'peers', 'execution', 'alarms', 'network_pcs', 'state_age_sec', 'progress',
    'last_failure', 'loop_lag_ms', 'signal', 'scan', 'networks', 'preview', 'sent_at', 'local_time',
    'utc_time', 'clock_age_sec',
}
#: 늘 바뀌는 칸 · 끝 글자
VOLATILE_SUFFIXES = ('_at', '_monotonic', '_stamp', '_age', '_age_sec', '_ms')


def base_url(address: str) -> str:
    text = address.strip().rstrip('/')
    if not text.startswith('http'):
        text = f'http://{text}'
    host = text.split('://', 1)[1]
    if ':' not in host:
        text = f'{text}:8000'
    return text


def fetch(url: str, timeout: float = 8.0) -> Tuple[Any, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8')), ''
    except urllib.error.HTTPError as exc:
        return None, f'HTTP {exc.code}'
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, str(getattr(exc, 'reason', exc))


def snapshot(addresses: Iterable[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for address in addresses:
        url = base_url(address)
        speaker = url.endswith(':8100')
        pc: Dict[str, Any] = {}
        for path in (SPEAKER_ENDPOINTS if speaker else ROBOT_ENDPOINTS):
            data, error = fetch(url + path)
            pc[path] = data if error == '' else {'_error': error}
        result[url] = pc
        reachable = sum(1 for value in pc.values() if not (isinstance(value, dict) and '_error' in value))
        print(f'{url} · {reachable}/{len(pc)} 응답')
    return result


def flatten(value: Any, prefix: str = '') -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key)
            if name in VOLATILE_KEYS or name.endswith(VOLATILE_SUFFIXES):
                continue
            out.update(flatten(item, f'{prefix}.{name}' if prefix else name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.update(flatten(item, f'{prefix}[{index}]'))
    else:
        out[prefix] = value
    return out


def diff(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for url in sorted(set(before) | set(after)):
        a = flatten(before.get(url, {}))
        b = flatten(after.get(url, {}))
        changed = [
            (key, a.get(key, '(없음)'), b.get(key, '(없음)'))
            for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)
        ]
        lines.append(f'== {url} · 바뀐 칸 {len(changed)}개')
        for key, old, new in changed:
            lines.append(f'  {key}: {json.dumps(old, ensure_ascii=False)} → {json.dumps(new, ensure_ascii=False)}')
    return lines


def main(argv: List[str]) -> int:
    folder = Path(__file__).resolve().parents[1] / 'log' / 'pc_snapshot'
    if len(argv) >= 3 and argv[0] == 'save':
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{argv[1]}.json'
        path.write_text(json.dumps(snapshot(argv[2:]), ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'저장 · {path}')
        return 0
    if len(argv) == 3 and argv[0] == 'diff':
        before = json.loads((folder / f'{argv[1]}.json').read_text(encoding='utf-8'))
        after = json.loads((folder / f'{argv[2]}.json').read_text(encoding='utf-8'))
        print('\n'.join(diff(before, after)))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
