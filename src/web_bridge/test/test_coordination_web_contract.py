from pathlib import Path



WORKSPACE = Path(__file__).resolve().parents[3]
BRIDGE = WORKSPACE / 'src/web_bridge/motion_web_bridge/bridge_node.py'


def test_user_web_exposes_only_local_high_level_group_control():
    # 라우트가 어느 모듈에 있든 계약은 같다 · 웹 경계 전체를 본다
    source = '\n'.join(
        path.read_text(encoding='utf-8')
        for path in sorted(BRIDGE.parent.rglob('*.py'))
    )
    assert "@app.get('/api/coordination')" in source
    assert "@app.put('/api/coordination/settings')" in source
    assert "@app.post('/api/coordination/control')" in source
    assert "@app.post('/api/coordination/local-control')" in source
    assert "@app.get('/api/coordination/local-status')" in source
    assert '/api/coordination/pairing/' not in source
    assert '8010' not in source


