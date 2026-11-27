"""다른 로봇 PC 운전 모드 보기·바꾸기 · 2026-10-13 (밤샘 시험 F-1 이 막혔다)"""

from motion_web_bridge import remote_run_mode as rr

PCS = [
    {'pc_id': 'floating4', 'is_local': True, 'web_url': 'http://10.0.0.4:8000'},
    {'pc_id': 'floating1', 'web_url': 'http://10.0.0.1:8000'},
    {'pc_id': 'floating2', 'online': False, 'web_url': 'http://10.0.0.2:8000'},
    {'pc_id': 'speaker', 'role': 'speaker', 'web_url': 'http://10.0.0.9:8100'},
]


def test_modes_are_read_from_each_robot_pc_speaker_excluded():
    calls = []

    def http(url, **kwargs):
        calls.append(url)
        return {'run_mode': 'manual'}

    rows = rr.run_modes(PCS, lambda: 'schedule', http)['pcs']
    assert [(r['pc_id'], r['run_mode'], bool(r['error'])) for r in rows] == [
        ('floating4', 'schedule', False), ('floating1', 'manual', False), ('floating2', '', True)]
    assert calls == ['http://10.0.0.1:8000/api/schedule/status']


def test_set_calls_the_other_pc_and_the_local_service():
    sent, local = [], []

    def http(url, **kwargs):
        sent.append((url, kwargs.get('method'), kwargs.get('body')))
        return {'status': 'ok', 'run_mode': 'schedule'}

    result = rr.set_run_mode(PCS, ['floating1', 'floating4'], 'schedule', local.append, http)
    assert result['success'] is True
    assert sent == [('http://10.0.0.1:8000/api/schedule/mode', 'PUT', {'run_mode': 'schedule'})]
    assert local == ['schedule']


def test_unknown_offline_or_speaker_pcs_fail_and_bad_modes_are_refused():
    result = rr.set_run_mode(PCS, ['floating2', 'speaker', 'nope'], 'manual', lambda _m: None, lambda *a, **k: {})
    assert result['success'] is False and len(result['results']) == 3
    assert rr.set_run_mode(PCS, ['floating1'], 'auto', lambda _m: None)['success'] is False
