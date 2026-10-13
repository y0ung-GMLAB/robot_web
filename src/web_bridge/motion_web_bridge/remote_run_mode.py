"""같은 망 다른 로봇 PC 의 운전 모드 보기·바꾸기 · 2026-10-13 (사용자 요청)

밤샘 시험(5대 F-1)이 막혔다 · floating1~3 을 스케줄 모드로 바꾸려면 그 PC 화면에 따로 들어가야 했다.
이 PC 서버가 같은 망 PC 표(`runtime.network_pcs`)의 **로봇 PC** 웹을 대신 부른다(브라우저가 남의 주소를
직접 부르지 않는다 · 모든 PC 업데이트와 같은 길) · 스피커는 운전 모드가 없어 뺀다.

    보기      GET  <그 PC>/api/schedule/status · run_mode
    바꾸기    PUT  <그 PC>/api/schedule/mode {run_mode}
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Mapping, Optional

RUN_MODES = ('schedule', 'manual', 'off')
STATUS_TIMEOUT_SEC = 3.0
SET_TIMEOUT_SEC = 5.0


def _http(url: str, *, method: str = 'GET', body: Optional[Mapping[str, Any]] = None, timeout: float) -> Dict[str, Any]:
    data = json.dumps(dict(body)).encode('utf-8') if body is not None else None
    request = urllib.request.Request(url, method=method, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 · 같은 망 PC
        payload = json.loads(response.read().decode('utf-8') or '{}')
    return payload if isinstance(payload, dict) else {}


def robots(network_pcs: Any) -> List[Mapping[str, Any]]:
    return [pc for pc in (network_pcs or []) if isinstance(pc, Mapping) and str(pc.get('role') or 'robot') != 'speaker']


def run_modes(network_pcs: Any, local_mode: Callable[[], str], http: Callable[..., Dict[str, Any]] = _http) -> Dict[str, Any]:
    """PC 마다 지금 운전 모드 · 못 읽은 PC 는 이유"""
    rows = []
    for pc in robots(network_pcs):
        row = {'pc_id': str(pc.get('pc_id') or ''), 'display_name': str(pc.get('display_name') or pc.get('pc_id') or ''),
               'is_local': bool(pc.get('is_local')), 'online': pc.get('online', True) is not False, 'run_mode': '', 'error': ''}
        if row['is_local']:
            row['run_mode'] = local_mode()
        elif not row['online'] or not pc.get('web_url'):
            row['error'] = '연결 안 됨'
        else:
            try:
                row['run_mode'] = str(http(f"{pc['web_url']}/api/schedule/status", timeout=STATUS_TIMEOUT_SEC).get('run_mode') or '')
            except (OSError, urllib.error.URLError, ValueError) as exc:
                row['error'] = f'읽지 못함 · {exc}'
        rows.append(row)
    return {'success': True, 'pcs': rows}


def set_run_mode(
    network_pcs: Any, pc_ids: List[str], run_mode: str,
    local_set: Callable[[str], Dict[str, Any]], http: Callable[..., Dict[str, Any]] = _http,
) -> Dict[str, Any]:
    """고른 PC 들의 운전 모드를 바꾼다 · PC 마다 결과"""
    mode = str(run_mode or '').strip().lower()
    if mode not in RUN_MODES:
        return {'success': False, 'message': 'run_mode 는 schedule · manual · off 중 하나여야 합니다'}
    known = {str(pc.get('pc_id') or ''): pc for pc in robots(network_pcs)}
    results = []
    for pc_id in [str(p) for p in pc_ids or []]:
        pc = known.get(pc_id)
        if pc is None:
            results.append({'pc_id': pc_id, 'success': False, 'message': '같은 망 로봇 PC 표에 없습니다'})
            continue
        try:
            if pc.get('is_local'):
                local_set(mode)
            else:
                if pc.get('online', True) is False or not pc.get('web_url'):
                    raise OSError('연결 안 됨')
                answer = http(f"{pc['web_url']}/api/schedule/mode", method='PUT', body={'run_mode': mode}, timeout=SET_TIMEOUT_SEC)
                if answer.get('success') is False or (answer.get('run_mode') and answer.get('run_mode') != mode):
                    raise ValueError(str(answer.get('message') or answer.get('detail') or '그 PC 가 거절했습니다'))
            results.append({'pc_id': pc_id, 'success': True, 'run_mode': mode})
        except (OSError, urllib.error.URLError, ValueError, RuntimeError) as exc:
            results.append({'pc_id': pc_id, 'success': False, 'message': str(exc)})
    failed = [r for r in results if not r['success']]
    names = {'schedule': '스케줄', 'manual': '수동', 'off': '끔'}
    return {
        'success': not failed and bool(results),
        'message': (f"{' · '.join(r['pc_id'] for r in results)} 을(를) {names[mode]} 모드로 바꿨습니다" if not failed
                    else ' / '.join(f"{r['pc_id']} 실패 · {r['message']}" for r in failed)),
        'results': results,
    }
